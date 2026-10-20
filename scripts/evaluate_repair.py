#!/usr/bin/env python
"""Evaluation script for the P3 ML Engineer repair layer.

Evaluates candidate repair generation on Data Engineer dataset splits.
Measures:
- Valid structured output rate
- Exact match against ground truth source_code (exact text and whitespace-insensitive)
- Top-1 and Top-k oracle accuracy
- Average edit distance and lines changed
- Category agreement with ground truth intended_category
- Compiler-verified clean compilation rate
- Inference latency per record

Writes results to reports/repair_eval.json and reports/repair_summary.md.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.analysis_engine import build_context, detect
from src.model.candidate_generator import analyze_and_repair, compute_edit_distance
from src.model.repair_model import MockModelProvider


def evaluate_split(
    split_name: str,
    records: List[Dict[str, Any]],
    k: int = 3,
    provider=None,
) -> Dict[str, Any]:
    """Evaluate repair generation on a collection of dataset records."""
    total_records = len(records)
    attempted = 0
    structured_valid = 0
    exact_matches = 0
    whitespace_matches = 0
    top_k_matches = 0
    category_matches = 0
    verified_clean = 0
    total_edit_distance = 0
    total_lines_changed = 0
    total_latency_ms = 0.0

    per_record_results = []

    for item in records:
        mutated_code = item.get("mutated_code", "")
        ground_truth = item.get("source_code", "")
        language = item.get("language", "python")
        intended_cat = item.get("expected", {}).get("intended_category") or item.get("error", {}).get("category")

        # Step 1: Detect error
        detection = detect(mutated_code, language)
        if not detection.detected or detection.root is None:
            # Code was not flagged as broken
            continue

        attempted += 1
        ctx = build_context(mutated_code, detection.root, language)

        start_time = time.perf_counter()
        try:
            candidates = analyze_and_repair(ctx, k=k, provider=provider)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            total_latency_ms += duration_ms

            if candidates:
                structured_valid += 1
                top_cand = candidates[0]

                # Exact matches
                is_exact = (top_cand.repaired_code == ground_truth)
                is_ws_match = (top_cand.repaired_code.strip() == ground_truth.strip())
                if is_exact:
                    exact_matches += 1
                if is_ws_match:
                    whitespace_matches += 1

                # Top-k oracle match
                oracle_match = any(c.repaired_code.strip() == ground_truth.strip() for c in candidates)
                if oracle_match:
                    top_k_matches += 1

                # Category agreement
                if intended_cat and top_cand.repair_category == intended_cat:
                    category_matches += 1

                # Edit metrics
                ed = compute_edit_distance(mutated_code, top_cand.repaired_code)
                total_edit_distance += ed
                total_lines_changed += top_cand.lines_changed

                # Verification check via compiler/analyzer
                cand_det = detect(top_cand.repaired_code, language)
                is_compiles = not cand_det.detected
                if is_compiles:
                    verified_clean += 1

                per_record_results.append({
                    "example_id": item.get("example_id"),
                    "language": language,
                    "attempted": True,
                    "structured_valid": True,
                    "is_exact_match": is_exact,
                    "is_ws_match": is_ws_match,
                    "oracle_match": oracle_match,
                    "verified_clean": is_compiles,
                    "edit_distance": ed,
                    "lines_changed": top_cand.lines_changed,
                    "latency_ms": round(duration_ms, 2),
                })
            else:
                per_record_results.append({
                    "example_id": item.get("example_id"),
                    "language": language,
                    "attempted": True,
                    "structured_valid": False,
                })
        except Exception as e:
            per_record_results.append({
                "example_id": item.get("example_id"),
                "language": language,
                "attempted": True,
                "error": str(e),
            })

    n = max(attempted, 1)
    n_valid = max(structured_valid, 1)

    summary = {
        "split": split_name,
        "total_records": total_records,
        "attempted_repairs": attempted,
        "structured_valid_pct": round(structured_valid / n * 100.0, 1),
        "exact_match_pct": round(exact_matches / n * 100.0, 1),
        "whitespace_match_pct": round(whitespace_matches / n * 100.0, 1),
        "top_k_oracle_pct": round(top_k_matches / n * 100.0, 1),
        "category_agreement_pct": round(category_matches / n * 100.0, 1),
        "verified_clean_compilation_pct": round(verified_clean / n * 100.0, 1),
        "avg_edit_distance": round(total_edit_distance / n_valid, 2),
        "avg_lines_changed": round(total_lines_changed / n_valid, 2),
        "avg_latency_ms": round(total_latency_ms / n, 2),
        "records": per_record_results,
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description="Evaluate P3 ML Repair Model on dataset splits.")
    parser.add_argument("--splits", nargs="+", default=["test", "real_test", "val"], help="Splits to evaluate.")
    parser.add_argument("--limit", type=int, default=None, help="Max records per split.")
    parser.add_argument("--k", type=int, default=3, help="Max candidates per repair query.")
    parser.add_argument("--output", default="reports/repair_eval.json", help="Output JSON path.")
    args = parser.parse_args()

    provider = MockModelProvider(mode="normal")
    all_summaries = {}

    for split in args.splits:
        split_path = ROOT / "data" / "splits" / f"{split}.jsonl"
        if not split_path.exists():
            print(f"Skipping missing split file: {split_path}")
            continue

        lines = split_path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(l) for l in lines if l.strip()]
        if args.limit:
            records = records[: args.limit]

        print(f"Evaluating {split} ({len(records)} records)...")
        summary = evaluate_split(split, records, k=args.k, provider=provider)
        all_summaries[split] = summary

    # Write output JSON
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_summaries, indent=2), encoding="utf-8")
    print(f"Wrote evaluation metrics to {out_path}")

    # Generate Markdown Summary
    md_lines = [
        "# P3 ML Repair Model Evaluation Summary",
        "",
        f"**Evaluated on:** {', '.join(args.splits)}  ",
        f"**Candidates (k):** {args.k}  ",
        f"**Backend:** {provider.get_model_name()}  ",
        "",
        "| Split | Records | Valid Output % | Exact Match % | WS-Insensitive Match % | Top-k Oracle % | Verified Clean % | Avg Latency (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for split, s in all_summaries.items():
        md_lines.append(
            f"| {split} | {s['attempted_repairs']}/{s['total_records']} | "
            f"{s['structured_valid_pct']}% | {s['exact_match_pct']}% | "
            f"{s['whitespace_match_pct']}% | {s['top_k_oracle_pct']}% | "
            f"{s['verified_clean_compilation_pct']}% | {s['avg_latency_ms']} ms |"
        )
    md_lines.append("")

    md_path = ROOT / "reports" / "repair_summary.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote markdown summary to {md_path}")


if __name__ == "__main__":
    main()
