"""Dataset Builder: orchestrates seed baseline checking, mutation, compilation, and validation."""

import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from src.data_engine.schemas import (
    DatasetRecord,
    SeedExample,
    SourceType,
    ValidationStatus,
    ExpectedProperties,
    MutationMetadata,
    SourceLocation,
    ErrorInfo,
    ProvenanceMetadata,
)
from src.data_engine.seed_loader import SeedLoader
from src.data_engine.diagnostic_collector import DiagnosticCollector
from src.data_engine.dataset_validator import DatasetValidator
from src.data_engine.deduplicator import Deduplicator
from src.data_engine.mutation_registry import default_registry

logger = logging.getLogger(__name__)


@dataclass
class BuilderStats:
    total_seeds: int = 0
    valid_baselines: int = 0
    mutation_attempts: int = 0
    successful_mutations: int = 0
    rejected_mutations: int = 0
    quarantined_mutations: int = 0
    validated_mutants: int = 0
    duplicates_removed: int = 0


class DatasetBuilder:
    """Orchestrates generation of validated synthetic compiler error examples."""

    def __init__(
        self,
        max_mutants_per_seed: int = 4,
        random_seed: int = 42,
        allow_cascading: bool = False,
        collector: Optional[DiagnosticCollector] = None,
    ):
        self.max_mutants_per_seed = max_mutants_per_seed
        self.random_seed = random_seed
        self.allow_cascading = allow_cascading
        self.collector = collector or DiagnosticCollector()
        self.validator = DatasetValidator(self.collector)
        self.deduplicator = Deduplicator()
        self.stats = BuilderStats()

    def build_from_seeds(self, seeds: List[SeedExample]) -> List[DatasetRecord]:
        """Generate, validate, and deduplicate mutants from seed examples."""
        self.stats = BuilderStats(total_seeds=len(seeds))
        generated_records: List[DatasetRecord] = []
        rng = random.Random(self.random_seed)

        for seed_idx, seed in enumerate(seeds):
            # 1. Baseline verification
            is_valid, err_reason = self.validator.validate_baseline(seed)
            if not is_valid:
                logger.warning(f"Rejecting seed {seed.example_id}: {err_reason}")
                continue

            self.stats.valid_baselines += 1
            self.deduplicator.record_source(seed.example_id, seed.source_code)

            # 2. Select compatible mutation operators
            applicable_ops = default_registry.get_applicable(seed.source_code, seed.language)
            if not applicable_ops:
                continue

            # Deterministically shuffle operators per seed
            ops_to_try = list(applicable_ops)
            rng.shuffle(ops_to_try)

            mutants_created_for_seed = 0
            for op in ops_to_try:
                if mutants_created_for_seed >= self.max_mutants_per_seed:
                    break

                self.stats.mutation_attempts += 1
                op_seed = rng.randint(1000, 999999)
                mut_res = op.apply(seed.source_code, seed.language, seed=op_seed)

                if not mut_res.success or not mut_res.mutated_code:
                    self.stats.rejected_mutations += 1
                    continue

                self.stats.successful_mutations += 1

                # 3. Check duplicate mutant
                if self.deduplicator.is_mutant_duplicate(mut_res.mutated_code):
                    self.stats.duplicates_removed += 1
                    continue

                # 4. Compile and assess mutant
                adapter = self.collector.get_adapter_for(seed.language)
                assessment, comp_res = self.validator.assess_mutant(
                    baseline_code=seed.source_code,
                    mutated_code=mut_res.mutated_code,
                    language_adapter=adapter,
                    intended_category=mut_res.intended_category or "syntax",
                    intended_subcategory=mut_res.intended_subcategory,
                    allow_cascading=self.allow_cascading,
                )

                if assessment.status == ValidationStatus.MUTATION_REJECTED:
                    self.stats.rejected_mutations += 1
                    continue
                elif assessment.status == ValidationStatus.QUARANTINED:
                    self.stats.quarantined_mutations += 1
                elif assessment.status == ValidationStatus.MUTANT_VALIDATED:
                    self.stats.validated_mutants += 1

                # Record deduplicated mutant
                mutant_id = f"mut_{seed.example_id}_{op.operator_id}_{mutants_created_for_seed + 1}"
                self.deduplicator.record_mutant(mutant_id, mut_res.mutated_code)

                # 5. Build structured DatasetRecord
                error_info = comp_res.to_error_info(
                    category=mut_res.intended_category or "syntax",
                    subcategory=mut_res.intended_subcategory,
                )

                target_loc = None
                if mut_res.target_line is not None:
                    target_loc = SourceLocation(
                        line=mut_res.target_line,
                        column=mut_res.target_column,
                    )

                record = DatasetRecord(
                    schema_version="1.0",
                    example_id=mutant_id,
                    source_type=SourceType.SYNTHETIC,
                    language=seed.language,
                    source_code=seed.source_code,
                    mutated_code=mut_res.mutated_code,
                    original_example_id=seed.example_id,
                    mutation=MutationMetadata(
                        operator_id=op.operator_id,
                        operator_version=op.operator_version,
                        target_location=target_loc,
                        seed=op_seed,
                        description=mut_res.description,
                        original_token=mut_res.original_token,
                        mutated_token=mut_res.mutated_token,
                    ),
                    error=error_info,
                    expected=ExpectedProperties(
                        should_parse=False,
                        should_compile=False,
                        intended_error_count=1,
                        intended_category=mut_res.intended_category,
                        intended_subcategory=mut_res.intended_subcategory,
                    ),
                    provenance=ProvenanceMetadata(
                        repository="synthetic-mutation-engine",
                        author="data_engine",
                    ),
                    validation_status=assessment.status,
                    quarantine_reason=assessment.reason,
                    split_group_id=seed.example_id,  # Keeps mutants tied to the seed's split group
                )

                generated_records.append(record)
                mutants_created_for_seed += 1

        return generated_records
