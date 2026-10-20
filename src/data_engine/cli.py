"""Command-Line Interface (CLI) for the Compiler Error Detection & Repair Data Engine."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from src.data_engine.config import load_config, AppConfig
from src.data_engine.seed_loader import SeedLoader
from src.data_engine.dataset_builder import DatasetBuilder
from src.data_engine.dataset_validator import DatasetValidator
from src.data_engine.dataset_splitter import DatasetSplitter
from src.data_engine.real_bug_importer import RealBugImporter
from src.data_engine.statistics import StatisticsGenerator
from src.data_engine.exporter import DatasetExporter
from src.data_engine.schemas import DatasetRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_engine.cli")


def cmd_seeds(args: argparse.Namespace) -> int:
    """Handle seeds command: inspect or validate seed examples."""
    seeds_path = Path(args.seeds_file) if args.seeds_file else Path("data/seeds/seed_examples.jsonl")
    loader = SeedLoader(seeds_path)

    try:
        seeds = loader.load()
        logger.info(f"Loaded {len(seeds)} seed examples from {seeds_path}")
    except Exception as e:
        logger.error(f"Failed to load seeds: {e}")
        return 1

    if args.validate:
        logger.info("Validating baseline compilation for all seed examples...")
        report = loader.validate(seeds)
        print("\n=== Seed Validation Summary ===")
        print(f"Total seeds:     {report.total_seeds}")
        print(f"Valid seeds:     {report.valid_seeds}")
        print(f"Rejected seeds:  {report.rejected_seeds}")
        print(f"Unique programs: {len(report.unique_source_hashes)}")
        print(f"By language:     {report.counts_by_language}")
        print(f"Valid by lang:   {report.valid_by_language}")
        if report.rejected_reasons:
            print("\nRejection details:")
            for r in report.rejected_reasons:
                print(f" - {r['example_id']} ({r['language']}): {r['reason']}")
            return 1
        print("All seeds validated successfully (100% clean baselines)!\n")

    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Handle build command: mutate seeds, compile mutants, validate diagnostics, and export."""
    config = load_config(args.config)
    seed = args.seed if args.seed is not None else config.random_seed
    seeds_file = args.seeds_file or config.paths.seeds_file
    output_file = args.output or config.paths.processed_dataset

    logger.info(f"Building dataset with seed={seed}, config={args.config}")
    loader = SeedLoader(seeds_file)
    try:
        seeds = loader.load()
    except Exception as e:
        logger.error(f"Error loading seeds: {e}")
        return 1

    builder = DatasetBuilder(
        max_mutants_per_seed=config.mutation.max_mutants_per_seed,
        random_seed=seed,
        allow_cascading=config.mutation.allow_cascading_diagnostics,
    )

    records = builder.build_from_seeds(seeds)
    logger.info(
        f"Generated {len(records)} candidate records "
        f"({builder.stats.validated_mutants} validated, {builder.stats.quarantined_mutations} quarantined)"
    )

    exporter = DatasetExporter(overwrite=args.overwrite)
    try:
        written = exporter.export_jsonl(records, output_file)
        logger.info(f"Exported {written} records to {output_file}")
    except Exception as e:
        logger.error(f"Failed to export records: {e}")
        return 1

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Handle validate command: verify exported records against schema and invariants."""
    input_file = Path(args.input)
    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return 1

    validator = DatasetValidator()
    total = 0
    passed = 0
    failed = 0

    with open(input_file, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                data = json.loads(line)
                rec = DatasetRecord(**data)
                is_valid, errors = validator.validate_record(rec)
                if is_valid:
                    passed += 1
                else:
                    failed += 1
                    logger.warning(f"Record {rec.example_id} at line {line_no} failed validation: {errors}")
            except Exception as e:
                failed += 1
                logger.warning(f"Malformed record at line {line_no}: {e}")

    print("\n=== Dataset Validation Report ===")
    print(f"Total records inspected: {total}")
    print(f"Passed:                  {passed}")
    print(f"Failed:                  {failed}")

    return 0 if failed == 0 else 1


def cmd_split(args: argparse.Namespace) -> int:
    """Handle split command: partition dataset into train/val/test/real_test without leakage."""
    config = load_config(args.config)
    input_file = Path(args.input) if args.input else Path(config.paths.processed_dataset)
    splits_dir = Path(args.output_dir) if args.output_dir else Path(config.paths.splits_dir)
    real_bugs_file = Path(args.real_bugs) if args.real_bugs else Path(config.paths.processed_real_bugs)

    if not input_file.exists():
        logger.error(f"Input dataset file not found: {input_file}")
        return 1

    # Load synthetic records
    synthetic_records: List[DatasetRecord] = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                synthetic_records.append(DatasetRecord(**json.loads(line.strip())))

    # Load real bugs if available
    real_records: List[DatasetRecord] = []
    if real_bugs_file.exists():
        with open(real_bugs_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    real_records.append(DatasetRecord(**json.loads(line.strip())))
        logger.info(f"Loaded {len(real_records)} real bug records for real_test split")
    else:
        logger.info("No pre-processed real bugs file found; proceeding with synthetic records")

    splitter = DatasetSplitter(
        train_ratio=config.splitting.train_ratio,
        val_ratio=config.splitting.val_ratio,
        test_ratio=config.splitting.test_ratio,
        random_seed=config.splitting.random_seed,
    )

    try:
        split_res = splitter.split(synthetic_records, real_records)
    except Exception as e:
        logger.error(f"Splitting failed: {e}")
        return 1

    exporter = DatasetExporter(overwrite=True)
    splits_dir.mkdir(parents=True, exist_ok=True)

    exporter.export_jsonl(split_res.train, splits_dir / "train.jsonl")
    exporter.export_jsonl(split_res.val, splits_dir / "val.jsonl")
    exporter.export_jsonl(split_res.test, splits_dir / "test.jsonl")
    exporter.export_jsonl(split_res.real_test, splits_dir / "real_test.jsonl")

    # Write machine-readable split audit
    reports_dir = Path(config.paths.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    audit_file = reports_dir / "split_audit.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(split_res.audit_report, f, indent=2)

    logger.info(f"Splits generated successfully in {splits_dir}")
    print("\n=== Split Audit Report ===")
    print(f"Train records:     {len(split_res.train)}")
    print(f"Val records:       {len(split_res.val)}")
    print(f"Test records:      {len(split_res.test)}")
    print(f"Real test records: {len(split_res.real_test)}")
    print(f"Leakage free:      {split_res.audit_report['leakage_free']}")
    print(f"Audit saved to:    {audit_file}\n")

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Handle stats command: generate machine-readable JSON statistics and markdown report."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    all_records: List[DatasetRecord] = []
    if input_dir.is_dir():
        for jsonl_file in sorted(input_dir.glob("*.jsonl")):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        all_records.append(DatasetRecord(**json.loads(line.strip())))
    elif input_dir.is_file():
        with open(input_dir, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_records.append(DatasetRecord(**json.loads(line.strip())))

    if not all_records:
        logger.error(f"No records found in {input_dir}")
        return 1

    # Load audit report if present in output_dir
    audit_report = None
    audit_path = output_dir / "split_audit.json"
    if audit_path.exists():
        with open(audit_path, "r", encoding="utf-8") as f:
            audit_report = json.load(f)

    gen = StatisticsGenerator()
    stats = gen.compute_statistics(all_records, split_audit=audit_report)
    json_path, md_path = gen.write_reports(stats, output_dir=output_dir)

    logger.info(f"Statistics written to {json_path}")
    logger.info(f"Markdown summary written to {md_path}")
    print(f"\nReport summary saved to: {md_path}")
    return 0


def cmd_import_real(args: argparse.Namespace) -> int:
    """Handle import-real command: import and verify real bugs from benchmark fixtures."""
    input_dir = Path(args.input_dir)
    output_file = Path(args.output)

    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        return 1

    importer = RealBugImporter()
    logger.info(f"Importing and verifying real bugs from {input_dir}...")
    records = importer.import_from_directory(input_dir)

    exporter = DatasetExporter(overwrite=True)
    written = exporter.export_jsonl(records, output_file)
    logger.info(f"Successfully verified and exported {written} real bug records to {output_file}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="data-engine",
        description="Data Engineer pipeline for AI-Based Compiler Error Detection & Repair",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: seeds
    p_seeds = subparsers.add_parser("seeds", help="Inspect and validate seed examples")
    p_seeds.add_argument("--seeds-file", default="data/seeds/seed_examples.jsonl", help="Path to seed JSONL")
    p_seeds.add_argument("--validate", action="store_true", help="Compile and validate all seeds")

    # Subcommand: build
    p_build = subparsers.add_parser("build", help="Build synthetic dataset via mutation engine")
    p_build.add_argument("--config", default="configs/dataset.yaml", help="Path to YAML configuration")
    p_build.add_argument("--seed", type=int, default=None, help="Random seed override")
    p_build.add_argument("--seeds-file", default=None, help="Path to seed dataset")
    p_build.add_argument("--output", default="data/processed/dataset.jsonl", help="Output JSONL path")
    p_build.add_argument("--overwrite", action="store_true", default=True, help="Overwrite existing output")

    # Subcommand: validate
    p_val = subparsers.add_parser("validate", help="Validate dataset records against schema and invariants")
    p_val.add_argument("--input", required=True, help="Input JSONL file to validate")

    # Subcommand: split
    p_split = subparsers.add_parser("split", help="Generate train/val/test/real_test splits safely")
    p_split.add_argument("--input", default="data/processed/dataset.jsonl", help="Processed dataset path")
    p_split.add_argument("--config", default="configs/dataset.yaml", help="Configuration file path")
    p_split.add_argument("--output-dir", default="data/splits", help="Output directory for split JSONL files")
    p_split.add_argument("--real-bugs", default="data/processed/real_bugs.jsonl", help="Processed real bugs path")

    # Subcommand: stats
    p_stats = subparsers.add_parser("stats", help="Generate dataset statistics and markdown report")
    p_stats.add_argument("--input-dir", required=True, help="Directory containing split JSONL files or single JSONL")
    p_stats.add_argument("--output-dir", default="reports", help="Output directory for reports")

    # Subcommand: import-real
    p_real = subparsers.add_parser("import-real", help="Import and verify real-world bugs")
    p_real.add_argument("--input-dir", default="data/real_bugs", help="Directory containing real bug fixtures")
    p_real.add_argument("--output", default="data/processed/real_bugs.jsonl", help="Output processed JSONL file")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        return 0

    dispatch = {
        "seeds": cmd_seeds,
        "build": cmd_build,
        "validate": cmd_validate,
        "split": cmd_split,
        "stats": cmd_stats,
        "import-real": cmd_import_real,
    }

    handler = dispatch.get(args.subcommand)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
