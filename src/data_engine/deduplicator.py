"""Deduplication module: detects and eliminates duplicate source and mutant programs."""

import hashlib
from typing import Dict, List, Set, Tuple, Optional
from src.data_engine.schemas import DatasetRecord


def compute_code_hash(code: str) -> str:
    """Compute normalized SHA-256 hash of code ignoring whitespace differences."""
    # Normalize by stripping lines and ignoring empty lines
    normalized = "\n".join(line.strip() for line in code.splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class Deduplicator:
    """Manages deduplication across baselines and mutants."""

    def __init__(self):
        self._seen_source_hashes: Set[str] = set()
        self._seen_mutant_hashes: Set[str] = set()
        self._exact_id_to_hash: Dict[str, str] = {}
        self.duplicate_count: int = 0

    def is_source_duplicate(self, source_code: str) -> bool:
        h = compute_code_hash(source_code)
        return h in self._seen_source_hashes

    def record_source(self, example_id: str, source_code: str) -> bool:
        """Record a source program. Returns False if already seen (duplicate)."""
        h = compute_code_hash(source_code)
        if h in self._seen_source_hashes:
            self.duplicate_count += 1
            return False
        self._seen_source_hashes.add(h)
        self._exact_id_to_hash[example_id] = h
        return True

    def is_mutant_duplicate(self, mutated_code: str) -> bool:
        """Check if mutant code has already been generated."""
        h = compute_code_hash(mutated_code)
        return h in self._seen_mutant_hashes

    def record_mutant(self, example_id: str, mutated_code: str) -> bool:
        """Record a mutant program. Returns False if duplicate."""
        h = compute_code_hash(mutated_code)
        if h in self._seen_mutant_hashes:
            self.duplicate_count += 1
            return False
        self._seen_mutant_hashes.add(h)
        self._exact_id_to_hash[example_id] = h
        return True

    def filter_records(self, records: List[DatasetRecord]) -> Tuple[List[DatasetRecord], int]:
        """Filter a list of DatasetRecord, removing any duplicates."""
        unique_records: List[DatasetRecord] = []
        dup_count = 0
        local_seen: Set[str] = set()

        for rec in records:
            code_to_check = rec.mutated_code if rec.mutated_code else rec.source_code
            h = compute_code_hash(code_to_check)
            if h in local_seen:
                dup_count += 1
                continue
            local_seen.add(h)
            unique_records.append(rec)

        return unique_records, dup_count
