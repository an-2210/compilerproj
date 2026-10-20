# Dataset Schema and Contract Specification

**Version:** 1.0  
**Format:** JSON Lines (JSONL), UTF-8 encoded, exactly one JSON object per line.

---

## 1. Overview

This schema defines the interface contract for all synthetic and real-world compiler error examples. Downstream pipeline stages—**DETECT**, **EXPLAIN**, **REPAIR**, and **VERIFY**—consume this format directly.

---

## 2. Top-Level Record Definition

| Field Name | Type | Required | Description |
|---|---|:---:|---|
| `schema_version` | string | Yes | Fixed at `"1.0"`. |
| `example_id` | string | Yes | Stable, globally unique identifier (e.g. `mut_seed_c_001_C_MISSING_SEMICOLON_1` or `real_c_curl_001`). |
| `source_type` | string | Yes | Enum: `"synthetic"`, `"seed"`, or `"real_bug"`. |
| `language` | string | Yes | Enum: `"c"`, `"cpp"`, or `"python"`. |
| `source_code` | string | Yes | Ground-truth valid baseline source code. |
| `mutated_code` | string | Cond. | Mutated (buggy) source code containing the compiler error. Required for synthetic mutants and real-bug examples. |
| `original_example_id` | string | Cond. | For mutants, the parent baseline example ID. |
| `mutation` | object | No | Mutation metadata (for synthetic records). |
| `error` | object | Yes | Compiler and diagnostic ground-truth metadata. |
| `expected` | object | Yes | Verification expectations and intended counts. |
| `provenance` | object | Yes | Source repository, commit hash, file path, and licensing provenance. |
| `validation_status` | string | Yes | Enum: `VALID_BASELINE`, `MUTANT_VALIDATED`, `MUTATION_REJECTED`, `MUTANT_UNVERIFIED`, `COMPILER_UNAVAILABLE`, `QUARANTINED`. |
| `quarantine_reason` | string | No | Reason for quarantine if status is `QUARANTINED`. |
| `split_group_id` | string | Yes | Stable group ID ensuring baselines and their mutants are never separated across train/val/test. |
| `split` | string | No | Enum: `"train"`, `"val"`, `"test"`, `"real_test"`, or `null`. |

---

## 3. Sub-Object Schemas

### 3.1. `mutation` (MutationMetadata)

| Field Name | Type | Description |
|---|---|---|
| `operator_id` | string | Unique operator name (e.g. `C_MISSING_SEMICOLON`). |
| `operator_version` | string | Version string (e.g. `"1.0"`). |
| `target_location` | object | Optional `{"line": int, "column": int}` of the mutation. |
| `seed` | integer | Random seed used for reproducible mutation selection. |
| `description` | string | Human-readable explanation of the applied syntactic modification. |
| `original_token` | string | Text of the original token prior to mutation. |
| `mutated_token` | string | Text of the token or sequence replacing the original token. |

### 3.2. `error` (ErrorInfo)

| Field Name | Type | Description |
|---|---|---|
| `category` | string | Primary error taxonomy category (e.g. `delimiter_punctuation`, `syntax`, `expression_operator`). |
| `subcategory` | string | Fine-grained classification (e.g. `missing_semicolon`, `undeclared_identifier`). |
| `compiler` | string | Compiler or parser tool name (`gcc`, `g++`, `python_compiler`, `pycparser`). |
| `compiler_version` | string | Tool version string (e.g. `gcc 16.1.0`, `Python 3.13.3`). |
| `exit_code` | integer | Non-zero exit code emitted by the compiler tool. |
| `diagnostics` | array | List of extracted `DiagnosticMessage` items. |
| `raw_output` | string | Raw standard error or compiler stderr stream. |
| `execution_duration_ms` | float | Wall-clock execution time in milliseconds. |

### 3.3. `DiagnosticMessage`

| Field Name | Type | Description |
|---|---|---|
| `message` | string | Cleaned diagnostic text from compiler. |
| `file` | string | File name reported by compiler. |
| `line` | integer | 1-indexed source line number. |
| `column` | integer | 1-indexed source column number. |
| `severity` | string | `"error"`, `"warning"`, or `"note"`. |
| `raw_text` | string | Complete original diagnostic line. |

### 3.4. `expected` (ExpectedProperties)

| Field Name | Type | Description |
|---|---|---|
| `should_parse` | boolean | Expected parser outcome (`false` for syntax errors). |
| `should_compile` | boolean | Expected compiler outcome (`false` for compiler errors). |
| `intended_error_count` | integer | Number of intended root-cause errors (always `1` for synthetic mutants). |
| `intended_category` | string | Intended error taxonomy category. |
| `intended_subcategory` | string | Intended fine-grained subcategory. |

### 3.5. `provenance` (ProvenanceMetadata)

| Field Name | Type | Description |
|---|---|---|
| `repository` | string | Origin repository URL (e.g. `https://github.com/curl/curl`). |
| `commit` | string | Commit SHA where the bug or fix was isolated. |
| `file_path` | string | Path within the source tree. |
| `license` | string | Open-source license (e.g. `MIT`, `Apache-2.0`, `BSD-3-Clause`). |
| `source_url` | string | Web link to original bug report or commit. |
| `bug_id` | string | Unique bug identifier. |
| `fixed_code` | string | Fixed version of the program for evaluation. |
| `author` | string | Author or generator tag. |

---

## 4. Downstream Integration Guide

### For the Analysis Engineer (EXPLAIN)
- Consume `record["mutated_code"]` as the input program.
- Extract `record["error"]["diagnostics"]` for compiler hints (line, column, severity, message).
- Contrast against `record["source_code"]` for ground-truth root-cause explanation.

### For the Machine Learning Engineer (REPAIR)
- Load `train.jsonl` and `val.jsonl` for training and validation.
- Model input: `record["mutated_code"]` + `record["error"]["raw_output"]`.
- Model target: `record["source_code"]`.
- Evaluate on `test.jsonl` (synthetic test) and `real_test.jsonl` (real-world benchmarks).
- **Never train on `real_test.jsonl`**.
