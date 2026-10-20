# Dataset Reproducibility & Integrity Guide

Reproducibility and leakage prevention are fundamental requirements for the Compiler Error Detection & Repair project.

---

## 1. Deterministic Seeding

All stochastic components throughout the data pipeline are governed by a configurable `random_seed` (default: `42`).

- **Operator Selection:** Shuffles candidate mutation operators deterministically per seed.
- **Location Selection:** Chooses candidate token locations using seeded PRNGs.
- **Split Partitioning:** Groups are shuffled using the configured random seed before partition assignment.

Re-running the pipeline with identical seed and configuration guarantees bit-for-bit identical JSONL datasets.

---

## 2. Leakage-Safe Splitting Architecture

### Grouping Invariant
Let $S = \{s_1, s_2, \dots, s_n\}$ be the set of seed programs. For each seed $s_i$, the mutation engine generates a set of mutants $M(s_i)$.
All records derived from $s_i$ are assigned:
$$\text{split\_group\_id}(r) = s_i \quad \forall r \in \{s_i\} \cup M(s_i)$$

Similarly, for real-world bug pairs, $\text{split\_group\_id}$ is assigned to the repository or bug pair.

### Split Assignment
Partitions are constructed by partitioning the disjoint set of groups $G$:
$$G = G_{\text{train}} \cup G_{\text{val}} \cup G_{\text{test}} \cup G_{\text{real\_test}}$$
$$\text{subject to } G_A \cap G_B = \emptyset \quad \forall A \neq B$$

### Automated Leakage Audit
Every run executes an automated audit verifying that all forbidden intersections are strictly empty:
```json
{
  "leakage_free": true,
  "forbidden_intersections": {
    "train_val": [],
    "train_test": [],
    "val_test": [],
    "train_real": [],
    "val_real": []
  }
}
```
If any group leaks across splits, `DatasetSplitter` raises `LeakageDetectedError` and aborts.

---

## 3. Dataset Integrity & Checksums

The pipeline generates `data/dataset_manifest.json` containing SHA-256 checksums, byte sizes, and record counts for all generated JSONL files:

```bash
python -c "
import json
with open('data/dataset_manifest.json') as f:
    print(json.dumps(json.load(f)['files'], indent=2))
"
```

---

## 4. Full Reproduction Pipeline

To reproduce the complete dataset from scratch:

```bash
# 1. Validate hand-written seeds
python -m src.data_engine.cli seeds --validate

# 2. Build synthetic mutants and capture compiler diagnostics
python -m src.data_engine.cli build --config configs/dataset.yaml --seed 42

# 3. Import and verify real-world bug benchmarks
python -m src.data_engine.cli import-real --input-dir data/real_bugs --output data/processed/real_bugs.jsonl

# 4. Generate leakage-safe splits
python -m src.data_engine.cli split --input data/processed/dataset.jsonl --config configs/dataset.yaml

# 5. Validate schema and invariants across all splits
python -m src.data_engine.cli validate --input data/processed/dataset.jsonl

# 6. Generate statistics and Markdown report
python -m src.data_engine.cli stats --input-dir data/splits --output-dir reports

# 7. Run automated test suite
python -m pytest tests
```
