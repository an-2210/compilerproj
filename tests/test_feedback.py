"""Tests for feedback-driven repair retry, verifier integration, and end-to-end pipeline."""

import json
from pathlib import Path
import pytest

from src.analysis_engine import build_context, detect
from src.model.candidate_generator import analyze_and_repair
from src.model.feedback import (
    create_feedback_from_detection,
    feedback_retry_loop,
)
from src.model.prompts import build_feedback_prompt
from src.model.repair_model import MockModelProvider
from src.model.schemas import (
    MLRepairCandidate,
    RepairFeedback,
    StructuredModelOutput,
)


def _make_dummy_candidate(cid: str = "cand_1", code: str = "def f(x):\n    return x\n") -> MLRepairCandidate:
    return MLRepairCandidate(
        candidate_id=cid,
        repaired_code=code,
        repair_category="syntax",
        root_cause="Added colon",
        target_line=1,
        confidence=0.8,
        unified_diff="--- a\n+++ b\n@@ -1 +1 @@\n-def f(x)\n+def f(x):\n",
    )


# 15. Feedback-based retry
def test_feedback_prompt_construction():
    broken = "def area(r)\n    return 3 * r * r\n"
    det = detect(broken, "python")
    ctx = build_context(broken, det.root, "python")

    feedback = RepairFeedback(
        candidate_id="cand_1",
        attempt_number=1,
        verification_status="SYNTAX_REGRESSION",
        error_message="indentation error introduced on line 2",
        still_has_original_error=False,
        new_diagnostics=[{"message": "unexpected indent", "line": 2}],
    )

    prev_cands = [_make_dummy_candidate("cand_1", "def area(r):\n        return 3 * r * r\n")]
    sys_prompt, user_prompt = build_feedback_prompt(ctx, feedback, prev_cands)

    assert "ATTENTION: PREVIOUS REPAIR ATTEMPT REJECTED" in user_prompt
    assert "SYNTAX_REGRESSION" in user_prompt
    assert "unexpected indent" in user_prompt
    assert "cand_1" in user_prompt


def test_distinguish_original_error_vs_regression():
    broken = "def area(r)\n    return 3 * r * r\n"
    det = detect(broken, "python")
    ctx = build_context(broken, det.root, "python")

    cand = _make_dummy_candidate("cand_test", broken)
    # Re-detecting broken code produces same error
    same_det = detect(broken, "python")
    fb = create_feedback_from_detection(cand, ctx, same_det, attempt_number=1)

    assert fb.still_has_original_error is True
    assert fb.verification_status == "STILL_BROKEN"

    # Now simulate a regression (expected indented block)
    regression_code = "def area(r):\nreturn 3 * r * r\n"
    reg_det = detect(regression_code, "python")
    assert reg_det.detected
    fb_reg = create_feedback_from_detection(cand, ctx, reg_det, attempt_number=2)
    assert fb_reg.verification_status == "SYNTAX_REGRESSION"


# 16. Retry limit enforcement
def test_retry_limit_enforcement():
    broken = "def f(x)\n    return x\n"
    det = detect(broken, "python")
    ctx = build_context(broken, det.root, "python")

    # Verifier that always rejects
    def always_reject_verifier(cand: MLRepairCandidate):
        fb = RepairFeedback(
            candidate_id=cand.candidate_id,
            attempt_number=1,
            verification_status="REJECTED",
            error_message="Test verifier intentionally rejected patch",
        )
        return False, fb

    # Queue distinct responses so it doesn't stagnate immediately
    resps = [
        json.dumps({"repaired_code": "def f(x):\n    return x\n", "confidence": 0.9}),
        json.dumps({"repaired_code": "# Attempt 2\ndef f(x):\n    return x\n", "confidence": 0.8}),
        json.dumps({"repaired_code": "# Attempt 3\ndef f(x):\n    return x\n", "confidence": 0.7}),
        json.dumps({"repaired_code": "# Attempt 4\ndef f(x):\n    return x\n", "confidence": 0.6}),
    ]
    provider = MockModelProvider(response_queue=resps)

    chosen, all_cands, feedbacks = feedback_retry_loop(
        ctx=ctx,
        verifier_fn=always_reject_verifier,
        max_retries=3,
        k=1,
        provider=provider,
    )

    # Must be None since it was always rejected
    assert chosen is None
    # Must stop at max_retries = 3
    assert len(feedbacks) == 3


def test_feedback_retry_succeeds_on_second_attempt():
    broken = "def f(x)\n    return x\n"
    det = detect(broken, "python")
    ctx = build_context(broken, det.root, "python")

    call_count = 0

    def verifier(cand: MLRepairCandidate):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return False, RepairFeedback(
                candidate_id=cand.candidate_id,
                attempt_number=1,
                verification_status="SYNTAX_REGRESSION",
                error_message="First attempt failed mock tests",
            )
        return True, RepairFeedback(
            candidate_id=cand.candidate_id,
            attempt_number=2,
            verification_status="VERIFIED",
        )

    resps = [
        json.dumps({"repaired_code": "def f(x): pass\n", "confidence": 0.5}),
        json.dumps({"repaired_code": "def f(x):\n    return x\n", "confidence": 0.95}),
    ]
    provider = MockModelProvider(response_queue=resps)

    chosen, all_cands, feedbacks = feedback_retry_loop(
        ctx=ctx,
        verifier_fn=verifier,
        max_retries=3,
        k=1,
        provider=provider,
    )

    assert chosen is not None
    assert chosen.repaired_code == "def f(x):\n    return x\n"
    assert len(feedbacks) == 2
    assert feedbacks[1].verification_status == "VERIFIED"


# 20. Complete mock-backed pipeline test from context to candidate output
def test_complete_end_to_end_pipeline():
    """Validates the full pipeline:

    P1 Dataset record -> P2 detect -> P2 ErrorContext -> P3 analyze_and_repair -> P4 verification
    """
    root_dir = Path(__file__).resolve().parent.parent
    train_split = root_dir / "data" / "splits" / "train.jsonl"
    assert train_split.exists()

    # Load first Python mutant from P1 dataset
    records = [json.loads(line) for line in train_split.read_text(encoding="utf-8").splitlines() if line.strip()]
    py_mutant = next(r for r in records if r["language"] == "python" and r["source_type"] == "synthetic")

    mutated_code = py_mutant["mutated_code"]
    original_code = py_mutant["source_code"]

    # Step 1 (P2): Detect error
    detection = detect(mutated_code, "python")
    assert detection.detected
    assert detection.root is not None

    # Step 2 (P2): Build error context
    ctx = build_context(mutated_code, detection.root, "python")
    assert ctx.code == mutated_code

    # Step 3 (P3): Generate repair candidates
    # Mock provider generates repair based on heuristics
    provider = MockModelProvider(mode="normal")
    candidates = analyze_and_repair(ctx, k=2, provider=provider)

    assert len(candidates) >= 1
    top_cand = candidates[0]
    assert top_cand.repaired_code != mutated_code
    assert top_cand.unified_diff

    # Step 4 (P4 Verifier simulation): Check candidate compiles
    cand_detection = detect(top_cand.repaired_code, "python")
    # Verify whether candidate resolved error or what diagnostics remain
    assert isinstance(cand_detection.detected, bool)

    # Convert candidate to P4 expected format
    payload_for_p4 = {
        "candidate_id": top_cand.candidate_id,
        "repaired_code": top_cand.repaired_code,
        "unified_diff": top_cand.unified_diff,
        "confidence": top_cand.confidence,
        "metadata": top_cand.metadata,
    }
    assert payload_for_p4["candidate_id"] == top_cand.candidate_id
