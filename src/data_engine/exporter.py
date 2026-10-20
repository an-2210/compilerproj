"""Dataset Exporter: validates and writes dataset records to versioned JSONL files and manifests."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from pydantic import ValidationError

from src.data_engine.schemas import DatasetRecord

logger = logging.getLogger(__name__)


def compute_file_sha256(file_path: Path) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class DatasetExporter:
    """Exports DatasetRecord collections to JSON Lines files with schema validation."""

    def __init__(self, overwrite: bool = True):
        self.overwrite = overwrite

    def export_jsonl(self, records: List[DatasetRecord], output_path: str | Path) -> int:
        """Write records to JSONL file. Validates each record against Pydantic schema."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        if out_file.exists() and not self.overwrite:
            raise FileExistsError(f"Target file already exists: {out_file}. Set overwrite=True to replace.")

        written_count = 0
        with open(out_file, "w", encoding="utf-8") as f:
            for rec in records:
                # Ensure record is valid Pydantic model
                if not isinstance(rec, DatasetRecord):
                    rec = DatasetRecord(**rec)
                json_str = rec.model_dump_json(exclude_none=False)
                f.write(json_str + "\n")
                written_count += 1

        return written_count

    def create_manifest(
        self,
        files: Dict[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        output_path: str | Path = "data/dataset_manifest.json",
    ) -> Dict[str, Any]:
        """Create a metadata manifest for exported dataset files."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        file_entries: Dict[str, Any] = {}
        total_records = 0

        for name, path in files.items():
            if path.exists():
                sha256 = compute_file_sha256(path)
                line_count = sum(1 for line in open(path, "r", encoding="utf-8") if line.strip())
                total_records += line_count
                file_entries[name] = {
                    "path": str(path),
                    "records": line_count,
                    "sha256": sha256,
                    "size_bytes": path.stat().st_size,
                }

        manifest = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": total_records,
            "files": file_entries,
            "metadata": metadata or {},
        }

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return manifest
