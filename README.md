# AI-Based Compiler Error Detection & Repair

The integrated application, verification workflow, and demonstration are documented in [GUIDE.md](GUIDE.md), [INSTRUCTION.md](INSTRUCTION.md), and [EXPLANATION.md](EXPLANATION.md). Run `python dev_frontend/server.py` from this directory to open the existing UI at `http://127.0.0.1:8765/`. The remainder of this README describes the Data Engineer component.

A robust, reproducible, and compiler-grounded Data Engineering system designed for the **DETECT -> EXPLAIN -> REPAIR -> VERIFY** intelligent debugging pipeline.

---

## 1. Role and Purpose of the Data Engineer Module

The Data Engineer component is responsible for generating, validating, and curating high-quality, compiler-grounded datasets. It supplies structured training, validation, and evaluation records to downstream components:
- **Baseline Integrity:** Maintains a hand-written 52-example seed dataset across C, C++, and Python that passes compiler checks with 100% cleanliness.
- **Controlled Mutation Engine:** Implements 15 AST-aware and token-aware mutation operators, introducing exactly one intended root-cause error per mutant while protecting comments and string literals.
- **Compiler-Grounded Diagnostics:** Compiles every generated mutant and captures actual compiler diagnostics (GCC, G++, Python parser), recording exit codes, line numbers, column numbers, and raw stderr.
- **Leakage-Safe Splitting:** Partitions examples at the **split-group level** (`split_group_id`), ensuring that baseline programs and all their derived mutants are never split across training, validation, and test sets.
- **Real-Bug Evaluation Suite:** Imports, verifies, and isolates genuine open-source bugs into an independent `real_test.jsonl` benchmark.

---

## 2. Supporting the DETECT -> EXPLAIN -> REPAIR -> VERIFY Pipeline

```
  +--------------+       +--------------+       +--------------+       +--------------+
  |    DETECT    |  -->  |   EXPLAIN    |  -->  |    REPAIR    |  -->  |    VERIFY    |
  | (Diagnostics)|       | (Root Cause) |       | (ML Fixer)   |       | (Recompile)  |
  +--------------+       +--------------+       +--------------+       +--------------+
         ^                      ^                      ^                      ^
         |                      |                      |                      |
  +-----------------------------------------------------------------------------------+
  |                          DATA ENGINEER MODULE DELIVERABLES                        |
  |  - Raw compiler stderr      - Intended category    - (mutated -> fixed)   - Clean baseline|
  |  - Extracted line/col       - Subcategory & diff   - train/val/test splits- Verifier gate |
  +-----------------------------------------------------------------------------------+
```

1. **DETECT:** Supplies actual compiler diagnostics, exit codes, and locations (`line`, `column`, `message`).
2. **EXPLAIN:** Supplies ground truth `intended_category`, `intended_subcategory`, and before/after source diffs so the Analysis Engineer can train or evaluate root-cause explanation models.
3. **REPAIR:** Supplies clean, paired `(mutated_code, source_code)` examples in `train.jsonl` and `val.jsonl` for ML repair models.
4. **VERIFY:** Supplies baseline programs and compiler execution harnesses to recompile and verify candidate patches.

---

## 3. Installation and Setup

### Prerequisites
- **Python:** 3.10+ (Tested on Python 3.13.3)
- **C/C++ Compilers:** GCC and G++ (e.g. MSYS2 UCRT64 GCC 16.1.0 or MinGW/Linux GCC).
  - *Fallback:* If GCC is not installed, the C adapter gracefully uses `pycparser`.

### Quick Setup

```bash
# Clone the repository
git clone <repo-url>
cd compilerproj

# Install dependencies
pip install -r requirements.txt
```

---

## 4. Repository Structure

```
compilerproj/
|-- configs/
|   |-- dataset.yaml              # Global compiler, mutation, and split settings
|-- data/
|   |-- seeds/
|   |   |-- seed_examples.jsonl   # 52 hand-written, verified seed programs
|   |-- real_bugs/
|   |   |-- README.md             # Real-bug documentation and provenance rules
|   |   |-- sample_real_bugs.jsonl# Verified open-source bug benchmark
|   |-- processed/
|   |   |-- dataset.jsonl         # 208 validated synthetic mutants
|   |   |-- real_bugs.jsonl       # 8 verified real-bug pairs
|   |-- splits/
|   |   |-- train.jsonl           # Training partition (164 records)
|   |   |-- val.jsonl             # Validation partition (20 records)
|   |   |-- test.jsonl            # Synthetic test partition (24 records)
|   |   |-- real_test.jsonl       # Real-world evaluation benchmark (8 records)
|   |-- dataset_manifest.json     # Checksums, sizes, and record manifests
|-- docs/
|   |-- dataset_schema.md         # Schema and contract specification
|   |-- mutation_operators.md     # 15 mutation operators and verification rules
|   |-- data_sources.md           # Seed criteria and real-bug benchmark sources
|   |-- reproducibility.md        # Deterministic seeding and split audit
|-- reports/
|   |-- dataset_statistics.json   # Machine-readable metrics and distributions
|   |-- dataset_summary.md        # Markdown report with distribution tables
|   |-- split_audit.json          # Group leakage audit confirmation
|-- scripts/
|   |-- build_dataset.py          # Runner for dataset generation
|   |-- validate_dataset.py       # Runner for schema validation
|   |-- generate_statistics.py    # Runner for statistics calculation
|-- src/
|   |-- data_engine/
|       |-- __init__.py           # Package exports
|       |-- config.py             # YAML configuration loader
|       |-- schemas.py            # Strict Pydantic models
|       |-- seed_loader.py        # Seed dataset loader and validator
|       |-- language_adapters.py  # GCC, G++, and Python compiler invocation
|       |-- diagnostic_collector.py # Safe execution and diagnostic parser
|       |-- mutation_registry.py  # Operator registry and interfaces
|       |-- mutation_engine.py    # 15 mutation operators implementation
|       |-- dataset_validator.py  # Independent mutant assessment
|       |-- deduplicator.py       # Code hashing and deduplication
|       |-- dataset_splitter.py   # Leakage-safe group partitioning
|       |-- real_bug_importer.py  # Real-world benchmark ingestion
|       |-- statistics.py         # Metrics computation and reports
|       |-- exporter.py           # JSONL output and manifest writer
|       |-- dataset_builder.py    # Pipeline orchestrator
|       |-- cli.py                # Command-line interface
|-- tests/
|   |-- test_schemas.py
|   |-- test_seed_dataset.py
|   |-- test_mutation_engine.py
|   |-- test_diagnostics.py
|   |-- test_validation.py
|   |-- test_splits.py
|   |-- test_real_bug_importer.py
|   |-- test_exporter.py
|   |-- test_end_to_end.py
|-- pyproject.toml
|-- requirements.txt
|-- .gitignore
|-- README.md
```

---

## 5. Seed Dataset Format

The seed dataset (`data/seeds/seed_examples.jsonl`) contains **52 hand-written programs** (20 C, 15 C++, 17 Python). Each record is structured as:
```json
{
  "example_id": "seed_c_001",
  "language": "c",
  "description": "Compute the sum of two integers",
  "tags": ["arithmetic", "function", "basic"],
  "expected_to_compile": true,
  "source_code": "#include <stdio.h>\n\nint add(int a, int b) {\n    return a + b;\n}\n\nint main() {\n    int result = add(10, 20);\n    printf(\"Sum: %d\\n\", result);\n    return 0;\n}"
}
```

---

## 6. Dataset Record Schema

Every record in the generated JSONL files adheres strictly to the schema in [docs/dataset_schema.md](file:///docs/dataset_schema.md).

```json
{
  "schema_version": "1.0",
  "example_id": "mut_seed_c_001_C_MISSING_SEMICOLON_1",
  "source_type": "synthetic",
  "language": "c",
  "source_code": "int main() { return 0; }",
  "mutated_code": "int main() { return 0 }",
  "original_example_id": "seed_c_001",
  "mutation": {
    "operator_id": "C_MISSING_SEMICOLON",
    "operator_version": "1.0",
    "target_location": { "line": 1, "column": 23 },
    "seed": 42
  },
  "error": {
    "category": "delimiter_punctuation",
    "subcategory": "missing_semicolon",
    "compiler": "gcc",
    "compiler_version": "gcc 16.1.0",
    "exit_code": 1,
    "diagnostics": [
      {
        "message": "expected ';' before '}' token",
        "file": "input.c",
        "line": 1,
        "column": 23,
        "severity": "error"
      }
    ],
    "raw_output": "input.c:1:23: error: expected ';' before '}' token"
  },
  "expected": {
    "should_parse": false,
    "should_compile": false,
    "intended_error_count": 1
  },
  "validation_status": "MUTANT_VALIDATED",
  "split_group_id": "seed_c_001",
  "split": "train"
}
```

---

## 7. The 15 Mutation Operators

See [docs/mutation_operators.md](file:///docs/mutation_operators.md) for detailed descriptions.
1. `C_MISSING_SEMICOLON` (C, C++)
2. `C_EXTRA_SEMICOLON` (C, C++)
3. `UNMATCHED_OPENING_BRACKET` (C, C++, Python)
4. `UNMATCHED_CLOSING_BRACKET` (C, C++, Python)
5. `UNMATCHED_PARENTHESIS` (C, C++, Python)
6. `MISSING_CLOSING_BRACE` (C, C++)
7. `ARITHMETIC_OPERATOR_MUTATION` (C, C++, Python)
8. `COMPARISON_OPERATOR_MUTATION` (C, C++, Python)
9. `ASSIGNMENT_VS_EQUALITY_MUTATION` (C, C++, Python)
10. `MISSING_EXPRESSION_OPERAND` (C, C++, Python)
11. `MISSING_DELIMITER_COMMA` (C, C++, Python)
12. `IDENTIFIER_MISSPELLING` (C, C++, Python)
13. `EXTRA_FUNCTION_ARGUMENT` (C, C++, Python)
14. `MISSING_FUNCTION_ARGUMENT` (C, C++, Python)
15. `PYTHON_INDENTATION_ERROR` (Python)

---

## 8. Command-Line Interface (CLI) Guide

All stages can be executed independently or sequentially via `src.data_engine.cli`:

### Step 1: Validate Seed Baseline Programs
```bash
python -m src.data_engine.cli seeds --validate
```
*Validates that all 52 seed examples compile with 0 errors (100% clean).*

### Step 2: Build Synthetic Dataset
```bash
python -m src.data_engine.cli build --config configs/dataset.yaml --seed 42
```
*Applies mutations, invokes GCC/G++/Python, validates ground-truth diagnostics, deduplicates, and exports to `data/processed/dataset.jsonl`.*

### Step 3: Validate Records Against Schema
```bash
python -m src.data_engine.cli validate --input data/processed/dataset.jsonl
```
*Verifies schema conformance, invariants, and diagnostic presence.*

### Step 4: Import Real-World Bug Benchmarks
```bash
python -m src.data_engine.cli import-real --input-dir data/real_bugs --output data/processed/real_bugs.jsonl
```
*Ingests real-bug fixtures, verifies buggy code fails and fixed code compiles cleanly, preserving full provenance.*

### Step 5: Generate Leakage-Safe Splits
```bash
python -m src.data_engine.cli split --input data/processed/dataset.jsonl --config configs/dataset.yaml
```
*Partitions by `split_group_id` into `train.jsonl`, `val.jsonl`, `test.jsonl`, and `real_test.jsonl`. Writes `reports/split_audit.json`.*

### Step 6: Generate Dataset Statistics & Reports
```bash
python -m src.data_engine.cli stats --input-dir data/splits --output-dir reports
```
*Computes category balance, language distributions, and outputs `reports/dataset_statistics.json` and `reports/dataset_summary.md`.*

---

## 9. Running Automated Tests

Run the complete test suite with pytest:

```bash
python -m pytest tests
```

**Test Suite Coverage:**
- `test_schemas.py`: Schema validation, required fields, and constraints.
- `test_seed_dataset.py`: 52 seed uniqueness, variety, and clean compilation.
- `test_mutation_engine.py`: 15 operators, reproducibility, comment/string protection.
- `test_diagnostics.py`: Compiler execution, timeouts, and diagnostic extraction.
- `test_validation.py`: Baseline detection, mutant assessment, and rejection rules.
- `test_splits.py`: Group-based leakage prevention, real_test isolation, and split reproducibility.
- `test_real_bug_importer.py`: Real-bug ingestion and provenance verification.
- `test_exporter.py`: JSONL reading/writing, overwrite protection, manifest creation.
- `test_end_to_end.py`: Complete pipeline integration test.

---

## 10. Security & Execution Reliability

- **No Shell Execution:** All compiler and parser subprocesses are invoked strictly with argument lists (`subprocess.run(["gcc", ...])`), completely preventing shell injection.
- **Isolated Workspaces:** Compilation occurs in isolated temporary directories (`tempfile.TemporaryDirectory()`) that are cleaned up automatically.
- **Execution Limits:** Strict timeouts (default: 5.0 seconds) and stdout/stderr capture caps (64 KB) prevent infinite loops or denial-of-service from compiler bugs.
- **No Binary Execution:** Compilers are invoked with `-fsyntax-only` or syntax checking flags. Binaries are never executed.

---

## 11. Downstream Integration Guide

### Analysis Engineer (DETECT & EXPLAIN)
- **Input:** Read `mutated_code` and `error["diagnostics"]`.
- **Target:** Compare with `source_code` to evaluate root-cause explanation models.
- **Diagnostics Available:** Compiler tool name, version, exit code, line, column, severity, and raw message.

### ML Engineer (REPAIR)
- **Training:** Train models strictly on `train.jsonl` and evaluate checkpoints on `val.jsonl`.
- **Evaluation:** Benchmark models on `test.jsonl` (synthetic test set) and `real_test.jsonl` (real-world bug evaluation).
- **Prohibited:** Never train on `real_test.jsonl` or `test.jsonl`.

---

## 12. Analysis Engineer Layer (DETECT, CONTEXT, RULE REPAIR)

The `src/analysis_engine/` package reads the dataset records and provides `detect`, `build_context` and
`rule_repair`, plus the published contracts (`Diagnostic`, `DetectionResult`, `ErrorContext`,
`RepairCandidate`, `RepairResult`). Setup, the compiler note for macOS, evaluation, and the dev frontend
are in [docs/analysis_engineer.md](docs/analysis_engineer.md).

```bash
python scripts/evaluate_analysis.py     # writes reports/analysis_eval.json and reports/analysis_summary.md
python dev_frontend/server.py           # test page at http://127.0.0.1:8765
```

---

## 13. ML Engineer Layer & Ollama Local LLM Integration

The `src/model/` package defines the repair model generation interface (`ModelProvider`), supporting three provider backends:

- **Mock / Deterministic Rules (`MockModelProvider`):** Fast, reproducible, 100% offline baseline that requires zero external services or API keys.
- **Ollama Local LLM (`OllamaProvider`):** Direct integration with native [Ollama](https://ollama.com) (`/api/chat` and `/api/tags`). Prompts the local LLM using structured JSON schema format, fast socket-level availability checking (300ms non-blocking probe), and automatic error recovery.
- **Hosted API (`HostedAPIProvider`):** Integration with remote API endpoints (e.g. OpenAI / Anthropic-compatible endpoints) using environment variables.

### Running with Ollama

```bash
# 1. Start Ollama daemon
ollama serve

# 2. Pull your preferred code model
ollama pull deepseek-coder:1.3b
# or
ollama pull qwen2.5-coder:1.5b

# 3. Configure via .env (or environment variables)
# See .env.example for all configuration keys
MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-coder:1.3b
```

---

## 14. Unified Repair CLI

The project includes an end-to-end command-line repair tool (`scripts/repair_cli.py`) that coordinates Detection -> Explanation -> Candidate Generation -> Verification:

```bash
# Repair a broken source file
python scripts/repair_cli.py --file path/to/broken.py

# Repair code provided directly via command-line
python scripts/repair_cli.py --code "def add(a, b) return a + b" --language python

# Use a specific provider and model
python scripts/repair_cli.py --file main.c --provider ollama --model deepseek-coder:1.3b

# Save output or export structured JSON
python scripts/repair_cli.py --file broken.cpp --output fixed.cpp
python scripts/repair_cli.py --file broken.py --json
```

---

## 15. Web Interface & Document Import

Launch the interactive web UI and backend server:

```bash
python dev_frontend/server.py
```

Open <http://127.0.0.1:8765/> to access:
- **Code Input Options:** Paste code, select pre-set bug examples, or use the **Import File** button supporting `.c`, `.cpp`, `.java`, `.py`, and `.txt`.
- **AI Engine Switcher:** Real-time selector between Local Rules/Mock, Ollama Local LLM, and Hosted API.
- **Dynamic Model Discovery:** Automatically queries `GET /api/models` to display available Ollama models and connection health.
- **Multi-Stage Inspection Panels:** View detected compiler diagnostics, source context AST, generated repair candidates with unified diffs, and compiler verification proof.
- **Download Verified Patch:** Safe one-click download for verified source files.

