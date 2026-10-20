"""Tests for candidate generation, minimal-diff calculation, deduplication, and ranking."""

import json
import pytest

from src.analysis_engine.contracts import Diagnostic, ErrorContext
from src.model.candidate_generator import (
    analyze_and_repair,
    compute_edit_distance,
    compute_edit_metrics,
    compute_unified_diff,
    create_candidate,
    is_excessive_edit,
    normalize_code,
)
from src.model.repair_model import MockModelProvider
from src.model.schemas import (
    MLRepairCandidate,
    StructuredModelOutput,
    UnchangedCodeError,
)


def _make_context(code: str, line: int = 1, msg: str = "syntax error") -> ErrorContext:
    diag = Diagnostic(message=msg, line=line, severity="error", source="ast")
    return ErrorContext(
        language="python",
        code=code,
        root=diag,
        reported_line=line,
        candidate_lines=[line],
    )


# 11. Unified diff generation
def test_unified_diff_generation():
    orig = "def foo():\n    return 1\n"
    repaired = "def foo():\n    return 2\n"
    diff = compute_unified_diff(orig, repaired, "test.py")

    assert "--- a/test.py" in diff
    assert "+++ b/test.py" in diff
    assert "-    return 1" in diff
    assert "+    return 2" in diff


def test_edit_metrics_and_distance():
    orig = "x = 1\n"
    rep = "x = 100\n"
    metrics = compute_edit_metrics(orig, rep)
    assert metrics["lines_modified"] == 1
    assert metrics["lines_changed"] == 1
    assert compute_edit_distance("cat", "cut") == 1
    assert compute_edit_distance("same", "same") == 0


# 12. Excessive edit detection
def test_excessive_edit_detection():
    orig = "".join(f"line_{i} = {i}\n" for i in range(20))
    # Replace 18 out of 20 lines
    excessive_rep = "".join(f"rewritten_{i} = {i * 10}\n" for i in range(20))

    metrics = compute_edit_metrics(orig, excessive_rep)
    assert is_excessive_edit(metrics) is True

    # Single line edit on 20-line file is not excessive
    minimal_rep = orig.replace("line_1 = 1\n", "line_1 = 100\n")
    minimal_metrics = compute_edit_metrics(orig, minimal_rep)
    assert is_excessive_edit(minimal_metrics) is False


# 13. Unchanged candidate rejection
def test_unchanged_candidate_rejection():
    code = "x = 1\n"
    ctx = _make_context(code)
    output = StructuredModelOutput(
        repaired_code="x = 1\n",
        repair_category="syntax",
        root_cause="no change",
    )
    with pytest.raises(UnchangedCodeError):
        create_candidate(ctx, output, model_name="mock")


# 9. Multiple candidate generation
def test_multiple_candidate_generation():
    code = "def f(x)\n    return x\n"
    ctx = _make_context(code)

    # Provider returning distinct candidates
    resps = [
        json.dumps({"repaired_code": "def f(x):\n    return x\n", "confidence": 0.95}),
        json.dumps({"repaired_code": "def f(x=0):\n    return x\n", "confidence": 0.80}),
        json.dumps({"repaired_code": "def f(x, y=1):\n    return x\n", "confidence": 0.70}),
    ]
    provider = MockModelProvider(response_queue=resps)
    candidates = analyze_and_repair(ctx, k=3, provider=provider)

    assert len(candidates) == 3
    assert candidates[0].repaired_code != candidates[1].repaired_code
    assert candidates[1].repaired_code != candidates[2].repaired_code


# 10. Duplicate candidate removal
def test_duplicate_candidate_removal():
    code = "def f(x)\n    return x\n"
    ctx = _make_context(code)

    # Return identical repaired code three times with different confidence
    resps = [
        json.dumps({"repaired_code": "def f(x):\n    return x\n", "confidence": 0.9}),
        json.dumps({"repaired_code": "def f(x):\n    return x\n", "confidence": 0.7}),
        json.dumps({"repaired_code": "def f(x):\n    return x\n", "confidence": 0.5}),
    ]
    provider = MockModelProvider(response_queue=resps)
    candidates = analyze_and_repair(ctx, k=3, provider=provider)

    # Deduplication ensures only 1 candidate remains
    assert len(candidates) == 1
    assert candidates[0].confidence == 0.9


# 19. Compatibility with actual P4 candidate input
def test_candidate_contract_compatibility_with_p4_and_p2():
    code = "def f(x)\n    return x\n"
    ctx = _make_context(code)

    provider = MockModelProvider(mode="normal")
    candidates = analyze_and_repair(ctx, k=1, provider=provider)
    assert len(candidates) == 1

    cand = candidates[0]
    assert isinstance(cand, MLRepairCandidate)

    # Required fields for P4 verifier
    assert cand.candidate_id
    assert cand.repaired_code
    assert cand.unified_diff
    assert cand.target_line is not None
    assert 0.0 <= cand.confidence <= 1.0
    assert cand.model_name
    assert cand.generation_method

    # Round-trip JSON serialization
    serialized = cand.model_dump_json()
    reloaded = MLRepairCandidate.model_validate_json(serialized)
    assert reloaded.candidate_id == cand.candidate_id
    assert reloaded.repaired_code == cand.repaired_code

    # Convert to P2 RepairCandidate
    p2_cand = cand.to_analysis_candidate(compiles=True)
    assert p2_cand.code == cand.repaired_code
    assert p2_cand.compiles is True
    assert p2_cand.rule_id == cand.candidate_id


def test_top_level_package_proxy_import():
    """Verify that importing from 'model' (proxy) works identically to 'src.model'."""
    from model.candidate_generator import analyze_and_repair as proxy_aar
    from model.schemas import MLRepairCandidate as ProxyCandidate

    code = "def f(x)\n    return x\n"
    ctx = _make_context(code)
    cands = proxy_aar(ctx, k=1, provider=MockModelProvider(mode="normal"))
    assert len(cands) == 1
    assert isinstance(cands[0], ProxyCandidate)
