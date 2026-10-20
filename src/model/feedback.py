"""Feedback-based repair retry mechanism consuming P4 verification outcomes."""

from typing import Any, Callable, Dict, List, Optional, Tuple

from src.analysis_engine.contracts import DetectionResult, ErrorContext
from src.model.candidate_generator import analyze_and_repair
from src.model.repair_model import ModelProvider
from src.model.schemas import FewShotExample, MLRepairCandidate, RepairFeedback


VerificationResult = Tuple[bool, RepairFeedback]
VerifierFunction = Callable[[MLRepairCandidate], VerificationResult]


def create_feedback_from_detection(
    candidate: MLRepairCandidate,
    original_ctx: ErrorContext,
    detection: DetectionResult,
    attempt_number: int = 1,
) -> RepairFeedback:
    """Helper that creates a RepairFeedback object from P2's DetectionResult on patched code."""
    if not detection.detected:
        return RepairFeedback(
            candidate_id=candidate.candidate_id,
            attempt_number=attempt_number,
            verification_status="VERIFIED",
            still_has_original_error=False,
            error_message="Verification passed: code compiled without error diagnostics.",
        )

    # Check if the original error is still present
    orig_msg = original_ctx.root.message.lower()
    still_present = any(orig_msg in d.message.lower() for d in detection.diagnostics)

    # Identify new diagnostics not in the original context
    new_diags = []
    for d in detection.diagnostics:
        if orig_msg not in d.message.lower():
            new_diags.append(d.model_dump())

    status = "STILL_BROKEN" if still_present else "SYNTAX_REGRESSION"
    error_msg = f"{status}: {detection.root.message if detection.root else 'compilation errors detected'}"

    return RepairFeedback(
        candidate_id=candidate.candidate_id,
        attempt_number=attempt_number,
        verification_status=status,
        error_message=error_msg,
        new_diagnostics=new_diags,
        still_has_original_error=still_present,
        raw_compiler_output="\n".join(d.raw or d.message for d in detection.diagnostics),
    )


def feedback_retry_loop(
    ctx: ErrorContext,
    verifier_fn: VerifierFunction,
    max_retries: int = 3,
    k: int = 1,
    provider: Optional[ModelProvider] = None,
    few_shot_examples: Optional[List[FewShotExample]] = None,
) -> Tuple[Optional[MLRepairCandidate], List[MLRepairCandidate], List[RepairFeedback]]:
    """Iteratively repairs code with P4 verification feedback until success or retry limit.

    Inputs:
        ctx: P2's ErrorContext (guaranteed immutable).
        verifier_fn: Callback accepting an MLRepairCandidate and returning (is_valid, RepairFeedback).
        max_retries: Maximum number of generation-verification cycles (>= 1).
        k: Candidates generated per round.
        provider: Model backend.
        few_shot_examples: Optional few-shot examples.

    Outputs:
        (successful_candidate_or_None, all_generated_candidates, feedback_history)
    """
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    all_candidates: List[MLRepairCandidate] = []
    feedback_history: List[RepairFeedback] = []
    current_feedback: Optional[RepairFeedback] = None
    seen_code_hashes = set()

    for attempt in range(1, max_retries + 1):
        candidates = analyze_and_repair(
            ctx=ctx,
            feedback=current_feedback,
            k=k,
            provider=provider,
            few_shot_examples=few_shot_examples,
        )

        if not candidates:
            # Model failed to generate valid candidates in this round
            break

        # Filter out previously tested candidate code to prevent repeating failures
        new_candidates = [c for c in candidates if hash(c.repaired_code) not in seen_code_hashes]
        if not new_candidates:
            # Generation stagnated into previously rejected candidates
            break

        for cand in new_candidates:
            seen_code_hashes.add(hash(cand.repaired_code))
            all_candidates.append(cand)

            # Test candidate with verifier
            is_valid, feedback = verifier_fn(cand)
            feedback.attempt_number = attempt
            feedback_history.append(feedback)

            if is_valid:
                # Verifier confirmed the fix
                cand.metadata["verification_status"] = "PASSED"
                cand.metadata["verification_attempts"] = attempt
                return cand, all_candidates, feedback_history

            # Save latest feedback for next iteration prompt
            current_feedback = feedback

    # All attempts exhausted without verifier confirmation
    return None, all_candidates, feedback_history
