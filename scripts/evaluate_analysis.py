"""Evaluate the Analysis Engineer layer against the Data Engineer's splits.

Metrics, per split and overall:
  detection       share of mutated programs where the detector reports an error
  category        root diagnostic category equals the record's intended category
  localization    the reported line and the top candidate line equal the true line
                  (gold = mutation target line, else the first line that differs
                  from source_code)
  false_positive  clean source_code programs flagged as erroneous
  repair          rule-based fix: chosen candidate compiles, equals source_code
                  (exact text, and ignoring whitespace), or any candidate does
                  (oracle@k over the reported candidates)

Usage:
  python scripts/evaluate_analysis.py [--splits val test real_test] [--limit N]
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis_engine import build_context, detect, rule_repair  # noqa: E402

SPLIT_FILES = {
    "train": "data/splits/train.jsonl",
    "val": "data/splits/val.jsonl",
    "test": "data/splits/test.jsonl",
    "real_test": "data/splits/real_test.jsonl",
}


def _ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


def gold_line(record: dict) -> Optional[int]:
    """1-indexed line of the mistake in mutated_code."""
    target = (record.get("mutation") or {}).get("target_location") or {}
    if target.get("line"):
        return target["line"]
    src = record["source_code"].split("\n")
    mut = record["mutated_code"].split("\n")
    for idx, (a, b) in enumerate(zip(src, mut)):
        if a != b:
            return idx + 1
    return None


def intended_category(record: dict) -> Optional[str]:
    expected = record.get("expected") or {}
    if expected.get("intended_category"):
        return expected["intended_category"]
    return (record.get("error") or {}).get("category")


def evaluate_record(record: dict) -> Dict:
    result = {"example_id": record["example_id"], "language": record["language"],
              "split": record.get("split"), "source_type": record["source_type"],
              "operator": (record.get("mutation") or {}).get("operator_id", "REAL")}

    detection = detect(record["mutated_code"], record["language"])
    result["detected"] = detection.detected
    result["layer"] = detection.layer
    if detection.root is None:
        return result

    gold = gold_line(record)
    ctx = build_context(record["mutated_code"], detection.root, record["language"])
    result["category_ok"] = detection.root.category == intended_category(record)
    result["gold_line"] = gold
    result["reported_line_exact"] = ctx.reported_line == gold
    result["mapped_line_exact"] = bool(ctx.candidate_lines) and ctx.candidate_lines[0] == gold
    result["mapped_line_within_1"] = bool(ctx.candidate_lines) and gold is not None and \
        abs(ctx.candidate_lines[0] - gold) <= 1
    result["mapped_line_in_top2"] = gold in ctx.candidate_lines[:2]

    repair = rule_repair(ctx)
    chosen = repair.chosen
    result["repair_applicable"] = repair.applicable
    result["repair_chosen_compiles"] = bool(chosen and chosen.compiles)
    result["repair_exact_text"] = bool(chosen and chosen.code == record["source_code"])
    result["repair_exact_ws"] = bool(chosen and _ws(chosen.code) == _ws(record["source_code"]))
    result["repair_oracle_ws"] = any(_ws(c.code) == _ws(record["source_code"])
                                     for c in repair.rule_candidates)
    result["repair_chosen_rule"] = chosen.rule_id if chosen else None
    return result


def _rate(rows: List[Dict], key: str) -> Optional[float]:
    values = [r[key] for r in rows if key in r and r[key] is not None]
    if not values:
        return None
    return round(100.0 * sum(bool(v) for v in values) / len(values), 1)


def summarize(rows: List[Dict], clean_flags: List[bool]) -> Dict:
    mutants = [r for r in rows if r["source_type"] != "seed"]
    located = [r for r in mutants if "mapped_line_exact" in r]
    repaired = [r for r in mutants if "repair_exact_ws" in r]
    return {
        "records": len(rows),
        "detection_recall_pct": _rate(rows, "detected"),
        "category_agreement_pct": _rate(located, "category_ok"),
        "localization_raw_reported_exact_pct": _rate(located, "reported_line_exact"),
        "localization_mapped_exact_pct": _rate(located, "mapped_line_exact"),
        "localization_mapped_within_1_pct": _rate(located, "mapped_line_within_1"),
        "localization_mapped_top2_pct": _rate(located, "mapped_line_in_top2"),
        "repair_applicable_pct": _rate(repaired, "repair_applicable"),
        "repair_chosen_compiles_pct": _rate(repaired, "repair_chosen_compiles"),
        "repair_fix_exact_text_pct": _rate(repaired, "repair_exact_text"),
        "repair_fix_exact_ws_pct": _rate(repaired, "repair_exact_ws"),
        "repair_oracle_at_k_ws_pct": _rate(repaired, "repair_oracle_ws"),
        "false_positive_pct_on_clean_sources": round(
            100.0 * sum(clean_flags) / len(clean_flags), 2) if clean_flags else None,
        "clean_sources_checked": len(clean_flags),
    }


METRIC_LABELS = [
    ("detection_recall_pct", "Detection recall (%)"),
    ("category_agreement_pct", "Category agreement (%)"),
    ("localization_raw_reported_exact_pct", "Localization, compiler line (%)"),
    ("localization_mapped_exact_pct", "Localization, mapped line (%)"),
    ("localization_mapped_within_1_pct", "Localization, mapped line within 1 (%)"),
    ("repair_applicable_pct", "Repair: a rule applies (%)"),
    ("repair_chosen_compiles_pct", "Repair: chosen fix compiles (%)"),
    ("repair_fix_exact_ws_pct", "Repair: fix equals source, ignoring whitespace (%)"),
    ("repair_fix_exact_text_pct", "Repair: fix equals source, exact text (%)"),
    ("repair_oracle_at_k_ws_pct", "Repair: correct fix among candidates (%)"),
    ("false_positive_pct_on_clean_sources", "False positives on clean sources (%)"),
]


def write_markdown(report: Dict, path: Path) -> None:
    lines = ["# Analysis layer evaluation", "",
             "Generated by `scripts/evaluate_analysis.py`. Rules were written while inspecting",
             "the train, val and test error messages, so these numbers are in-sample for the",
             "rule set. See docs/analysis_engineer.md for the limits.", "",
             "## Overall", "", "| Metric | Value |", "|---|---|"]
    for key, label in METRIC_LABELS:
        lines.append(f"| {label} | {report['overall'].get(key)} |")
    lines += ["", "## Per split", ""]
    splits = list(report["per_split"])
    lines.append("| Metric | " + " | ".join(splits) + " |")
    lines.append("|---|" + "---|" * len(splits))
    for key, label in METRIC_LABELS:
        values = " | ".join(str(report["per_split"][sp].get(key)) for sp in splits)
        lines.append(f"| {label} | {values} |")
    lines += ["", "## Per operator", "", "| Operator | Records | Category | Localization | Repair exact (ws) |",
              "|---|---|---|---|---|"]
    for op, summary in report["by_operator"].items():
        lines.append(f"| {op} | {summary['records']} | {summary['category_agreement_pct']} | "
                     f"{summary['localization_mapped_exact_pct']} | {summary['repair_fix_exact_ws_pct']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test", "real_test"])
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N records per split")
    parser.add_argument("--output", default="reports/analysis_eval.json")
    args = parser.parse_args()

    started = time.time()
    per_split: Dict[str, Dict] = {}
    all_rows: List[Dict] = []
    clean_seen = {}

    for split in args.splits:
        records = [json.loads(line) for line in (ROOT / SPLIT_FILES[split]).read_text(encoding="utf-8").splitlines() if line.strip()]
        if args.limit:
            records = records[: args.limit]
        rows = []
        for record in records:
            rows.append(evaluate_record(record))
            key = record["source_code"]
            if key not in clean_seen:
                clean_seen[key] = detect(key, record["language"]).detected
        per_split[split] = summarize(rows, [clean_seen[r["source_code"]] for r in records])
        all_rows.extend(rows)
        print(f"{split}: {len(rows)} records", flush=True)

    clean_flags = list(clean_seen.values())
    overall = summarize(all_rows, clean_flags)
    report = {
        "overall": overall,
        "per_split": per_split,
        "by_language": {
            lang: summarize([r for r in all_rows if r["language"] == lang],
                            [])
            for lang in sorted({r["language"] for r in all_rows})
        },
        "by_operator": {},
        "seconds": round(time.time() - started, 1),
        "records": all_rows,
    }

    per_op = defaultdict(list)
    for row in all_rows:
        per_op[row["operator"]].append(row)
    report["by_operator"] = {op: summarize(rows, []) for op, rows in sorted(per_op.items())}

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out_path.with_name("analysis_summary.md")
    write_markdown(report, md_path)
    print(json.dumps({"overall": overall, "seconds": report["seconds"]}, indent=2))
    print(f"wrote {out_path} and {md_path}")


if __name__ == "__main__":
    main()
