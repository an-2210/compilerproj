"""Seed Dataset Manager: loads, validates, and reports on seed programs."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import ValidationError

from src.data_engine.schemas import SeedExample, Language
from src.data_engine.language_adapters import get_adapter

logger = logging.getLogger(__name__)


class SeedValidationReport:
    """Detailed summary of seed set validation."""

    def __init__(self):
        self.total_seeds: int = 0
        self.valid_seeds: int = 0
        self.rejected_seeds: int = 0
        self.counts_by_language: Dict[str, int] = {}
        self.valid_by_language: Dict[str, int] = {}
        self.rejected_reasons: List[Dict[str, str]] = []
        self.unique_source_hashes: Set[str] = set()

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_seeds": self.total_seeds,
            "valid_seeds": self.valid_seeds,
            "rejected_seeds": self.rejected_seeds,
            "unique_programs": len(self.unique_source_hashes),
            "counts_by_language": self.counts_by_language,
            "valid_by_language": self.valid_by_language,
            "rejections": self.rejected_reasons,
        }


class SeedLoader:
    """Loads and validates seed examples from JSONL."""

    def __init__(self, seeds_path: str | Path = "data/seeds/seed_examples.jsonl"):
        self.seeds_path = Path(seeds_path)

    def load(self) -> List[SeedExample]:
        """Load seed records from file with schema validation."""
        if not self.seeds_path.exists():
            raise FileNotFoundError(f"Seed file not found: {self.seeds_path}")

        seeds: List[SeedExample] = []
        seen_ids: Set[str] = set()

        with open(self.seeds_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    data = json.loads(line)
                    seed = SeedExample(**data)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Malformed JSON at line {line_no} in {self.seeds_path}: {e}")
                except ValidationError as e:
                    raise ValueError(f"Schema violation at line {line_no} in {self.seeds_path}: {e}")

                if seed.example_id in seen_ids:
                    raise ValueError(f"Duplicate seed ID detected at line {line_no}: {seed.example_id}")
                seen_ids.add(seed.example_id)
                seeds.append(seed)

        return seeds

    def validate(self, seeds: Optional[List[SeedExample]] = None) -> SeedValidationReport:
        """Validate that all baseline seed programs compile or parse cleanly."""
        if seeds is None:
            seeds = self.load()

        report = SeedValidationReport()
        report.total_seeds = len(seeds)

        for seed in seeds:
            lang_str = seed.language.value
            report.counts_by_language[lang_str] = report.counts_by_language.get(lang_str, 0) + 1

            # Check uniqueness of source
            src_normalized = "".join(seed.source_code.split())
            report.unique_source_hashes.add(src_normalized)

            try:
                adapter = get_adapter(seed.language)
                comp_res = adapter.compile_or_parse(seed.source_code)
                if comp_res.success:
                    report.valid_seeds += 1
                    report.valid_by_language[lang_str] = report.valid_by_language.get(lang_str, 0) + 1
                else:
                    report.rejected_seeds += 1
                    err_msg = (
                        comp_res.diagnostics[0].message
                        if comp_res.diagnostics
                        else (comp_res.stderr or "Compilation failed")
                    )
                    report.rejected_reasons.append(
                        {
                            "example_id": seed.example_id,
                            "language": lang_str,
                            "reason": f"Baseline compilation failed: {err_msg}",
                        }
                    )
            except Exception as e:
                report.rejected_seeds += 1
                report.rejected_reasons.append(
                    {
                        "example_id": seed.example_id,
                        "language": lang_str,
                        "reason": f"Adapter error: {e}",
                    }
                )

        return report
