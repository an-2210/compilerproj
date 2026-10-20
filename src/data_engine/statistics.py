"""Statistics Generator: computes reproducible metrics, distributions, and markdown reports."""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from src.data_engine.schemas import DatasetRecord, SourceType, ValidationStatus, SplitType

logger = logging.getLogger(__name__)


class StatisticsGenerator:
    """Generates detailed machine-readable JSON and human-readable Markdown reports from dataset records."""

    def __init__(self, metadata: Optional[Dict[str, Any]] = None):
        self.metadata = metadata or {}

    def compute_statistics(
        self,
        records: List[DatasetRecord],
        builder_stats: Optional[Dict[str, Any]] = None,
        split_audit: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute full statistical summary over actual records."""
        total_records = len(records)

        # Language distribution
        by_language = Counter(r.language.value for r in records)

        # Source type distribution
        by_source_type = Counter(r.source_type.value for r in records)

        # Validation status distribution
        by_validation_status = Counter(r.validation_status.value for r in records)

        # Split distribution
        by_split = Counter(r.split.value if r.split else "unassigned" for r in records)

        # Error category distribution
        by_category = Counter()
        by_subcategory = Counter()
        for r in records:
            cat = r.error.category if r.error else "none"
            subcat = r.error.subcategory if (r.error and r.error.subcategory) else "unknown"
            by_category[cat] += 1
            by_subcategory[f"{cat}::{subcat}"] += 1

        # Mutation operator distribution
        by_operator = Counter()
        for r in records:
            if r.mutation and r.mutation.operator_id:
                by_operator[r.mutation.operator_id] += 1

        # Diagnostic extraction stats
        diag_success_count = sum(1 for r in records if r.error and len(r.error.diagnostics) > 0)
        diag_success_rate = round(diag_success_count / total_records, 4) if total_records > 0 else 0.0

        # Compilers observed
        compilers_seen = Counter(r.error.compiler for r in records if r.error and r.error.compiler)

        stats = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": total_records,
            "distributions": {
                "by_language": dict(by_language),
                "by_source_type": dict(by_source_type),
                "by_validation_status": dict(by_validation_status),
                "by_split": dict(by_split),
                "by_category": dict(by_category),
                "by_subcategory": dict(by_subcategory),
                "by_operator": dict(by_operator),
                "by_compiler": dict(compilers_seen),
            },
            "diagnostics": {
                "records_with_extracted_diagnostics": diag_success_count,
                "diagnostic_extraction_success_rate": diag_success_rate,
            },
            "builder_metrics": builder_stats or {},
            "split_audit": split_audit or {},
            "metadata": self.metadata,
        }

        return stats

    def generate_markdown_summary(self, stats: Dict[str, Any]) -> str:
        """Render markdown summary report from statistics dictionary."""
        total = stats.get("total_records", 0)
        dist = stats.get("distributions", {})
        splits = dist.get("by_split", {})
        langs = dist.get("by_language", {})
        sources = dist.get("by_source_type", {})
        cats = dist.get("by_category", {})
        ops = dist.get("by_operator", {})
        diag_info = stats.get("diagnostics", {})
        split_audit = stats.get("split_audit", {})
        builder_metrics = stats.get("builder_metrics", {})

        md = []
        md.append("# Compiler Error Detection & Repair — Dataset Report\n")
        md.append(f"**Generated at:** {stats.get('generated_at', 'N/A')}\n")
        md.append(f"**Total Records:** `{total}`\n\n")

        # High-level overview
        md.append("## 1. High-Level Dataset Overview\n")
        md.append("| Metric | Value |\n")
        md.append("|---|---|\n")
        md.append(f"| Total Records | **{total}** |\n")
        md.append(f"| Synthetic Examples | {sources.get('synthetic', 0)} |\n")
        md.append(f"| Real-Bug Examples | {sources.get('real_bug', 0)} |\n")
        md.append(f"| Train Set Size | {splits.get('train', 0)} |\n")
        md.append(f"| Validation Set Size | {splits.get('val', 0)} |\n")
        md.append(f"| Test Set Size | {splits.get('test', 0)} |\n")
        md.append(f"| Real-Bug Test Set Size | {splits.get('real_test', 0)} |\n")
        md.append(f"| Diagnostic Extraction Rate | {diag_info.get('diagnostic_extraction_success_rate', 0):.2%} |\n")
        md.append(f"| Leakage-Free Audit | `{'PASSED' if split_audit.get('leakage_free', True) else 'FAILED'}` |\n\n")

        # Language distribution
        md.append("## 2. Language Distribution\n")
        md.append("| Language | Count | Percentage |\n")
        md.append("|---|---|---|\n")
        for lang, count in sorted(langs.items(), key=lambda x: -x[1]):
            pct = count / total if total else 0
            md.append(f"| `{lang}` | {count} | {pct:.1%} |\n")
        md.append("\n")

        # Category distribution
        md.append("## 3. Error Category Balance\n")
        md.append("| Error Category | Count | Percentage |\n")
        md.append("|---|---|---|\n")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            pct = count / total if total else 0
            md.append(f"| `{cat}` | {count} | {pct:.1%} |\n")
        md.append("\n")

        # Mutation operators
        if ops:
            md.append("## 4. Mutation Operator Counts\n")
            md.append("| Operator ID | Count |\n")
            md.append("|---|---|\n")
            for op, count in sorted(ops.items(), key=lambda x: -x[1]):
                md.append(f"| `{op}` | {count} |\n")
            md.append("\n")

        # Split Leakage Audit
        md.append("## 5. Leakage-Safe Split Audit\n")
        if split_audit:
            intersections = split_audit.get("forbidden_intersections", {})
            md.append("All split groups are isolated to prevent data leakage:\n\n")
            md.append("| Boundary Check | Forbidden Intersection Size | Status |\n")
            md.append("|---|---|---|\n")
            for pair, inter in intersections.items():
                status = "EMPTY (PASS)" if len(inter) == 0 else f"LEAKAGE ({len(inter)} groups)"
                md.append(f"| `{pair}` | `{len(inter)}` | **{status}** |\n")
        else:
            md.append("No split audit available.\n")
        md.append("\n")

        return "".join(md)

    def write_reports(
        self,
        stats: Dict[str, Any],
        output_dir: str | Path = "reports",
        json_filename: str = "dataset_statistics.json",
        md_filename: str = "dataset_summary.md",
    ) -> Tuple[Path, Path]:
        """Save JSON and Markdown reports to destination directory."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

        md_path = out_dir / md_filename
        md_content = self.generate_markdown_summary(stats)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return json_path, md_path
