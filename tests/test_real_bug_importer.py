"""Tests for modular real-bug importer and provenance preservation."""

import json
import pytest
from pathlib import Path
from src.data_engine.real_bug_importer import RealBugImporter
from src.data_engine.schemas import SourceType, ValidationStatus


@pytest.fixture
def importer():
    return RealBugImporter()


def test_import_sample_real_bugs(importer):
    fixture_path = "data/real_bugs/sample_real_bugs.jsonl"
    records = importer.import_from_file(fixture_path)
    assert len(records) > 0

    for r in records:
        assert r.source_type == SourceType.REAL_BUG
        assert r.provenance.repository is not None
        assert r.provenance.commit is not None
        assert r.provenance.file_path is not None
        assert r.provenance.license is not None
        assert r.validation_status == ValidationStatus.MUTANT_VALIDATED
        assert r.split_group_id.startswith("repo_") or r.split_group_id.startswith("real_group_")


def test_missing_provenance_raises(importer, tmp_path):
    invalid_entry = {
        "bug_id": "test_bug_01",
        "language": "python",
        "buggy_code": "x = 1\n",
        # missing fixed_code
    }
    tmp_file = tmp_path / "invalid.jsonl"
    tmp_file.write_text(json.dumps(invalid_entry) + "\n", encoding="utf-8")

    records = importer.import_from_file(tmp_file)
    assert len(records) == 0  # Safely skipped / warned without crashing pipeline
