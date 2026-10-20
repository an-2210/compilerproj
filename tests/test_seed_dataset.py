"""Tests for hand-written seed dataset validation, diversity, and uniqueness."""

import pytest
from pathlib import Path
from src.data_engine.seed_loader import SeedLoader
from src.data_engine.schemas import Language


@pytest.fixture
def seed_loader():
    return SeedLoader("data/seeds/seed_examples.jsonl")


def test_seed_dataset_size(seed_loader):
    seeds = seed_loader.load()
    assert len(seeds) >= 50, f"Expected at least 50 seed examples, got {len(seeds)}"


def test_seed_ids_are_unique(seed_loader):
    seeds = seed_loader.load()
    ids = [s.example_id for s in seeds]
    assert len(ids) == len(set(ids)), "Found duplicate seed example_id"


def test_seed_languages_represented(seed_loader):
    seeds = seed_loader.load()
    languages = {s.language for s in seeds}
    assert Language.C in languages
    assert Language.CPP in languages
    assert Language.PYTHON in languages


def test_seed_programs_are_unique(seed_loader):
    seeds = seed_loader.load()
    hashes = {"".join(s.source_code.split()) for s in seeds}
    assert len(hashes) == len(seeds), "Duplicate source programs found in seed set"


def test_seed_validation_report(seed_loader):
    seeds = seed_loader.load()
    report = seed_loader.validate(seeds)
    assert report.total_seeds >= 50
    assert report.valid_seeds == report.total_seeds, f"Rejections detected: {report.rejected_reasons}"
    assert report.rejected_seeds == 0
