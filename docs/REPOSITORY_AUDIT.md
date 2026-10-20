# Repository audit (baseline 2026-10-20)

## Baseline

- Checkout: `compilerproj`, branch `meheli-initial`, commit `f91955b6ce0fe9ceb860971d4bc361c2ad1491d5`; clean working tree. Work proceeds on `feature/systems-engineering`.
- `python -m pytest -q` with system Python 3.12.3: 114 collected, 97 passed, 17 failed (exit 1). All 17 trace to `ModuleNotFoundError: pyflakes`; the package is declared in both manifests but absent from that interpreter.
- Docker CLI 28.1.1 exists; daemon access is denied, so build/run validation is unavailable here.

## Architecture inventory

| Role | Implementation | Verified baseline | Gap |
| --- | --- | --- | --- |
| Data | `src/data_engine`, seed/split JSONL and scripts | Data tests passed | Dataset provenance and compiler availability vary by environment. |
| Analysis | `src/analysis_engine` detection, context and rules | Context tests passed; Python analysis blocked by missing dependency | Rule `compiles` flag alone is not an independent Systems acceptance check. |
| ML | `src/model`, mirrored top-level `model` facade | Candidate and model tests passed | Default provider is deterministic mock; broad exception suppression hides provider errors. |
| Systems/UI | `dev_frontend/server.py`, `index.html` | Existing analysis endpoint and page inspected | No isolated candidate verifier, attempt history, regression gate, or structured final result. |

## Defects and sequence

1. **High:** Verification is absent. Add immutable source hash, temporary copy, actual tool execution, diagnostic comparison, explicit status and cleanup.
2. **High:** API/UI present rule predictions as completed repairs without an independent verification result. Integrate the verifier and show status, diff and history.
3. **Medium:** Python analysis crashes when declared dependencies are not installed. Document and validate installation in an isolated environment; expose tool failure as inconclusive rather than success.
4. **Medium:** Model generation suppresses all errors. Preserve an explicit pipeline failure reason when model output or provider fails; use deterministic rule fallback.
5. **Medium:** No Docker files or runnable Systems documentation. Add minimal runtime configuration and record unverified Docker checks honestly.

## Security and limits

Detection and verification compile or statically analyze submitted code; they must never execute it. C/C++ preprocessing may access local headers and compiler processes have only the adapter timeout, with no verified network or filesystem isolation. The application should bind to loopback by default and cap input. Static validation cannot prove runtime behavior.
