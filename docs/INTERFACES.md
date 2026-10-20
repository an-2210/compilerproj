# Integration interfaces

The source of truth is the Pydantic models in `src/analysis_engine/contracts.py`, `src/model/schemas.py`, and `src/systems/verification.py`.

## Detection and context

`detect(code, language, layers="fast")` returns `DetectionResult`. Supported language names are `python`/`py`, `c`, and `cpp`/`c++`. A diagnostic has `message`, optional 1-based `line`/`column`, `severity`, `source` tool, optional `code`, taxonomy `category`/`subcategory`, and `raw` output. `root` is the ranked target; `cascades` are follow-on errors. Source with syntax errors does not require an AST to obtain a diagnostic.

`build_context(code, root, language)` returns `ErrorContext`, including reported and candidate lines, source neighborhood, symbols, imports, indentation and bracket hints. The complete source is in `context.code`; the API omits it from the context object because the caller already supplied it.

## Candidates

Rules return `RepairCandidate` with `rule_id`, `description`, `line`, `confidence`, full replacement `code`, and advisory `compiles`. The model layer returns `MLRepairCandidate` with `candidate_id`, `repaired_code`, category, root-cause explanation, target line, diff, provenance and edit metrics. The Systems layer treats both as untrusted proposals; neither `compiles` nor confidence grants acceptance. The model provider is a deterministic mock by default and is labeled as such.

## Verification

`verify_candidate(original, candidate, language, candidate_id=..., expected_hash=..., timeout_seconds=...)` checks source size, optional SHA-256 hash and changed-line budget, writes the candidate into a temporary directory, runs Python `compile()` in a separate interpreter or the C/C++ compiler adapter, reruns fast diagnostics, and returns `VerificationResult`.

| Status | Meaning |
| --- | --- |
| `VERIFIED` | Tool ran successfully; the original target and all detected errors are absent. |
| `REJECTED` | Candidate is invalid, stale, excessive, unchanged, or introduces a new error. |
| `NOT_REPAIRED` | Target or other existing errors remain. |
| `INCONCLUSIVE` | Tooling failed or timed out, so acceptance cannot be established. |

The result includes hashes, patch and tool execution flags, old/new diagnostics, target resolution, changed-line count, unified diff, exit code, bounded stdout/stderr and duration. Diagnostic comparison uses `(source, message, code)` independent of shifted line numbers. This is conservative and may reject a valid fix when a new error has the same text as an old one.

`run_pipeline(code, language, max_attempts=3)` returns `PipelineReport` with detection, context, rule proposal, attempt history, optional selected verification, and repaired code only when `status == VERIFIED`. Duplicate full-source candidates are skipped. Attempt count is bounded at 1–10. There is no execution of user source or test suite.

## HTTP

- `GET /health`: `{ "status": "ok" }`.
- `GET /`: existing HTML interface.
- `GET /api/samples`: curated dataset examples.
- `POST /api/analyze`: legacy detection/context/rule response.
- `POST /api/repair`: `{"code":"...","language":"python","max_attempts":3}`; returns `PipelineReport` JSON. Invalid input returns 400/413; unavailable analysis tooling returns 503.

Requests are capped at 80,000 body bytes and code at 100,000 UTF-8 bytes; the UI is intended for shorter inputs. There is no persistent result lookup or user authentication. Bind to loopback for local use.
