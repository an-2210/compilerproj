"""Dataset validator: independently evaluates baselines and mutants against strict criteria."""

import logging
from typing import Dict, List, Optional, Tuple

from src.data_engine.schemas import (
    DatasetRecord,
    ValidationStatus,
    ErrorCategory,
    SourceType,
    SeedExample,
)
from src.data_engine.language_adapters import LanguageAdapter, CompilationResult, get_adapter
from src.data_engine.diagnostic_collector import DiagnosticCollector, categorize_diagnostic_message

logger = logging.getLogger(__name__)


class ValidationAssessment:
    """Detailed assessment of a single candidate record."""

    def __init__(
        self,
        status: ValidationStatus,
        reason: Optional[str] = None,
        observed_error_count: int = 0,
        intended_error_count: int = 1,
        category_matched: bool = False,
    ):
        self.status = status
        self.reason = reason
        self.observed_error_count = observed_error_count
        self.intended_error_count = intended_error_count
        self.category_matched = category_matched


class DatasetValidator:
    """Validates baseline programs and mutant candidates according to rigorous compiler ground truth."""

    def __init__(self, collector: Optional[DiagnosticCollector] = None):
        self.collector = collector or DiagnosticCollector()

    def validate_baseline(self, seed: SeedExample) -> Tuple[bool, Optional[str]]:
        """Verify that a baseline program compiles cleanly without errors."""
        adapter = self.collector.get_adapter_for(seed.language)
        if not adapter.is_available():
            return False, f"Compiler for {seed.language.value} is unavailable."

        res = adapter.compile_or_parse(seed.source_code)
        if not res.success:
            err = res.diagnostics[0].message if res.diagnostics else res.stderr
            return False, f"Baseline failed to compile: {err}"
        return True, None

    def assess_mutant(
        self,
        baseline_code: str,
        mutated_code: str,
        language_adapter: LanguageAdapter,
        intended_category: str,
        intended_subcategory: Optional[str] = None,
        allow_cascading: bool = False,
    ) -> Tuple[ValidationAssessment, CompilationResult]:
        """Compile mutant and assess whether the intended single error was correctly introduced."""
        if not language_adapter.is_available():
            return (
                ValidationAssessment(
                    status=ValidationStatus.COMPILER_UNAVAILABLE,
                    reason=f"Compiler tool {language_adapter.language.value} not available",
                ),
                CompilationResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="Compiler unavailable",
                    diagnostics=[],
                    tool_name="none",
                    compiler_available=False,
                ),
            )

        # Compile mutant
        comp_res = language_adapter.compile_or_parse(mutated_code)

        # Check 1: If mutant still compiles cleanly, the mutation was benign -> REJECT
        if comp_res.success:
            return (
                ValidationAssessment(
                    status=ValidationStatus.MUTATION_REJECTED,
                    reason="Mutated code still compiles cleanly without expected errors",
                    observed_error_count=0,
                    intended_error_count=1,
                    category_matched=False,
                ),
                comp_res,
            )

        # Check 2: Check timeout or process failure
        if comp_res.exit_code == -99:
            return (
                ValidationAssessment(
                    status=ValidationStatus.QUARANTINED,
                    reason="Compilation timed out during validation",
                    observed_error_count=0,
                    intended_error_count=1,
                ),
                comp_res,
            )

        diag_count = len(comp_res.diagnostics)
        observed_errors = sum(1 for d in comp_res.diagnostics if d.severity.value in ("error", "fatal error"))
        if observed_errors == 0 and not comp_res.success:
            # Fallback if unparsed error
            observed_errors = 1

        # Check 3: Check for severe cascading errors (> 6 diagnostics)
        if observed_errors > 6 and not allow_cascading:
            return (
                ValidationAssessment(
                    status=ValidationStatus.QUARANTINED,
                    reason=f"Severe cascading diagnostics ({observed_errors} errors observed) for single mutation",
                    observed_error_count=observed_errors,
                    intended_error_count=1,
                ),
                comp_res,
            )

        # Check 4: Diagnostic category consistency
        primary_msg = comp_res.diagnostics[0].message if comp_res.diagnostics else comp_res.stderr
        observed_cat, observed_subcat = categorize_diagnostic_message(primary_msg)

        # Category is matched if either primary category matches or it's a general syntax/semantic mismatch
        category_matched = (
            observed_cat == intended_category
            or intended_category in (ErrorCategory.SYNTAX.value, ErrorCategory.DELIMITER_PUNCTUATION.value)
            and observed_cat in (ErrorCategory.SYNTAX.value, ErrorCategory.DELIMITER_PUNCTUATION.value)
            or observed_cat == ErrorCategory.UNKNOWN.value
        )

        return (
            ValidationAssessment(
                status=ValidationStatus.MUTANT_VALIDATED,
                reason=None,
                observed_error_count=observed_errors,
                intended_error_count=1,
                category_matched=category_matched,
            ),
            comp_res,
        )

    def validate_record(self, record: DatasetRecord) -> Tuple[bool, List[str]]:
        """Validate an exported or loaded DatasetRecord against schema and consistency rules."""
        errors: List[str] = []

        if not record.example_id:
            errors.append("example_id cannot be empty")
        if not record.split_group_id:
            errors.append("split_group_id cannot be empty")

        if record.source_type == SourceType.SYNTHETIC:
            if not record.mutated_code:
                errors.append("Synthetic mutant must have mutated_code")
            if not record.original_example_id:
                errors.append("Synthetic mutant must reference original_example_id")
            if not record.mutation:
                errors.append("Synthetic mutant must include mutation metadata")

        if record.validation_status == ValidationStatus.MUTANT_VALIDATED:
            if not record.error or not record.error.diagnostics:
                errors.append("Validated mutant must have recorded diagnostics")

        return (len(errors) == 0, errors)
