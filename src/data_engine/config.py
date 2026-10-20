"""Configuration loading and validation."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml
from pydantic import BaseModel, Field


class CompilerConfig(BaseModel):
    executable: str
    flags: List[str] = Field(default_factory=list)
    fallback_parser: Optional[str] = None


class CompilersSection(BaseModel):
    timeout_seconds: float = 5.0
    max_output_bytes: int = 65536
    c: CompilerConfig = Field(default_factory=lambda: CompilerConfig(executable="gcc", flags=["-fsyntax-only", "-Wall"]))
    cpp: CompilerConfig = Field(default_factory=lambda: CompilerConfig(executable="g++", flags=["-fsyntax-only", "-Wall"]))
    python: CompilerConfig = Field(default_factory=lambda: CompilerConfig(executable="python", flags=["-m", "py_compile"]))


class PathsSection(BaseModel):
    seeds_file: str = "data/seeds/seed_examples.jsonl"
    processed_dataset: str = "data/processed/dataset.jsonl"
    real_bugs_dir: str = "data/real_bugs"
    processed_real_bugs: str = "data/processed/real_bugs.jsonl"
    splits_dir: str = "data/splits"
    reports_dir: str = "reports"


class MutationSection(BaseModel):
    max_mutants_per_seed: int = 4
    random_seed: int = 42
    allow_cascading_diagnostics: bool = False
    operators: List[str] = Field(default_factory=list)


class SplittingSection(BaseModel):
    random_seed: int = 42
    train_ratio: float = 0.80
    val_ratio: float = 0.10
    test_ratio: float = 0.10
    group_by: str = "split_group_id"


class AppConfig(BaseModel):
    schema_version: str = "1.0"
    random_seed: int = 42
    paths: PathsSection = Field(default_factory=PathsSection)
    compilers: CompilersSection = Field(default_factory=CompilersSection)
    mutation: MutationSection = Field(default_factory=MutationSection)
    splitting: SplittingSection = Field(default_factory=SplittingSection)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML file or return default configuration."""
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            # Flatten top-level dataset key if present
            if "dataset" in data and isinstance(data["dataset"], dict):
                data.update(data.pop("dataset"))
            return AppConfig(**data)
    
    # Check default path
    default_path = Path("configs/dataset.yaml")
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if "dataset" in data and isinstance(data["dataset"], dict):
                data.update(data.pop("dataset"))
            return AppConfig(**data)

    return AppConfig()
