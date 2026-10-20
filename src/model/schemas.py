"""Data contracts and schemas for the P3 ML Engineer repair layer.

These schemas define the hand-off from P2 (ErrorContext) to P3, the structured
model outputs, candidate representations, verification feedback, and conversions.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class RepairCategory(str, Enum):
    """Normalized repair categories aligned with Data Engineer and Analysis Engineer taxonomies."""
    SYNTAX = "syntax"
    INDENTATION = "indentation"
    DELIMITER_PUNCTUATION = "delimiter_punctuation"
    EXPRESSION_OPERATOR = "expression_operator"
    DECLARATION_IDENTIFIER = "declaration_identifier"
    FUNCTION_CALL_ARGUMENT = "function_call_argument"
    IMPORT = "import"
    TYPE_ERROR = "type_error"
    OTHER = "other"


# ---------------------------------------------------------------- Exceptions

class RepairModelError(Exception):
    """Base exception for repair model operations."""
    pass


class ModelOutputParseError(RepairModelError):
    """Raised when the model response cannot be parsed into the expected JSON contract."""
    pass


class ProviderUnavailableError(RepairModelError):
    """Raised when the requested model provider is unavailable or fails to respond."""
    pass


class ExcessiveEditError(RepairModelError):
    """Raised or flagged when candidate repair modifies more code than permitted."""
    pass


class UnchangedCodeError(RepairModelError):
    """Raised when a candidate repair leaves the code identical to the broken source."""
    pass


# ---------------------------------------------------------------- Model Output

class StructuredModelOutput(BaseModel):
    """Contract for the raw structured output returned by an LLM or repair model."""
    repaired_code: str = Field(description="Complete repaired source code.")
    repair_category: str = Field(default="syntax", description="Category of error repaired.")
    root_cause: str = Field(default="", description="Short explanation of the error and fix.")
    target_line: Optional[int] = Field(default=None, ge=1, description="Line number targeted by the repair.")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Self-reported confidence in the repair.")

    @field_validator("repaired_code")
    @classmethod
    def validate_non_empty_code(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("repaired_code must be a non-empty string")
        return v

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return round(float(v), 3)


# ---------------------------------------------------------------- Candidate Contract

class MLRepairCandidate(BaseModel):
    """Validated repair candidate produced by the P3 ML layer for P4 verification."""
    candidate_id: str = Field(description="Unique identifier for this candidate.")
    repaired_code: str = Field(description="Complete repaired source code.")
    repair_category: str = Field(default="syntax", description="Taxonomy-aligned category.")
    root_cause: str = Field(default="", description="Explanation of root cause.")
    target_line: Optional[int] = Field(default=None, ge=1, description="Line targeted by repair.")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Heuristic or model confidence score.")
    unified_diff: str = Field(default="", description="Unified diff against original code.")
    model_name: str = Field(default="mock-repair-v1", description="Model or generator that produced candidate.")
    generation_method: str = Field(default="zero-shot", description="zero-shot, few-shot, or feedback-retry.")
    edit_distance: int = Field(default=0, description="Levenshtein character distance from original.")
    lines_changed: int = Field(default=0, description="Number of lines added, removed, or modified.")
    is_excessive: bool = Field(default=False, description="True if change exceeds minimality threshold.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic, ranking, or model metadata.")

    # Compatibility properties for P2 contracts
    @property
    def code(self) -> str:
        """Alias for repaired_code to match P2 RepairCandidate."""
        return self.repaired_code

    @property
    def line(self) -> int:
        """Alias for target_line to match P2 RepairCandidate."""
        return self.target_line or 1

    @property
    def description(self) -> str:
        """Alias for root_cause to match P2 RepairCandidate."""
        return self.root_cause or self.repair_category

    def to_analysis_candidate(self, compiles: bool = False):
        """Convert this candidate to P2's analysis_engine.contracts.RepairCandidate."""
        from src.analysis_engine.contracts import RepairCandidate as P2RepairCandidate
        return P2RepairCandidate(
            rule_id=self.candidate_id,
            description=self.description,
            line=self.line,
            confidence=self.confidence,
            code=self.repaired_code,
            compiles=compiles,
        )

    @classmethod
    def from_analysis_candidate(
        cls,
        cand,
        original_code: str = "",
        model_name: str = "rule-engine",
    ) -> "MLRepairCandidate":
        """Convert a P2 rule candidate into an MLRepairCandidate."""
        import difflib
        diff = ""
        if original_code:
            orig_lines = original_code.splitlines(keepends=True)
            new_lines = cand.code.splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(orig_lines, new_lines, fromfile="original", tofile="repaired"))
        return cls(
            candidate_id=f"rule_{cand.rule_id}",
            repaired_code=cand.code,
            repair_category="rule_based",
            root_cause=cand.description,
            target_line=cand.line,
            confidence=cand.confidence,
            unified_diff=diff,
            model_name=model_name,
            generation_method="rule-based",
            metadata={"compiles": cand.compiles},
        )


# Shared alias
RepairCandidate = MLRepairCandidate


# ---------------------------------------------------------------- Few-shot & Feedback

class FewShotExample(BaseModel):
    """Representative repair exemplar for few-shot prompting."""
    language: str
    category: str
    mutated_code: str
    repaired_code: str
    diagnostic_message: str
    root_cause: str = ""
    target_line: Optional[int] = None


class RepairFeedback(BaseModel):
    """Feedback from P4 verifier or previous execution attempt describing what failed."""
    candidate_id: str
    attempt_number: int = Field(default=1, ge=1)
    verification_status: str = Field(
        default="REJECTED",
        description="REJECTED, STILL_BROKEN, SYNTAX_REGRESSION, TEST_FAILURE, or COMPILATION_ERROR.",
    )
    error_message: Optional[str] = None
    new_diagnostics: List[Dict[str, Any]] = Field(default_factory=list)
    still_has_original_error: bool = False
    raw_compiler_output: Optional[str] = None
