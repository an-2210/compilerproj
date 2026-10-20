"""Pydantic schemas and contracts for dataset generation and validation."""

from enum import Enum
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class Language(str, Enum):
    C = "c"
    CPP = "cpp"
    PYTHON = "python"


class SourceType(str, Enum):
    SYNTHETIC = "synthetic"
    SEED = "seed"
    REAL_BUG = "real_bug"


class ErrorCategory(str, Enum):
    SYNTAX = "syntax"
    DELIMITER_PUNCTUATION = "delimiter_punctuation"
    EXPRESSION_OPERATOR = "expression_operator"
    DECLARATION_IDENTIFIER = "declaration_identifier"
    FUNCTION_CALL_ARGUMENT = "function_call_argument"
    INDENTATION_BLOCK = "indentation_block"
    SEMANTIC = "semantic"
    TYPE_ERROR = "type_error"
    NONE = "none"
    UNKNOWN = "unknown"


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"
    INFO = "info"


class ValidationStatus(str, Enum):
    VALID_BASELINE = "VALID_BASELINE"
    MUTATION_REJECTED = "MUTATION_REJECTED"
    MUTANT_VALIDATED = "MUTANT_VALIDATED"
    MUTANT_UNVERIFIED = "MUTANT_UNVERIFIED"
    COMPILER_UNAVAILABLE = "COMPILER_UNAVAILABLE"
    QUARANTINED = "QUARANTINED"


class SplitType(str, Enum):
    TRAIN = "train"
    VAL = "val"
    TEST = "test"
    REAL_TEST = "real_test"


class SourceLocation(BaseModel):
    line: Optional[int] = Field(default=None, ge=1)
    column: Optional[int] = Field(default=None, ge=1)


class MutationMetadata(BaseModel):
    operator_id: str
    operator_version: str = "1.0"
    target_location: Optional[SourceLocation] = None
    seed: Optional[int] = None
    description: Optional[str] = None
    original_token: Optional[str] = None
    mutated_token: Optional[str] = None


class DiagnosticMessage(BaseModel):
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    raw_text: Optional[str] = None


class ErrorInfo(BaseModel):
    category: str
    subcategory: Optional[str] = None
    compiler: Optional[str] = None
    compiler_version: Optional[str] = None
    exit_code: Optional[int] = None
    diagnostics: List[DiagnosticMessage] = Field(default_factory=list)
    raw_output: Optional[str] = None
    execution_duration_ms: Optional[float] = None


class ExpectedProperties(BaseModel):
    should_parse: bool
    should_compile: bool
    intended_error_count: int = Field(default=1, ge=0)
    intended_category: Optional[str] = None
    intended_subcategory: Optional[str] = None


class ProvenanceMetadata(BaseModel):
    repository: Optional[str] = None
    commit: Optional[str] = None
    file_path: Optional[str] = None
    license: Optional[str] = None
    source_url: Optional[str] = None
    bug_id: Optional[str] = None
    fixed_code: Optional[str] = None
    author: Optional[str] = None


class DatasetRecord(BaseModel):
    """Canonical dataset record for every synthetic or real-bug example."""
    schema_version: str = "1.0"
    example_id: str
    source_type: SourceType
    language: Language
    source_code: str
    mutated_code: Optional[str] = None
    original_example_id: Optional[str] = None
    mutation: Optional[MutationMetadata] = None
    error: Optional[ErrorInfo] = None
    expected: ExpectedProperties
    provenance: ProvenanceMetadata = Field(default_factory=ProvenanceMetadata)
    validation_status: ValidationStatus
    quarantine_reason: Optional[str] = None
    split_group_id: str
    split: Optional[SplitType] = None

    @field_validator("example_id")
    @classmethod
    def validate_example_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("example_id must not be empty")
        return v.strip()

    @field_validator("split_group_id")
    @classmethod
    def validate_split_group_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("split_group_id must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_relationships(self) -> "DatasetRecord":
        # Mutants must have mutated_code
        if self.source_type == SourceType.SYNTHETIC:
            if not self.mutated_code:
                raise ValueError("Synthetic examples must provide mutated_code")
            if not self.original_example_id:
                raise ValueError("Synthetic examples must specify original_example_id")
        return self


class SeedExample(BaseModel):
    """Schema for hand-written seed programs."""
    example_id: str
    language: Language
    source_code: str
    description: str
    tags: List[str] = Field(default_factory=list)
    expected_to_compile: bool = True
    split_group_id: Optional[str] = None

    @field_validator("example_id")
    @classmethod
    def validate_example_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("example_id must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def populate_split_group(self) -> "SeedExample":
        if not self.split_group_id:
            self.split_group_id = self.example_id
        return self
