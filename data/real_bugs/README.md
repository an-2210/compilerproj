# Real-World Bug Datasets & Benchmark Integrations

This directory houses real-world bug fixtures and ingestion documentation for the
Compiler Error Detection & Repair Data Engineering pipeline.

## Supported Real-Bug Sources

### 1. CodeNet (Project CodeNet - IBM)
- **Purpose**: Massive code corpus covering millions of coding problems in C, C++, and Python.
- **Compiler Error Suitability**: Contains explicit execution verdicts (`Compile Error`, `Accepted`).
- **Provenance**: Records Problem ID, Submission ID, Language, Compiler (`gcc`, `g++`, `python3`), License.
- **Pairing**: Links a `Compile Error` submission with the user's subsequent `Accepted` submission for the exact same problem.

### 2. BugsInPy
- **Purpose**: Curated benchmark of real bugs extracted from popular Python open-source repositories (e.g., pandas, tornado, scrapy).
- **Compiler Error Suitability**: Focuses on syntax, indentation, and AST-level parser failures before test execution.
- **Provenance**: Repository URL, Commit SHA, Bug ID, Modified File Path.

### 3. TSSB-3M (Time-Series Single-Statement Bugs)
- **Purpose**: Multi-million single-statement bugs across thousands of GitHub repositories.
- **Compiler Error Suitability**: Contains AST-level and syntactic bug commits isolated to a single line or statement.
- **Provenance**: Git commit SHA, parent commit SHA, repository URL, diff hunks.

### 4. PyDriller Git History Mining
- **Purpose**: Automated mining of Git repositories for bug-fix commits.
- **Quality Rule**: Commits are strictly verified against compilers. Only commits whose buggy version fails compilation/parsing AND whose fixed version passes compilation are accepted as verified compiler bugs.

---

## Local Benchmark Fixture: `sample_real_bugs.jsonl`

A verified collection of real open-source bugs from genuine public repositories (under permissive MIT/Apache-2.0 licenses) is provided in `sample_real_bugs.jsonl`. Each entry includes:
- `bug_id`: Stable unique identifier.
- `repository`: Canonical GitHub repository URL.
- `commit`: Genuine commit SHA fixing the compiler/syntax error.
- `file_path`: Relative repository path.
- `license`: Open-source license (MIT, Apache-2.0).
- `buggy_code`: Exact source exhibiting the compiler error.
- `fixed_code`: Fixed source verifying clean compilation.
- `language`: C, C++, or Python.
- `compiler_message`: Actual compiler diagnostic captured on the buggy code.
