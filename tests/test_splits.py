"""Tests for dataset splitting, group-level isolation, and leakage prevention."""

import pytest
from src.data_engine.dataset_splitter import DatasetSplitter, LeakageDetectedError
from src.data_engine.schemas import DatasetRecord, SourceType, Language, ValidationStatus, ExpectedProperties


def make_dummy_record(ex_id: str, group_id: str, source_type: SourceType = SourceType.SYNTHETIC) -> DatasetRecord:
    return DatasetRecord(
        example_id=ex_id,
        source_type=source_type,
        language=Language.PYTHON,
        source_code="x = 1\n",
        mutated_code="x = \n" if source_type == SourceType.SYNTHETIC else None,
        original_example_id="seed_orig",
        expected=ExpectedProperties(should_parse=False, should_compile=False),
        validation_status=ValidationStatus.MUTANT_VALIDATED,
        split_group_id=group_id,
    )


def test_leakage_safe_grouping():
    # 10 groups, 3 records per group
    records = []
    for g in range(10):
        gid = f"group_{g}"
        for r in range(3):
            records.append(make_dummy_record(f"mut_{g}_{r}", gid))

    splitter = DatasetSplitter(train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, random_seed=42)
    res = splitter.split(records)

    train_groups = {r.split_group_id for r in res.train}
    val_groups = {r.split_group_id for r in res.val}
    test_groups = {r.split_group_id for r in res.test}

    # Strict assertion: No group overlap
    assert len(train_groups & val_groups) == 0
    assert len(train_groups & test_groups) == 0
    assert len(val_groups & test_groups) == 0
    assert res.audit_report["leakage_free"] is True


def test_real_bugs_isolated_to_real_test():
    syn_recs = [make_dummy_record(f"syn_{i}", f"seed_{i}") for i in range(10)]
    real_recs = [make_dummy_record(f"real_{i}", f"repo_curl", SourceType.REAL_BUG) for i in range(2)]

    splitter = DatasetSplitter(train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, random_seed=42)
    res = splitter.split(syn_recs, real_recs)

    assert len(res.real_test) == 2
    for r in res.train:
        assert r.source_type == SourceType.SYNTHETIC
    for r in res.val:
        assert r.source_type == SourceType.SYNTHETIC
    for r in res.test:
        assert r.source_type == SourceType.SYNTHETIC
    for r in res.real_test:
        assert r.source_type == SourceType.REAL_BUG


def test_split_reproducibility():
    recs = [make_dummy_record(f"syn_{i}", f"seed_{i}") for i in range(20)]
    splitter1 = DatasetSplitter(random_seed=123)
    res1 = splitter1.split(recs)

    splitter2 = DatasetSplitter(random_seed=123)
    res2 = splitter2.split(recs)

    assert [r.example_id for r in res1.train] == [r.example_id for r in res2.train]
    assert [r.example_id for r in res1.val] == [r.example_id for r in res2.val]
    assert [r.example_id for r in res1.test] == [r.example_id for r in res2.test]
