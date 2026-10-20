"""Analysis Engineer package: DETECT, CONTEXT and rule-based REPAIR.

Pipeline:  detect(code, language) -> build_context(code, root, language) -> rule_repair(ctx)
"""

from src.analysis_engine.contracts import (
    BracketInfo,
    DetectionResult,
    Diagnostic,
    ErrorContext,
    RepairCandidate,
    RepairResult,
)
from src.analysis_engine.detect.detector import detect
from src.analysis_engine.context.builder import build_context
from src.analysis_engine.rules.engine import rule_repair

__all__ = [
    "BracketInfo",
    "DetectionResult",
    "Diagnostic",
    "ErrorContext",
    "RepairCandidate",
    "RepairResult",
    "detect",
    "build_context",
    "rule_repair",
]
