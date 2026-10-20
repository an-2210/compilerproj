"""Compiler Error Detection & Repair Data Engine package."""

from src.data_engine.schemas import (
    Language,
    SourceType,
    ErrorCategory,
    ValidationStatus,
    DatasetRecord,
    SeedExample,
    DiagnosticMessage,
    ErrorInfo,
)
from src.data_engine.mutation_registry import (
    MutationOperator,
    MutationResult,
    MutationRegistry,
    default_registry,
)
# Ensure all 15 mutation operators are registered on package import
import src.data_engine.mutation_engine

__all__ = [
    "Language",
    "SourceType",
    "ErrorCategory",
    "ValidationStatus",
    "DatasetRecord",
    "SeedExample",
    "DiagnosticMessage",
    "ErrorInfo",
    "MutationOperator",
    "MutationResult",
    "MutationRegistry",
    "default_registry",
]
