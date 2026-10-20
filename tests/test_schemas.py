"""Tests for schema definitions, validation, and contracts."""

import pytest
from pydantic import ValidationError

from src.data_engine.schemas import (
    DatasetRecord,
    SeedExample,
    Language,
    SourceType,
    ValidationStatus,
    ExpectedProperties,
    ErrorInfo,
    DiagnosticMessage,
    DiagnosticSeverity,
    MutationMetadata,
    SourceLocation,
    ProvenanceMetadata,
)


def test_valid_synthetic_record():
    record = DatasetRecord(
        schema_version="1.0",
        example_id="mut_001",
        source_type=SourceType.SYNTHETIC,
        language=Language.C,
        source_code="int main() { return 0; }",
        mutated_code="int main() { return 0 }",
        original_example_id="seed_001",
        mutation=MutationMetadata(
            operator_id="C_MISSING_SEMICOLON",
            target_location=SourceLocation(line=1, column=24),
        ),
        error=ErrorInfo(
            category="delimiter_punctuation",
            subcategory="missing_semicolon",
            compiler="gcc",
            compiler_version="16.1.0",
            exit_code=1,
            diagnostics=[
                DiagnosticMessage(
                    message="expected ';' before '}' token",
                    file="input.c",
                    line=1,
                    column=24,
                    severity=DiagnosticSeverity.ERROR,
                )
            ],
        ),
        expected=ExpectedProperties(
            should_parse=False,
            should_compile=False,
            intended_error_count=1,
        ),
        validation_status=ValidationStatus.MUTANT_VALIDATED,
        split_group_id="seed_001",
    )
    assert record.example_id == "mut_001"
    assert record.expected.intended_error_count == 1
    assert len(record.error.diagnostics) == 1


def test_synthetic_record_missing_mutated_code():
    with pytest.raises(ValidationError):
        DatasetRecord(
            example_id="mut_002",
            source_type=SourceType.SYNTHETIC,
            language=Language.C,
            source_code="int main() { return 0; }",
            original_example_id="seed_001",
            expected=ExpectedProperties(should_parse=False, should_compile=False),
            validation_status=ValidationStatus.MUTANT_VALIDATED,
            split_group_id="seed_001",
        )


def test_synthetic_record_missing_original_id():
    with pytest.raises(ValidationError):
        DatasetRecord(
            example_id="mut_003",
            source_type=SourceType.SYNTHETIC,
            language=Language.PYTHON,
            source_code="def foo(): pass",
            mutated_code="def foo() pass",
            expected=ExpectedProperties(should_parse=False, should_compile=False),
            validation_status=ValidationStatus.MUTANT_VALIDATED,
            split_group_id="seed_001",
        )


def test_invalid_language_fails():
    with pytest.raises(ValidationError):
        SeedExample(
            example_id="seed_invalid",
            language="unsupported_lang",  # type: ignore
            source_code="code",
            description="test",
        )


def test_empty_example_id_fails():
    with pytest.raises(ValidationError):
        DatasetRecord(
            example_id="   ",
            source_type=SourceType.SEED,
            language=Language.C,
            source_code="int main() { return 0; }",
            expected=ExpectedProperties(should_parse=True, should_compile=True),
            validation_status=ValidationStatus.VALID_BASELINE,
            split_group_id="seed_001",
        )


def test_optional_provenance_defaults():
    prov = ProvenanceMetadata()
    assert prov.repository is None
    assert prov.commit is None
    assert prov.license is None
