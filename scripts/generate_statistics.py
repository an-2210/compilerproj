#!/usr/bin/env python
"""Convenience script to generate statistics reports."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_engine.cli import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "stats", "--input-dir", "data/splits", "--output-dir", "reports"]
    sys.exit(main())
