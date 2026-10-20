"""Tests for mutant assessment, baseline validation, and quarantine rules."""

import pytest
from src.data_engine.dataset_validator import DatasetValidator
from src.data_engine.diagnostic_collector import DiagnosticCollector
from src.data_engine.schemas import SeedExample, Language, ValidationStatus
from src.data_engine.language_adapters import get_adapter


@pytest.fixture
def validator():
    return DatasetValidator(DiagnosticCollector())


def test_valid_baseline_detected(validator):
    seed = SeedExample(
        example_id="test_seed_1",
        language=Language.PYTHON,
        source_code="def foo():\n    return 10\n",
        description="test",
    )
    is_valid, err = validator.validate_baseline(seed)
    assert is_valid is True
    assert err is None


def test_invalid_baseline_detected(validator):
    bad_seed = SeedExample(
        example_id="bad_seed_1",
        language=Language.PYTHON,
        source_code="def foo()\n    return 10\n",
        description="bad seed",
    )
    is_valid, err = validator.validate_baseline(bad_seed)
    assert is_valid is False
    assert err is not None
    assert "Baseline failed to compile" in err


def test_mutant_assessment_valid_error(validator):
    adapter = get_adapter(Language.PYTHON)
    assessment, comp = validator.assess_mutant(
        baseline_code="x = 10\n",
        mutated_code="x = [1, 2\n",
        language_adapter=adapter,
        intended_category="delimiter_punctuation",
    )
    assert assessment.status == ValidationStatus.MUTANT_VALIDATED
    assert assessment.observed_error_count >= 1


def test_mutant_still_compiles_rejected(validator):
    adapter = get_adapter(Language.PYTHON)
    assessment, comp = validator.assess_mutant(
        baseline_code="x = 10\n",
        mutated_code="x = 20\n",  # Semantically different but syntactically valid
        language_adapter=adapter,
        intended_category="syntax",
    )
    assert assessment.status == ValidationStatus.MUTATION_REJECTED
    assert "still compiles cleanly" in assessment.reason
