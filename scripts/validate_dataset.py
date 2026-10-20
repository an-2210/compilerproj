#!/usr/bin/env python
"""Convenience script to validate dataset records."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_engine.cli import main

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/processed/dataset.jsonl"
    sys.argv = [sys.argv[0], "validate", "--input", target]
    sys.exit(main())
