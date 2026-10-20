"""Rule-based repair engine.

Runs every rule, applies each proposal to the source, and checks the patched program
with the detector. The chosen candidate is the highest-confidence one that compiles.
If none compiles, the highest-confidence candidate is returned with compiles=False.
"""

from typing import List

from src.analysis_engine.contracts import ErrorContext, RepairCandidate, RepairResult
from src.analysis_engine.detect.detector import detect
from src.analysis_engine.rules.repairs import RULES, apply_edits


MAX_VERIFIED = 60      # proposals checked with the compiler per error
MAX_REPORTED = 12     # candidates returned to the caller


def _compiles(code: str, language: str) -> bool:
    return not detect(code, language, layers="fast").detected


def rule_repair(ctx: ErrorContext) -> RepairResult:
    proposals = []
    for rule in RULES:
        proposals.extend(rule(ctx))

    seen = {ctx.code}
    verified: List[RepairCandidate] = []
    # Stable sort keeps rule order for equal confidence
    for proposal in sorted(proposals, key=lambda p: -p.confidence):
        if len(verified) >= MAX_VERIFIED:
            break
        patched = apply_edits(ctx.code, proposal.edits)
        if patched in seen:
            continue
        seen.add(patched)
        verified.append(RepairCandidate(
            rule_id=proposal.rule_id,
            description=proposal.description,
            line=proposal.edits[0][0],
            confidence=round(proposal.confidence, 3),
            code=patched,
            compiles=_compiles(patched, ctx.language),
        ))

    # Chosen = highest-confidence candidate that compiles, checked over all verified
    # candidates, before the reported list is trimmed
    chosen = next((c for c in verified if c.compiles), None)
    if chosen is None and verified:
        chosen = verified[0]
    return RepairResult(
        rule_candidates=verified[:MAX_REPORTED],
        chosen=chosen,
        applicable=bool(verified),
    )
