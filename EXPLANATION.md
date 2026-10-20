# Architecture and viva guide

## Problem and implemented solution

A suggested code repair can look plausible while leaving the original error or introducing another. This project joins genuine diagnostics with candidate generation and an independent acceptance gate. Its implemented flow is:

`source -> detect -> context -> rule/model proposals -> temporary candidate copy -> compile/diagnose -> compare -> bounded report`.

`src/data_engine` creates compiler-grounded fixtures and supplies C/C++ adapters. `src/analysis_engine/detect/detector.py` normalizes Python AST/pyflakes and C/C++ compiler errors. `src/analysis_engine/context/builder.py` gathers likely error context. `src/analysis_engine/rules/engine.py` proposes deterministic patches. `src/model/candidate_generator.py` can offer extra candidates through its default mock provider. `src/systems/pipeline.py:run_pipeline` deduplicates and selects within a fixed attempt budget. `src/systems/verification.py:verify_candidate` validates SHA-256 and edit limits, copies the proposal to a temporary directory, invokes a real static tool, compares diagnostics and returns a structured result. `dev_frontend/server.py` serves the API and original HTML page; `dev_frontend/index.html` displays each attempt and diff.

## Systems Engineer contribution

Detection finds a problem; verification checks a specific proposed replacement. A rule's `compiles` field and a model confidence value are hints, never acceptance. The verifier uses a separate Python process to compile Python without executing it; C/C++ checks use the existing syntax-only compiler adapter. It records whether the tool ran and its exit status. The source hash catches stale candidates, the changed-line limit filters broad rewrites, and `TemporaryDirectory` removes the working copy on normal, failure and timeout paths. Newly detected errors reject a candidate. Remaining old errors mean `NOT_REPAIRED`. Tool failure means `INCONCLUSIVE`.

The pipeline skips duplicate full-source candidates, caps attempts at 1–10, tries deterministic rule proposals first, then optional model proposals, and returns repaired code only after `VERIFIED`. The UI clears old results and the download control when the input changes, and discards a response if the input changed during verification. The current default model is a mock heuristic generator, not a trained online service. There is no execution of submitted source or runtime test suite. These checks establish static acceptability only. Python child processes have a timeout; no strict filesystem/network sandbox was verified for local compiler execution. Docker adds a non-root app user, read-only root, temporary filesystem, resource settings and a loopback host port, but the automation account could not access its daemon.

For the C unnamed-string-parameter case, the ranked root diagnostic alone is insufficient: GCC may first report a missing `bool` declaration while a later diagnostic reports the undeclared body identifier. The pipeline now passes all compiler diagnostics into the rule context. A narrowly scoped rule checks for the compiler's omitted-parameter diagnostic, a single unnamed `const char *` parameter, one unambiguous undeclared body identifier used at least twice, and no declaration for that identifier. It can include `stdbool.h` and `string.h` only when compiler diagnostics indicate those headers are needed. The mock provider limits colon/indentation edits to Python and leaves unsupported inputs unchanged rather than fabricating a patch. The independent verifier remains the sole acceptance gate.

## Live demonstration (3–5 minutes)

From the checkout, run `python dev_frontend/server.py`, open `http://127.0.0.1:8765/`, choose Python and paste:

```python
def add(a, b)
    return a + b
```

Choose **Analyze and verify**. Show the diagnostic on line 1, context, missing-colon proposal, unified diff, `verification_ran: true`, exit code 0, and `VERIFIED`. Download the repaired file only after checking the diff. Run `python -m pytest -q tests/test_systems.py` to show a rejected syntax regression, stale-hash rejection, bounded unrepairable input, timeout handling and the HTTP path. The health endpoint is `GET /health`.

## Presentation speech

“Our project starts with a common compiler-design problem: a diagnostic tells us where a program failed, but a proposed fix is not necessarily correct. We combine three existing layers—dataset engineering, error analysis, and candidate generation—with a Systems layer that makes the decision observable. The detector gets a real parser or compiler error. Context extraction gathers nearby lines and symbols. Local rules and an optional mock model propose repairs. My part validates every proposal against the original source hash and edit limits, writes it to a temporary copy, runs a real static check, and compares old and new diagnostics. A candidate is accepted only if the target and all detected errors are gone. If it introduces a new error, we reject it; if a tool fails, we call the result inconclusive. The pipeline has a strict attempt budget and keeps history, so it cannot claim success from a plausible-looking diff. The original UI now shows diagnostics, changes, verification and download only for a verified result. Our tests exercise the complete HTTP path as well as regressions and timeouts. The boundary is static correctness: we do not execute student programs or prove their output is right.”

## Viva questions and answers

1. **What is the input?** Source text and a supported language name.
2. **Which languages are supported?** Python, C and C++; tool availability differs by host.
3. **How is Python syntax detected?** Python's AST parser reports a `SyntaxError` with location.
4. **What does pyflakes add?** Selected undefined-name errors after syntax parsing succeeds.
5. **Is mypy required?** No. It is an optional full-detection layer; the repair path uses fast checks.
6. **How are C/C++ errors collected?** GCC/G++ syntax-only compiler adapters normalize diagnostics.
7. **What is root-cause context?** Nearby lines, ranked candidate lines, symbols, imports and structure hints.
8. **What makes a candidate?** A proposed complete source replacement plus explanation and provenance.
9. **Is confidence proof?** No. The independent verifier determines acceptance.
10. **Why hash the original?** To reject edits based on a different source revision.
11. **Why a temporary directory?** It prevents candidate evaluation from changing the submitted original.
12. **Is user code executed?** No. It is parsed or compiled statically.
13. **What does `VERIFIED` mean?** The configured static tool ran, the target resolved, and no detected errors remain.
14. **What does `REJECTED` mean?** Invalid input or a new error makes a candidate unacceptable.
15. **What does `NOT_REPAIRED` mean?** Existing errors remain or no candidate passed within the budget.
16. **What does `INCONCLUSIVE` mean?** Tool failure or timeout prevents a sound decision.
17. **How are regressions found?** Candidate error diagnostics are compared with baseline error identities.
18. **How are duplicate attempts avoided?** The pipeline hashes each proposed full source and skips repeats.
19. **Can retries loop forever?** No. `max_attempts` is bounded at 1–10.
20. **Is the default model an LLM?** No. It is a deterministic mock heuristic provider.
21. **Does `VERIFIED` guarantee correct output?** No. Runtime behavior and tests are outside the current gate.
22. **What does Docker protect?** It adds non-root operation, read-only root and resource settings; it is not a complete security guarantee.
23. **How do users see evidence?** The UI shows diff, tool execution, exit code, target resolution and attempt history.
24. **What would you improve next?** Stronger isolated workers, real provider integration, runtime tests, and better semantic diagnostic matching.

See `GUIDE.md`, `INSTRUCTION.md`, `docs/INTERFACES.md` and `docs/FINAL_VALIDATION_REPORT.md` for exact setup and validation status.
