"""Tests for P3 RepairModel, prompts, provider abstraction, and structured output parsing."""

import json
import pytest

from src.analysis_engine.contracts import Diagnostic, ErrorContext
from src.model.prompts import (
    build_few_shot_prompt,
    build_zero_shot_prompt,
)
from src.model.repair_model import (
    MockModelProvider,
    RepairModel,
    parse_model_output,
)
from src.model.schemas import (
    FewShotExample,
    ModelOutputParseError,
    ProviderUnavailableError,
    StructuredModelOutput,
)


def _make_dummy_context(code: str = "def f(x)\n    return x\n", language: str = "python") -> ErrorContext:
    """Helper creating a valid ErrorContext matching P2 contract."""
    diag = Diagnostic(
        message="expected ':'",
        line=1,
        column=9,
        severity="error",
        source="ast",
        category="syntax",
        subcategory="missing_colon",
    )
    return ErrorContext(
        language=language,
        code=code,
        root=diag,
        reported_line=1,
        candidate_lines=[1],
        line_text="def f(x)",
        symbols=["f", "x"],
        imports=[],
        open_brackets=[],
        unclosed_at_eof=[],
        indent_of_line=0,
        enclosing_indents=[],
    )


# 1. Valid structured model response
def test_valid_structured_model_response():
    valid_json = json.dumps({
        "repaired_code": "def f(x):\n    return x\n",
        "repair_category": "syntax",
        "root_cause": "Missing colon after function signature",
        "target_line": 1,
        "confidence": 0.95,
    })
    parsed = parse_model_output(valid_json)
    assert isinstance(parsed, StructuredModelOutput)
    assert parsed.repaired_code == "def f(x):\n    return x\n"
    assert parsed.target_line == 1
    assert parsed.confidence == 0.95


def test_valid_structured_model_response_with_code_fences():
    fenced_output = """Here is the fix:
```json
{
  "repaired_code": "int main(void) {\\n    return 0;\\n}\\n",
  "repair_category": "syntax",
  "root_cause": "Added semicolon",
  "target_line": 2,
  "confidence": 0.9
}
```
Hope this helps!"""
    parsed = parse_model_output(fenced_output)
    assert parsed.repaired_code == "int main(void) {\n    return 0;\n}\n"
    assert parsed.repair_category == "syntax"


# 2. Invalid JSON response
def test_invalid_json_response_raises():
    invalid_raw = "This is just prose explaining what to do without any valid JSON."
    with pytest.raises(ModelOutputParseError):
        parse_model_output(invalid_raw)

    malformed_json = '{"repaired_code": "foo", "confidence": invalid_num}'
    with pytest.raises(ModelOutputParseError):
        parse_model_output(malformed_json)


# 3. Missing repaired code
def test_missing_or_empty_repaired_code_raises():
    missing_code_json = json.dumps({
        "repair_category": "syntax",
        "root_cause": "Forgot to supply code",
    })
    with pytest.raises(ModelOutputParseError):
        parse_model_output(missing_code_json)

    empty_code_json = json.dumps({
        "repaired_code": "   \n  ",
        "repair_category": "syntax",
    })
    with pytest.raises(ModelOutputParseError):
        parse_model_output(empty_code_json)


# 4. Empty source input
def test_empty_source_input_rejected():
    diag = Diagnostic(message="empty file", line=1, source="ast")
    empty_ctx = ErrorContext(
        language="python",
        code="",
        root=diag,
        reported_line=1,
    )
    model = RepairModel()
    with pytest.raises(ValueError, match="non-empty string"):
        model.generate_repair(empty_ctx)


# 5. Invalid diagnostic/context input
def test_invalid_diagnostic_context_input_rejected():
    model = RepairModel()
    # Pydantic validates root type, but if None is somehow passed:
    with pytest.raises(Exception):
        ErrorContext(language="python", code="x = 1\n", root=None, reported_line=1)


# 6. Zero-shot generation
def test_zero_shot_generation_constructs_prompt_and_repairs():
    ctx = _make_dummy_context("def foo()\n    return 1\n")
    sys_prompt, user_prompt = build_zero_shot_prompt(ctx)

    assert "expert compiler error repair engineer" in sys_prompt.lower()
    assert "def foo()" in user_prompt
    assert "expected ':'" in user_prompt
    assert "JSON object" in user_prompt

    provider = MockModelProvider(mode="normal")
    model = RepairModel(provider=provider)
    result = model.generate_repair(ctx)

    assert isinstance(result, StructuredModelOutput)
    assert result.repaired_code.strip() == "def foo():\n    return 1"
    assert provider.call_count == 1


# 7. Few-shot generation with examples
def test_few_shot_generation_with_examples():
    ctx = _make_dummy_context("def f(x)\n    return x\n")
    examples = [
        FewShotExample(
            language="python",
            category="syntax",
            mutated_code="def g(a)\n    return a\n",
            repaired_code="def g(a):\n    return a\n",
            diagnostic_message="expected ':'",
            root_cause="Added missing colon",
            target_line=1,
        )
    ]
    sys_prompt, user_prompt = build_few_shot_prompt(ctx, examples)

    assert "REPRESENTATIVE REPAIR EXAMPLES" in user_prompt
    assert "def g(a)" in user_prompt
    assert "def g(a):" in user_prompt
    assert "def f(x)" in user_prompt

    model = RepairModel(provider=MockModelProvider(mode="normal"))
    result = model.generate_repair(ctx, examples=examples)
    assert isinstance(result, StructuredModelOutput)
    assert result.repaired_code.strip() == "def f(x):\n    return x"


# 8. Few-shot generation with no examples
def test_few_shot_generation_with_no_examples_degenerates_to_zero_shot():
    ctx = _make_dummy_context()
    sys_prompt, user_prompt = build_few_shot_prompt(ctx, examples=[])

    # Should not have the examples block
    assert "REPRESENTATIVE REPAIR EXAMPLES" not in user_prompt
    assert "def f(x)" in user_prompt


# 14. Provider timeout and failure
def test_provider_timeout_and_failure():
    ctx = _make_dummy_context()
    timeout_provider = MockModelProvider(mode="timeout")
    model = RepairModel(provider=timeout_provider)

    with pytest.raises(ProviderUnavailableError, match="timeout"):
        model.generate_repair(ctx)


# 17. No accidental modification of the original input
def test_no_accidental_modification_of_original_input():
    original_code = "def immutable_func(a, b)\n    return a + b\n"
    ctx = _make_dummy_context(original_code)

    model = RepairModel(provider=MockModelProvider(mode="normal"))
    result = model.generate_repair(ctx)

    # Assert ctx.code is unchanged
    assert ctx.code == original_code
    assert result.repaired_code != original_code


# 18. Compatibility with actual P2 output
def test_compatibility_with_actual_p2_output():
    from src.analysis_engine import build_context, detect

    broken_code = "def calculate_area(radius)\n    return 3.14 * radius * radius\n"
    detection = detect(broken_code, "python")
    assert detection.detected
    assert detection.root is not None

    p2_ctx = build_context(broken_code, detection.root, "python")
    assert isinstance(p2_ctx, ErrorContext)

    # Feed real P2 context into P3 RepairModel
    model = RepairModel(provider=MockModelProvider(mode="normal"))
    output = model.generate_repair(p2_ctx)

    assert isinstance(output, StructuredModelOutput)
    assert "def calculate_area(radius):" in output.repaired_code
