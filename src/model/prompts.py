"""Prompt construction for P3 ML Engineer repair models.

Supports:
1. Zero-shot prompts with rich P2 compiler context (code, line, diagnostics, symbols, brackets).
2. Few-shot prompts with exemplars filtered by language and category.
3. Feedback-based retry prompts incorporating P4 verification failure reports.
"""

from typing import List, Optional, Tuple
from src.analysis_engine.contracts import ErrorContext
from src.model.schemas import FewShotExample, MLRepairCandidate, RepairFeedback


SYSTEM_PROMPT = """You are an expert compiler error repair engineer.
Your task is to fix the single reported compiler, parser, or static analysis error in the provided program.

CRITICAL RULES:
1. Make the absolute minimal necessary change to fix the reported diagnostic.
2. Preserve existing logic, variable names, algorithms, comments, and program structure.
3. Do not perform any unrelated refactoring, styling changes, or formatting improvements.
4. Output MUST be valid, parseable JSON conforming strictly to the requested schema.
5. Do NOT include any markdown explanations, commentary, or text outside the JSON object.
"""

JSON_SCHEMA_INSTRUCTION = """Output MUST be a JSON object with this exact structure:
{
  "repaired_code": "<full repaired source code as a valid string>",
  "repair_category": "<syntax | indentation | delimiter_punctuation | expression_operator | declaration_identifier | function_call_argument | import | type_error | other>",
  "root_cause": "<concise explanation of why the compiler error happened and how you fixed it>",
  "target_line": <integer line number of the primary fix>,
  "confidence": <float between 0.0 and 1.0>
}
"""


def _format_code_with_line_numbers(code: str) -> str:
    """Helper to format source code with 1-based line numbers for model clarity."""
    lines = code.splitlines()
    pad = len(str(len(lines)))
    return "\n".join(f"{i + 1:>{pad}} | {line}" for i, line in enumerate(lines))


def build_zero_shot_prompt(ctx: ErrorContext) -> Tuple[str, str]:
    """Construct a zero-shot repair prompt from P2's ErrorContext.

    Returns:
        (system_prompt, user_prompt)
    """
    code_with_lines = _format_code_with_line_numbers(ctx.code)
    diag = ctx.root

    context_details = []
    context_details.append(f"- Reported Line: {ctx.reported_line}")
    if ctx.candidate_lines:
        context_details.append(f"- Candidate Line(s) for mistake: {ctx.candidate_lines}")
    if ctx.enclosing_scope:
        context_details.append(f"- Enclosing Scope: {ctx.enclosing_scope}")
    if ctx.symbols:
        context_details.append(f"- Visible Symbols: {', '.join(ctx.symbols[:15])}")
    if ctx.imports:
        context_details.append(f"- Existing Imports/Headers: {', '.join(ctx.imports)}")
    if ctx.open_brackets:
        brackets_str = ", ".join(f"'{b.char}' on line {b.line}:{b.column}" for b in ctx.open_brackets)
        context_details.append(f"- Unclosed Brackets at reported line: {brackets_str}")
    if ctx.unclosed_at_eof:
        brackets_eof = ", ".join(f"'{b.char}' on line {b.line}:{b.column}" for b in ctx.unclosed_at_eof)
        context_details.append(f"- Unclosed Brackets at EOF: {brackets_eof}")
    if ctx.language == "python" and ctx.indent_of_line is not None:
        context_details.append(f"- Indentation: {ctx.indent_of_line} spaces (enclosing blocks: {ctx.enclosing_indents})")

    context_block = "\n".join(context_details)

    user_prompt = f"""Language: {ctx.language}

### DIAGNOSTIC REPORT:
Source: {diag.source}
Severity: {diag.severity}
Message: {diag.message}
Reported Location: Line {diag.line or ctx.reported_line}, Column {diag.column or 'unknown'}
Category: {diag.category} / {diag.subcategory}

### ANALYSIS ENGINE CONTEXT:
{context_block}

### INPUT SOURCE CODE:
```
{code_with_lines}
```

Raw code without line numbers:
```
{ctx.code}
```

### TASK:
Fix the error described above. Produce the full, complete repaired source code with minimal modifications.
{JSON_SCHEMA_INSTRUCTION}
"""
    return SYSTEM_PROMPT, user_prompt


def build_few_shot_prompt(
    ctx: ErrorContext,
    examples: List[FewShotExample],
    max_examples: int = 3,
) -> Tuple[str, str]:
    """Construct a few-shot repair prompt using representative exemplars.

    If examples is empty, cleanly degenerates to zero-shot prompt.
    """
    if not examples:
        return build_zero_shot_prompt(ctx)

    # Prioritize examples matching language and category
    category = ctx.root.category
    ranked_examples = sorted(
        examples,
        key=lambda ex: (
            1 if ex.language == ctx.language else 0,
            1 if ex.category == category else 0,
        ),
        reverse=True,
    )[:max_examples]

    exemplars_text = []
    for i, ex in enumerate(ranked_examples, start=1):
        exemplars_text.append(f"""--- Example {i} ({ex.language} - {ex.category}) ---
Error Diagnostic: {ex.diagnostic_message}
Root Cause: {ex.root_cause}

Mutated Code:
```
{ex.mutated_code}
```

Repaired Code:
```
{ex.repaired_code}
```
""")

    few_shot_block = "\n".join(exemplars_text)

    # Get the zero-shot query portion
    _, user_query = build_zero_shot_prompt(ctx)

    combined_user_prompt = f"""### REPRESENTATIVE REPAIR EXAMPLES:
The following examples demonstrate fixing similar compiler errors with minimal edits:

{few_shot_block}

### NOW FIX THE TARGET CODE:
{user_query}
"""
    return SYSTEM_PROMPT, combined_user_prompt


def build_feedback_prompt(
    ctx: ErrorContext,
    feedback: RepairFeedback,
    previous_candidates: List[MLRepairCandidate],
) -> Tuple[str, str]:
    """Construct a retry prompt informed by P4 verification failure feedback.

    Distinguishes original diagnostic from new regression diagnostics and
    prevents repeating failed candidates.
    """
    _, base_prompt = build_zero_shot_prompt(ctx)

    # Identify the rejected candidate
    rejected_cand = next((c for c in previous_candidates if c.candidate_id == feedback.candidate_id), None)
    if not rejected_cand and previous_candidates:
        rejected_cand = previous_candidates[-1]

    history_entries = []
    for c in previous_candidates:
        history_entries.append(
            f"- Candidate {c.candidate_id} ({c.generation_method}):\n"
            f"  Diff:\n{c.unified_diff or c.repaired_code}"
        )
    history_block = "\n".join(history_entries) if history_entries else "None recorded."

    feedback_details = []
    feedback_details.append(f"- Attempt #{feedback.attempt_number} Failed with Status: {feedback.verification_status}")
    if feedback.error_message:
        feedback_details.append(f"- Verification Error: {feedback.error_message}")
    if feedback.still_has_original_error:
        feedback_details.append("- Original Error Status: STILL PRESENT (your previous patch did not resolve it).")
    if feedback.new_diagnostics:
        new_diags_str = "; ".join(str(d.get("message", d)) for d in feedback.new_diagnostics)
        feedback_details.append(f"- Regression / New Diagnostics Introduced: {new_diags_str}")
    if feedback.raw_compiler_output:
        feedback_details.append(f"- Raw Compiler Output from failed patch:\n```\n{feedback.raw_compiler_output}\n```")

    feedback_block = "\n".join(feedback_details)

    retry_user_prompt = f"""{base_prompt}

### ATTENTION: PREVIOUS REPAIR ATTEMPT REJECTED BY VERIFIER
Your previous repair candidate was tested by the Verification Engine (P4) and FAILED.
Do NOT repeat the same mistake. You must adjust your approach.

### VERIFICATION FEEDBACK:
{feedback_block}

### PREVIOUS REJECTED CANDIDATES (DO NOT REPEAT THESE):
{history_block}

### REFINED GOAL:
Generate a NEW, alternative repair that successfully fixes the original diagnostic WITHOUT introducing any new compiler errors.
{JSON_SCHEMA_INSTRUCTION}
"""
    return SYSTEM_PROMPT, retry_user_prompt
