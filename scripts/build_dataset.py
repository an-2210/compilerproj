#!/usr/bin/env python
"""Convenience script to run the dataset build pipeline."""

import sys
from pathlib import Path

# Ensure root directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_engine.cli import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "build", "--config", "configs/dataset.yaml", "--seed", "42"]
    sys.exit(main())
