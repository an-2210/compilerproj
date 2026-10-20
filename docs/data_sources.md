# Data Sources and Benchmark Provenance

This document outlines the data sources, ingestion criteria, licensing considerations, and provenance standards for the AI-Based Compiler Error Detection & Repair dataset.

---

## 1. Hand-Written Seed Dataset (`data/seeds/seed_examples.jsonl`)

The seed dataset contains **52 carefully hand-written, baseline programs** across three target languages:
- **C:** 20 programs covering basic arithmetic, recursive algorithms, pointers, arrays, structs, bitwise operations, linked lists, and sorting.
- **C++:** 15 programs covering classes, constructors, methods, templates, vectors, operator overloading, polymorphism, lambdas, and constexpr.
- **Python:** 17 programs covering list comprehensions, recursion, dictionaries, OOP, generators, decorators, exception handling, and algorithms.

### Seed Validation Principles
1. **100% Compiler Cleanliness:** Every seed baseline must compile/parse cleanly without errors before mutation.
2. **Minimal & Understandable:** Programs are small (< 40 lines), self-contained, and easy for human inspection and ML model reasoning.
3. **Diversity:** Exercises a wide range of language constructs to maximize applicability across all 15 mutation operators.
4. **Independent Provenance:** Entirely authored for this project under the MIT license, avoiding copyrighted external code.

---

## 2. Real-World Bug Sources

Real-world compiler bugs provide critical out-of-distribution evaluation data. They are ingested via modular adapters and isolated into `real_test.jsonl`.

### 2.1. Project CodeNet (IBM)
- **Format:** Source files accompanied by metadata CSV files containing submission IDs, problem IDs, languages, and judge verdicts.
- **Compiler Error Filtering:** Filter for submissions where `verdict == "Compile Error"`.
- **Pairing:** Matches the `Compile Error` submission with the same author's subsequent `Accepted` submission for the problem.

### 2.2. BugsInPy
- **Format:** Curated Git repositories and bug metadata files (`bug.info`).
- **Compiler Error Filtering:** Identifies commits addressing syntax errors, indentation errors, or unhandled token exceptions.
- **Provenance Preserved:** Repository URL, commit hash, file path, test suite outcome.

### 2.3. TSSB-3M (Time-Series Single-Statement Bugs)
- **Format:** Single-statement bug dataset mined across thousands of GitHub repositories.
- **Suitability:** High-precision single-line edits, ideal for isolating single-syntax-error repairs.

### 2.4. PyDriller History Mining
- **Methodology:** Traverses Git commit histories looking for commit messages with keywords like `fix syntax`, `missing semicolon`, `compiler error`.
- **Compiler Verification Gate:** PyDriller commits are **never assumed** to be compiler repairs. The buggy code is compiled, and only commits that fail with a real compiler error and pass on the fixed commit are retained.

---

## 3. Provenance and Licensing Standards

Every real-bug example includes complete metadata:
```json
{
  "repository": "https://github.com/curl/curl",
  "commit": "d986b2082b2fa2312b4e85741639d6ff56bcfa63",
  "file_path": "lib/vtls/openssl.c",
  "license": "curl",
  "source_url": "https://github.com/curl/curl",
  "bug_id": "real_c_curl_001"
}
```

### Strict Licensing Policy
- Only permissively licensed open-source code (MIT, Apache-2.0, BSD-2/3-Clause, Python-2.0, curl) is included in public benchmarks.
- No proprietary or unverified code is accepted into the evaluation suite.
