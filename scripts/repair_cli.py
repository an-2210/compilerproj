#!/usr/bin/env python
"""Unified Command-Line Interface for AI-Based Compiler Error Detection & Repair.

Supports:
- Repairing files or raw strings in Python, C, and C++
- Choosing backend: deterministic rules/mock, Ollama local LLM, or hosted APIs
- Printing 4-part beginner-friendly explanations (Error, Fix, Why, Corrected Code)
- Saving verified patches to disk
- Machine-readable JSON output for automated CI/CD integration

Usage Examples:
    # Repair a Python file using local rules / mock
    python scripts/repair_cli.py --file buggy.py

    # Repair using Ollama with deepseek-coder
    python scripts/repair_cli.py --file buggy.c --provider ollama --model deepseek-coder

    # Repair raw snippet directly
    python scripts/repair_cli.py --code "def f(x)\n  return x\n" --language python
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from src.systems.pipeline import run_pipeline


def detect_language_from_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python"
    elif ext in (".c", ".h"):
        return "c"
    elif ext in (".cpp", ".hpp", ".cc", ".cxx", ".java"):
        return "cpp"
    return "python"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI-Based Compiler Error Detection & Repair CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", type=Path, help="Path to source code file to repair")
    group.add_argument("--code", "-c", type=str, help="Raw source code string to repair")

    parser.add_argument(
        "--language", "-l",
        choices=["python", "c", "cpp"],
        help="Language of the code (auto-detected if --file is provided)",
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["mock", "ollama", "hosted", "openai"],
        default=os.environ.get("MODEL_PROVIDER", "mock"),
        help="Model provider backend (default: mock, or env MODEL_PROVIDER)",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Model name (e.g., deepseek-coder, llama3, gpt-4o-mini)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum candidate repair verification attempts (1-10)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Optional file path to write verified repaired code into",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output complete report in JSON format",
    )

    args = parser.parse_args()

    # Load code
    if args.file:
        if not args.file.exists():
            sys.stderr.write(f"Error: File not found: {args.file}\n")
            return 1
        try:
            code = args.file.read_text(encoding="utf-8")
        except Exception as e:
            sys.stderr.write(f"Error reading file {args.file}: {e}\n")
            return 1
        language = args.language or detect_language_from_path(args.file)
    else:
        code = args.code
        language = args.language or "python"

    # Run repair pipeline
    try:
        report = run_pipeline(
            code=code,
            language=language,
            max_attempts=args.max_attempts,
            provider=args.provider,
            model_name=args.model,
        )
    except Exception as exc:
        sys.stderr.write(f"Execution Error: {exc}\n")
        return 2

    # Handle JSON output
    if args.json:
        print(json.dumps(report.model_dump(), indent=2))
        return 0 if report.status in ("VERIFIED", "NOT_REPAIRED" and not report.detection.detected) else 1

    # Human-readable formatted output
    exp = report.explanation or {}
    print("=" * 60)
    print(" AI COMPILER ERROR DETECTION & REPAIR REPORT")
    print("=" * 60)
    print(f" Language:     {language.upper()}")
    print(f" Engine Used:  {report.model_used or args.provider}")
    print(f" Final Status: {report.status} ({report.reason})")
    print(f" Attempts:     {len(report.attempts)}")
    print("-" * 60)

    if exp.get("status") == "clean":
        print("\n[+] SUCCESS: No Errors Detected!")
        print(f"    {exp.get('error')}")
        print(f"    {exp.get('why')}\n")
    else:
        print(f"\n[-] ERROR (What & Where):")
        print(f"    {exp.get('error')}\n")

        print(f"[*] FIX (What Changed):")
        print(f"    {exp.get('fix')}\n")

        print(f"[?] WHY (Intuitive Rationale):")
        print(f"    {exp.get('why')}\n")

        print(f"[OK] CORRECTED CODE:")
        corrected = exp.get("corrected_code") or report.repaired_code or code
        for line in corrected.splitlines():
            print(f"    {line}")
        print()

    # Save output if requested
    if args.output and report.status == "VERIFIED" and report.repaired_code:
        try:
            args.output.write_text(report.repaired_code, encoding="utf-8")
            print(f"--> Repaired code written to: {args.output}")
        except Exception as e:
            sys.stderr.write(f"Warning: Could not write output file: {e}\n")

    print("=" * 60)
    return 0 if report.status == "VERIFIED" or not report.detection.detected else 1


if __name__ == "__main__":
    sys.exit(main())
