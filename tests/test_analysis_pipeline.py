"""Analysis Engineer: integration with the Data Engineer's dataset and the dev frontend API."""

import json
from pathlib import Path

import pytest

from src.analysis_engine import build_context, detect, rule_repair
from src.analysis_engine.contracts import ErrorContext, RepairResult
from dev_frontend.server import analyze, sample_list

ROOT = Path(__file__).resolve().parent.parent


def _records(split, limit=None):
    path = ROOT / "data" / "splits" / f"{split}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def test_every_real_bug_in_real_test_split_is_detected():
    for record in _records("real_test"):
        result = detect(record["mutated_code"], record["language"], layers="fast")
        assert result.detected, record["example_id"]


def test_pipeline_outputs_validate_against_contracts():
    record = _records("test", limit=1)[0]
    result = detect(record["mutated_code"], record["language"], layers="fast")
    ctx = build_context(record["mutated_code"], result.root, record["language"])
    repair = rule_repair(ctx)
    assert isinstance(ctx, ErrorContext)
    assert isinstance(repair, RepairResult)
    # Round-trip through JSON, which is how the ML and Systems engineers will consume it
    ErrorContext.model_validate_json(ctx.model_dump_json())
    RepairResult.model_validate_json(repair.model_dump_json())


def test_repair_recovers_exact_source_for_python_syntax_mutants():
    recovered = 0
    attempted = 0
    for record in _records("train") + _records("test"):
        if record["language"] != "python" or record["source_type"] == "seed":
            continue
        attempted += 1
        result = detect(record["mutated_code"], "python", layers="fast")
        if not result.detected:
            continue
        repair = rule_repair(build_context(record["mutated_code"], result.root, "python"))
        if repair.chosen and repair.chosen.code.strip() == record["source_code"].strip():
            recovered += 1
    assert attempted > 0
    # Regression floor, not a target: the rule baseline should recover a meaningful share
    assert recovered >= 1


def test_clean_seed_programs_are_not_flagged():
    seeds = [json.loads(line) for line in (ROOT / "data/seeds/seed_examples.jsonl").read_text().splitlines() if line.strip()]
    python_seeds = [s for s in seeds if s["language"] == "python"][:5]
    for seed in python_seeds:
        assert not detect(seed["source_code"], "python", layers="fast").detected, seed["example_id"]


# ---------------------------------------------------------------- Dev frontend API

def test_dev_frontend_analyze_returns_detection_context_and_repair():
    payload = analyze("def f(x)\n    return x\n", "python")
    assert payload["detection"]["detected"] is True
    assert payload["context"]["reported_line"] == 1
    assert payload["repair"]["chosen"]["compiles"] is True


def test_dev_frontend_clean_code_has_no_context_or_repair():
    payload = analyze("x = 1\n", "python")
    assert payload["detection"]["detected"] is False
    assert payload["context"] is None
    assert payload["repair"] is None


def test_dev_frontend_rejects_empty_and_oversized_input():
    with pytest.raises(ValueError):
        analyze("   ", "python")
    with pytest.raises(ValueError):
        analyze("x" * 20001, "python")


def test_dev_frontend_samples_come_from_dataset_splits():
    samples = sample_list()
    assert samples, "expected samples from data/splits"
    assert all(s["mutated_code"] and s["source_code"] for s in samples)
    assert all(s["split"] in {"train", "val", "test", "real_test", "unassigned"} for s in samples)
