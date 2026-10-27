"""Bounded detect, propose and independently verify workflow."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.analysis_engine import build_context, detect, rule_repair
from src.analysis_engine.contracts import DetectionResult
from src.model.candidate_generator import analyze_and_repair
from src.model.repair_model import ModelProvider
from .explanation import generate_beginner_explanation
from .verification import VerificationResult, source_hash, verify_candidate


class PipelineReport(BaseModel):
    status: str
    reason: str
    original_hash: str
    detection: DetectionResult
    context: dict[str, Any] | None = None
    repair: dict[str, Any] | None = None
    attempts: list[VerificationResult] = Field(default_factory=list)
    selected: VerificationResult | None = None
    repaired_code: str | None = None
    generation_error: str | None = None
    explanation: dict[str, Any] | None = None


def run_pipeline(code: str, language: str, *, max_attempts: int = 3,
                 provider: ModelProvider | None = None, include_model: bool = True) -> PipelineReport:
    if not isinstance(code, str) or not code.strip() or len(code.encode("utf-8")) > 100_000:
        raise ValueError("code must be non-empty and at most 100000 UTF-8 bytes")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    detection = detect(code, language, layers="fast")
    report = PipelineReport(status="NOT_REPAIRED", reason="no error detected", original_hash=source_hash(code),
                            detection=detection)

    def _finalize(rep: PipelineReport) -> PipelineReport:
        rep.explanation = generate_beginner_explanation(
            rep.status,
            rep.reason,
            rep.detection,
            code,
            language,
            context=rep.context,
            repair=rep.repair,
            selected=rep.selected,
            repaired_code=rep.repaired_code,
        )
        return rep

    if detection.root is None:
        return _finalize(report)
    context = build_context(code, detection.root, language, detection.diagnostics)
    report.context = context.model_dump(exclude={"code"})
    rules = rule_repair(context)
    report.repair = rules.model_dump()

    proposals: list[tuple[str, str]] = []
    if rules.chosen:
        proposals.append(("rule_" + rules.chosen.rule_id, rules.chosen.code))
    proposals.extend(("rule_" + c.rule_id, c.code) for c in rules.rule_candidates)
    if include_model:
        try:
            models = analyze_and_repair(context, k=min(max_attempts, 3), provider=provider)
            proposals.extend((c.candidate_id, c.repaired_code) for c in models)
        except Exception as exc:
            report.generation_error = f"candidate generation failed: {type(exc).__name__}"

    seen = {source_hash(code)}
    for candidate_id, candidate_code in proposals:
        digest = source_hash(candidate_code)
        if digest in seen:
            continue
        seen.add(digest)
        result = verify_candidate(code, candidate_code, language, candidate_id=candidate_id,
                                  expected_hash=report.original_hash)
        report.attempts.append(result)
        if result.status == "VERIFIED":
            report.status = "VERIFIED"
            report.reason = result.reason
            report.selected = result
            report.repaired_code = candidate_code
            return _finalize(report)
        if len(report.attempts) >= max_attempts:
            break
    if not report.attempts:
        report.reason = report.generation_error or "no safe distinct repair candidate available for these diagnostics"
    elif any(a.status == "INCONCLUSIVE" for a in report.attempts):
        report.status = "INCONCLUSIVE"
        report.reason = "verification could not complete for every attempt"
    else:
        report.reason = "no candidate passed verification within attempt budget"
    return _finalize(report)
