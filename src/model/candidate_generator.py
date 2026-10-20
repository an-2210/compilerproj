"""Candidate repair generation, minimal-diff calculation, candidate ranking and deduplication.

Exposes analyze_and_repair(ctx, feedback=None, k=3).
"""

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

from src.analysis_engine.contracts import ErrorContext
from src.model.repair_model import MockModelProvider, ModelProvider, RepairModel
from src.model.schemas import (
    ExcessiveEditError,
    FewShotExample,
    MLRepairCandidate,
    RepairFeedback,
    StructuredModelOutput,
    UnchangedCodeError,
)


# ---------------------------------------------------------------- Normalization & Diff Utilities

def normalize_code(code: str) -> str:
    """Normalize line endings and whitespace without altering code semantics.

    - Converts Windows CRLF to standard LF.
    - Strips trailing whitespace from each line.
    - Strips surrounding markdown code fences if accidentally included.
    - Ensures single trailing newline if code is non-empty.
    """
    if not isinstance(code, str):
        return ""

    text = code.replace("\r\n", "\n").replace("\r", "\n")

    # If the model enclosed the repaired code in ```python ... ```, strip the fence
    fence_match = re.search(r"```(?:\w+)?\n([\s\S]*?)\n```", text)
    if fence_match:
        text = fence_match.group(1)

    lines = [line.rstrip() for line in text.split("\n")]
    # Strip empty leading/trailing lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines) + ("\n" if lines else "")


def compute_unified_diff(original_code: str, repaired_code: str, filename: str = "source") -> str:
    """Generate standard unified diff between original and repaired code."""
    orig_lines = original_code.splitlines(keepends=True)
    repaired_lines = repaired_code.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        repaired_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,
    )
    return "".join(diff)


def compute_edit_distance(s1: str, s2: str) -> int:
    """Compute character-level Levenshtein edit distance."""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        return compute_edit_distance(s2, s1)
    if not s2:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def compute_edit_metrics(original_code: str, repaired_code: str) -> Dict[str, Any]:
    """Calculate detailed edit metrics: character distance, line diffs, and change ratio."""
    orig_lines = original_code.splitlines()
    rep_lines = repaired_code.splitlines()

    matcher = difflib.SequenceMatcher(None, orig_lines, rep_lines)
    lines_added = 0
    lines_deleted = 0
    lines_modified = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            lines_modified += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            lines_deleted += (i2 - i1)
        elif tag == "insert":
            lines_added += (j2 - j1)

    total_orig_lines = max(len(orig_lines), 1)
    lines_changed = lines_added + lines_deleted + lines_modified
    change_ratio = round(lines_changed / total_orig_lines, 3)

    char_dist = compute_edit_distance(original_code, repaired_code)

    return {
        "edit_distance": char_dist,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "lines_modified": lines_modified,
        "lines_changed": lines_changed,
        "change_ratio": change_ratio,
        "total_orig_lines": total_orig_lines,
    }


def is_excessive_edit(
    metrics: Dict[str, Any],
    max_change_ratio: float = 0.6,
    max_lines_changed: int = 50,
) -> bool:
    """Return True if the candidate change modifies an excessive portion of the source."""
    if metrics["total_orig_lines"] <= 3:
        # For tiny programs, changing 2 lines is not necessarily excessive
        return metrics["lines_changed"] > 5
    if metrics["change_ratio"] > max_change_ratio and metrics["lines_changed"] > 2:
        return True
    if metrics["lines_changed"] > max_lines_changed:
        return True
    return False


# ---------------------------------------------------------------- Candidate Construction

def create_candidate(
    ctx: ErrorContext,
    output: StructuredModelOutput,
    model_name: str,
    generation_method: str = "zero-shot",
    candidate_id: Optional[str] = None,
) -> MLRepairCandidate:
    """Build a validated MLRepairCandidate from model output, computing diffs and metrics."""
    orig_norm = normalize_code(ctx.code)
    rep_norm = normalize_code(output.repaired_code)

    if not rep_norm.strip():
        raise ValueError("Repaired code is empty after normalization")

    if rep_norm == orig_norm:
        raise UnchangedCodeError("Candidate repaired code is identical to original source code")

    diff = compute_unified_diff(orig_norm, rep_norm, filename=f"input.{ctx.language}")
    metrics = compute_edit_metrics(orig_norm, rep_norm)
    excessive = is_excessive_edit(metrics)

    cid = candidate_id or f"cand_{generation_method}_{abs(hash((rep_norm, output.target_line))) % 100000:05d}"

    # Determine target line if omitted by model
    target_line = output.target_line
    if target_line is None:
        # Find first modified line in diff
        orig_lines = orig_norm.splitlines()
        rep_lines = rep_norm.splitlines()
        for idx, (l1, l2) in enumerate(zip(orig_lines, rep_lines), start=1):
            if l1 != l2:
                target_line = idx
                break
        if target_line is None:
            target_line = ctx.reported_line

    metadata = {
        **metrics,
        "original_reported_line": ctx.reported_line,
        "candidate_lines": ctx.candidate_lines,
        "diagnostic_message": ctx.root.message,
    }

    return MLRepairCandidate(
        candidate_id=cid,
        repaired_code=rep_norm,
        repair_category=output.repair_category or ctx.root.category,
        root_cause=output.root_cause,
        target_line=target_line,
        confidence=output.confidence,
        unified_diff=diff,
        model_name=model_name,
        generation_method=generation_method,
        edit_distance=metrics["edit_distance"],
        lines_changed=metrics["lines_changed"],
        is_excessive=excessive,
        metadata=metadata,
    )


# ---------------------------------------------------------------- Candidate Ranking

def score_candidate(candidate: MLRepairCandidate, ctx: ErrorContext) -> float:
    """Compute a multi-factor score for ranking repair candidates.

    Signals:
    1. Model confidence (weight: 0.35)
    2. Minimality of diff / edit size (weight: 0.35)
    3. Target line matching candidate lines from P2 (weight: 0.20)
    4. Penalty for excessive changes (penalty: -0.40)
    """
    score = candidate.confidence * 0.35

    # Minimality score: decay as lines changed and edit distance grow
    lines_factor = max(0.0, 1.0 - (candidate.lines_changed * 0.1))
    score += lines_factor * 0.35

    # Target line relevance
    target = candidate.target_line
    if target is not None:
        if target in ctx.candidate_lines:
            score += 0.20
        elif target == ctx.reported_line:
            score += 0.15

    # Excessive edit penalty
    if candidate.is_excessive:
        score -= 0.40

    return round(score, 4)


# ---------------------------------------------------------------- Public API

def analyze_and_repair(
    ctx: ErrorContext,
    feedback: Optional[RepairFeedback] = None,
    k: int = 3,
    provider: Optional[ModelProvider] = None,
    few_shot_examples: Optional[List[FewShotExample]] = None,
    allow_excessive: bool = False,
) -> List[MLRepairCandidate]:
    """Primary P3 API: Generates and ranks up to k repair candidates for P4 verification.

    Inputs:
        ctx: P2's ErrorContext describing the detected error.
        feedback: Optional previous verification feedback from P4 for retry.
        k: Maximum number of repair candidates to return.
        provider: Model backend (defaults to MockModelProvider or configured provider).
        few_shot_examples: Optional exemplars for few-shot mode.
        allow_excessive: If False, filters out candidates flagged as excessive.

    Outputs:
        List of deduplicated, ranked MLRepairCandidate objects.
    """
    if not isinstance(ctx.code, str) or not ctx.code.strip():
        raise ValueError("Cannot repair empty code in ErrorContext")
    if ctx.root is None:
        raise ValueError("Cannot repair ErrorContext without root diagnostic")

    k = max(1, k)
    model = RepairModel(provider=provider or MockModelProvider())
    candidates: List[MLRepairCandidate] = []
    seen_code = set()

    # Temperature variations to encourage diversity across candidates
    temperatures = [0.0, 0.2, 0.5, 0.7, 0.9][: max(k * 2, 4)]
    gen_method = "feedback-retry" if feedback is not None else ("few-shot" if few_shot_examples else "zero-shot")

    for i, temp in enumerate(temperatures):
        if len(candidates) >= k:
            break

        try:
            structured = model.generate_repair(
                ctx=ctx,
                examples=few_shot_examples,
                feedback=feedback,
                previous_candidates=candidates,
                temperature=temp,
            )

            cand = create_candidate(
                ctx=ctx,
                output=structured,
                model_name=model.provider.get_model_name(),
                generation_method=gen_method,
                candidate_id=f"cand_{i + 1}_{model.provider.get_model_name()}",
            )

            if not allow_excessive and cand.is_excessive:
                continue

            # Deduplication by normalized code
            code_hash = hash(cand.repaired_code)
            if code_hash in seen_code:
                continue
            seen_code.add(code_hash)

            candidates.append(cand)

        except (UnchangedCodeError, ExcessiveEditError):
            continue
        except Exception:
            # Continue trying next temperature/sample
            continue

    # Rank candidates by multi-factor score
    ranked = sorted(candidates, key=lambda c: score_candidate(c, ctx), reverse=True)
    return ranked[:k]
