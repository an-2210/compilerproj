"""Tests for dataset export, JSONL formatting, and manifest generation."""

import json
import pytest
from pathlib import Path
from src.data_engine.exporter import DatasetExporter
from src.data_engine.schemas import (
    DatasetRecord,
    SourceType,
    Language,
    ValidationStatus,
    ExpectedProperties,
)


@pytest.fixture
def dummy_record():
    return DatasetRecord(
        example_id="exp_001",
        source_type=SourceType.SYNTHETIC,
        language=Language.PYTHON,
        source_code="x = 1\n",
        mutated_code="x = \n",
        original_example_id="seed_001",
        expected=ExpectedProperties(should_parse=False, should_compile=False),
        validation_status=ValidationStatus.MUTANT_VALIDATED,
        split_group_id="seed_001",
    )


def test_export_and_read_back(tmp_path, dummy_record):
    out_file = tmp_path / "test_out.jsonl"
    exporter = DatasetExporter()
    count = exporter.export_jsonl([dummy_record], out_file)
    assert count == 1
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        line = f.readline()
        loaded = DatasetRecord(**json.loads(line))
        assert loaded.example_id == dummy_record.example_id
        assert loaded.source_type == dummy_record.source_type


def test_overwrite_protection(tmp_path, dummy_record):
    out_file = tmp_path / "protected.jsonl"
    exporter_no_overwrite = DatasetExporter(overwrite=False)
    exporter_no_overwrite.export_jsonl([dummy_record], out_file)

    with pytest.raises(FileExistsError):
        exporter_no_overwrite.export_jsonl([dummy_record], out_file)


def test_manifest_creation(tmp_path, dummy_record):
    out_file = tmp_path / "data.jsonl"
    exporter = DatasetExporter()
    exporter.export_jsonl([dummy_record], out_file)

    manifest_file = tmp_path / "manifest.json"
    manifest = exporter.create_manifest({"data": out_file}, output_path=manifest_file)
    assert manifest["total_records"] == 1
    assert "data" in manifest["files"]
    assert len(manifest["files"]["data"]["sha256"]) == 64
