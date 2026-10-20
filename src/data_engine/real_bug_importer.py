"""Modular real-world bug importer for benchmarks (BugsInPy, CodeNet, TSSB-3M, PyDriller).

Preserves full provenance and independently verifies compiler diagnostics for both buggy and fixed code.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.data_engine.schemas import (
    DatasetRecord,
    SourceType,
    Language,
    ValidationStatus,
    ExpectedProperties,
    ProvenanceMetadata,
    ErrorInfo,
)
from src.data_engine.diagnostic_collector import DiagnosticCollector, categorize_diagnostic_message

logger = logging.getLogger(__name__)


class RealBugImporter:
    """Imports, verifies, and standardizes real-world bug pairs."""

    def __init__(self, collector: Optional[DiagnosticCollector] = None):
        self.collector = collector or DiagnosticCollector()

    def import_from_file(self, file_path: str | Path) -> List[DatasetRecord]:
        """Import real-bug entries from JSONL file with compiler verification."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Real bug file not found: {path}")

        records: List[DatasetRecord] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    raw = json.loads(line)
                    rec = self._process_entry(raw, line_no)
                    if rec:
                        records.append(rec)
                except Exception as e:
                    logger.warning(f"Error processing real bug at line {line_no} in {path}: {e}")

        return records

    def import_from_directory(self, dir_path: str | Path) -> List[DatasetRecord]:
        """Scan directory and import all .jsonl real-bug fixtures."""
        path = Path(dir_path)
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        all_records: List[DatasetRecord] = []
        for file in path.glob("*.jsonl"):
            all_records.extend(self.import_from_file(file))
        return all_records

    def _process_entry(self, entry: Dict[str, Any], line_no: int) -> Optional[DatasetRecord]:
        """Validate provenance, run compiler on buggy & fixed versions, and produce DatasetRecord."""
        bug_id = entry.get("bug_id")
        if not bug_id:
            raise ValueError(f"Missing required 'bug_id' at line {line_no}")

        lang_str = entry.get("language", "").lower()
        if not lang_str:
            raise ValueError(f"Missing 'language' for bug {bug_id}")
        language = Language(lang_str)

        buggy_code = entry.get("buggy_code")
        fixed_code = entry.get("fixed_code")
        if not buggy_code or not fixed_code:
            raise ValueError(f"Bug {bug_id} must provide both 'buggy_code' and 'fixed_code'")

        # 1. Verify fixed version passes compilation
        adapter = self.collector.get_adapter_for(language)
        fixed_res = adapter.compile_or_parse(fixed_code)
        if not fixed_res.success:
            logger.warning(f"Fixed code for {bug_id} failed compilation: {fixed_res.stderr}")
            val_status = ValidationStatus.QUARANTINED
            quarantine_reason = "Fixed code failed baseline compilation"
        else:
            val_status = ValidationStatus.MUTANT_VALIDATED
            quarantine_reason = None

        # 2. Verify buggy version fails compilation
        buggy_res = adapter.compile_or_parse(buggy_code)
        if buggy_res.success:
            logger.warning(f"Buggy code for {bug_id} unexpectedly compiled cleanly")
            val_status = ValidationStatus.MUTATION_REJECTED
            quarantine_reason = "Buggy code does not fail compilation"

        # Determine error categorization from diagnostic
        diag_msg = buggy_res.diagnostics[0].message if buggy_res.diagnostics else (buggy_res.stderr or "")
        cat, subcat = categorize_diagnostic_message(diag_msg)
        if entry.get("category"):
            cat = entry["category"]
        if entry.get("subcategory"):
            subcat = entry["subcategory"]

        error_info = buggy_res.to_error_info(category=cat, subcategory=subcat)

        repo = entry.get("repository")
        # Generate stable group ID based on repository to prevent split leakage
        if repo:
            repo_slug = repo.rstrip("/").split("/")[-1]
            split_group_id = f"repo_{repo_slug}"
        else:
            split_group_id = f"real_group_{bug_id}"

        provenance = ProvenanceMetadata(
            repository=entry.get("repository"),
            commit=entry.get("commit"),
            file_path=entry.get("file_path"),
            license=entry.get("license"),
            source_url=entry.get("source_url") or entry.get("repository"),
            bug_id=bug_id,
            fixed_code=fixed_code,
            author=entry.get("author"),
        )

        ex_id = bug_id if bug_id.startswith("real_") else f"real_{bug_id}"
        orig_id = f"fixed_{bug_id.removeprefix('real_')}"

        record = DatasetRecord(
            schema_version="1.0",
            example_id=ex_id,
            source_type=SourceType.REAL_BUG,
            language=language,
            source_code=fixed_code,
            mutated_code=buggy_code,
            original_example_id=orig_id,
            error=error_info,
            expected=ExpectedProperties(
                should_parse=False,
                should_compile=False,
                intended_error_count=1,
                intended_category=cat,
                intended_subcategory=subcat,
            ),
            provenance=provenance,
            validation_status=val_status,
            quarantine_reason=quarantine_reason,
            split_group_id=split_group_id,
        )

        return record
