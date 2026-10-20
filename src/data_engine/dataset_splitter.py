"""Leakage-safe dataset splitter enforcing group-level isolation across train/val/test/real_test."""

import json
import logging
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any

from src.data_engine.schemas import DatasetRecord, SplitType, SourceType

logger = logging.getLogger(__name__)


class LeakageDetectedError(Exception):
    """Raised when records sharing a split_group_id appear across multiple splits."""
    pass


@dataclass
class SplitResult:
    train: List[DatasetRecord]
    val: List[DatasetRecord]
    test: List[DatasetRecord]
    real_test: List[DatasetRecord]
    audit_report: Dict[str, Any]


class DatasetSplitter:
    """Partitions dataset records into train, val, test, and real_test without data leakage."""

    def __init__(
        self,
        train_ratio: float = 0.80,
        val_ratio: float = 0.10,
        test_ratio: float = 0.10,
        random_seed: int = 42,
    ):
        total = train_ratio + val_ratio + test_ratio
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"Split ratios must sum to 1.0, got {total}")
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        self.random_seed = random_seed

    def split(
        self,
        synthetic_records: List[DatasetRecord],
        real_records: Optional[List[DatasetRecord]] = None,
    ) -> SplitResult:
        """Partition synthetic records by split_group_id, isolating real_bug data into real_test."""
        real_records = real_records or []

        # 1. Real bugs go strictly to real_test
        real_test: List[DatasetRecord] = []
        for r in real_records:
            r.split = SplitType.REAL_TEST
            real_test.append(r)

        # 2. Group synthetic records by split_group_id
        groups: Dict[str, List[DatasetRecord]] = defaultdict(list)
        for r in synthetic_records:
            groups[r.split_group_id].append(r)

        group_ids = sorted(groups.keys())
        rng = random.Random(self.random_seed)
        rng.shuffle(group_ids)

        # Calculate target counts
        total_synthetic = len(synthetic_records)
        target_train = int(total_synthetic * self.train_ratio)
        target_val = int(total_synthetic * self.val_ratio)

        train: List[DatasetRecord] = []
        val: List[DatasetRecord] = []
        test: List[DatasetRecord] = []

        curr_train_count = 0
        curr_val_count = 0

        for gid in group_ids:
            group_recs = groups[gid]
            g_size = len(group_recs)

            if curr_train_count + g_size <= target_train or (curr_train_count == 0):
                for rec in group_recs:
                    rec.split = SplitType.TRAIN
                    train.append(rec)
                curr_train_count += g_size
            elif curr_val_count + g_size <= target_val or (curr_val_count == 0):
                for rec in group_recs:
                    rec.split = SplitType.VAL
                    val.append(rec)
                curr_val_count += g_size
            else:
                for rec in group_recs:
                    rec.split = SplitType.TEST
                    test.append(rec)

        # 3. Perform strict audit of forbidden group intersections
        audit = self.audit_splits(train, val, test, real_test)

        if not audit["leakage_free"]:
            raise LeakageDetectedError(f"Leakage detected between splits: {audit['forbidden_intersections']}")

        return SplitResult(
            train=train,
            val=val,
            test=test,
            real_test=real_test,
            audit_report=audit,
        )

    @staticmethod
    def audit_splits(
        train: List[DatasetRecord],
        val: List[DatasetRecord],
        test: List[DatasetRecord],
        real_test: List[DatasetRecord],
    ) -> Dict[str, Any]:
        """Audit split assignments to confirm zero overlap between split groups."""
        train_groups = {r.split_group_id for r in train}
        val_groups = {r.split_group_id for r in val}
        test_groups = {r.split_group_id for r in test}
        real_groups = {r.split_group_id for r in real_test}

        intersections = {
            "train_val": sorted(list(train_groups & val_groups)),
            "train_test": sorted(list(train_groups & test_groups)),
            "val_test": sorted(list(val_groups & test_groups)),
            "train_real": sorted(list(train_groups & real_groups)),
            "val_real": sorted(list(val_groups & real_groups)),
        }

        has_leakage = any(len(inter) > 0 for inter in intersections.values())

        total_syn = len(train) + len(val) + len(test)
        report = {
            "leakage_free": not has_leakage,
            "counts": {
                "train": len(train),
                "val": len(val),
                "test": len(test),
                "real_test": len(real_test),
                "total_synthetic": total_syn,
            },
            "groups_count": {
                "train_groups": len(train_groups),
                "val_groups": len(val_groups),
                "test_groups": len(test_groups),
                "real_groups": len(real_groups),
            },
            "proportions": {
                "train": round(len(train) / total_syn, 4) if total_syn else 0,
                "val": round(len(val) / total_syn, 4) if total_syn else 0,
                "test": round(len(test) / total_syn, 4) if total_syn else 0,
            },
            "forbidden_intersections": intersections,
        }
        return report
