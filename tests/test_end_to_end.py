"""End-to-end integration test exercising the complete Data Engineer workflow."""

import json
import pytest
from pathlib import Path

from src.data_engine.schemas import SeedExample, Language, DatasetRecord
from src.data_engine.mutation_registry import default_registry
from src.data_engine.diagnostic_collector import DiagnosticCollector
from src.data_engine.dataset_validator import DatasetValidator
from src.data_engine.dataset_builder import DatasetBuilder
from src.data_engine.dataset_splitter import DatasetSplitter
from src.data_engine.exporter import DatasetExporter
from src.data_engine.statistics import StatisticsGenerator


@pytest.mark.integration
def test_full_pipeline_end_to_end(tmp_path):
    # 1. Create a controlled seed program
    seed = SeedExample(
        example_id="seed_e2e_01",
        language=Language.PYTHON,
        source_code="def calculate_total(x, y):\n    return x + y\n\nres = calculate_total(10, 20)\n",
        description="End-to-end test seed program",
    )

    # 2. Build synthetic mutants using DatasetBuilder
    builder = DatasetBuilder(max_mutants_per_seed=2, random_seed=42)
    records = builder.build_from_seeds([seed])

    assert len(records) > 0, "Expected at least one valid mutant generated"
    mutant = records[0]

    # Verify mutant properties
    assert mutant.mutated_code != mutant.source_code
    assert mutant.error is not None
    assert len(mutant.error.diagnostics) >= 1
    assert mutant.validation_status.value == "MUTANT_VALIDATED"
    assert mutant.split_group_id == seed.example_id

    # 3. Export to JSONL
    dataset_file = tmp_path / "dataset.jsonl"
    exporter = DatasetExporter()
    exporter.export_jsonl(records, dataset_file)
    assert dataset_file.exists()

    # 4. Reload and validate schema
    reloaded = []
    with open(dataset_file, "r", encoding="utf-8") as f:
        for line in f:
            reloaded.append(DatasetRecord(**json.loads(line.strip())))
    assert len(reloaded) == len(records)

    # 5. Split and run leakage audit
    splitter = DatasetSplitter(train_ratio=0.5, val_ratio=0.25, test_ratio=0.25, random_seed=42)
    # Using multiple groups to test splitting
    multi_records = []
    for g_idx in range(4):
        s = SeedExample(
            example_id=f"seed_group_{g_idx}",
            language=Language.PYTHON,
            source_code=f"def fn_{g_idx}(val):\n    return val * {g_idx + 1}\n",
            description=f"Seed {g_idx}",
        )
        multi_records.extend(builder.build_from_seeds([s]))

    split_res = splitter.split(multi_records)
    assert split_res.audit_report["leakage_free"] is True
    assert len(split_res.audit_report["forbidden_intersections"]["train_val"]) == 0
    assert len(split_res.audit_report["forbidden_intersections"]["train_test"]) == 0

    # 6. Generate reports
    stats_gen = StatisticsGenerator()
    stats = stats_gen.compute_statistics(multi_records, split_audit=split_res.audit_report)
    json_path, md_path = stats_gen.write_reports(stats, output_dir=tmp_path / "reports")
    assert json_path.exists()
    assert md_path.exists()
