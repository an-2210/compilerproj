# Final validation report (2026-10-20)

## Repository and delivery

- Original `meheli-initial` preserved at `f91955b6ce0fe9ceb860971d4bc361c2ad1491d5`.
- Work branch: `feature/systems-engineering`; milestones `01904a6` (verification and UI pipeline) and `09da370` (setup, contracts, Docker and guides). Final test/report commit follows this record.
- No teammate files were removed. The only teammate source change makes absent optional mypy nonfatal and uses a portable temporary cache path.
- `GUIDE.md`, `INSTRUCTION.md`, `EXPLANATION.md`, repository audit, interface, team audit and Git workflow documentation exist.

## Executed checks

| Check | Result |
| --- | --- |
| Baseline `python -m pytest -q` (system Python, before changes) | Exit 1: 97 passed, 17 failed, all from absent pyflakes. |
| Focused Systems + analysis tests with pyflakes on `PYTHONPATH` | Exit 0: 32 passed. |
| Full suite after first implementation | Exit 0: 120 passed. |
| Full suite after HTTP/C tests | Exit 0: 122 passed. |
| Focused Systems tests after duplicate-selection test | Exit 0: 9 passed. |
| Real HTTP test | Health route, HTML page and `/api/repair` returned expected responses via `ThreadingHTTPServer` on loopback. |
| C compiler verification | Local C syntax repair returned `VERIFIED`, actual exit code 0. |
| `docker compose config` | Exit 0; service, loopback port, limits and health configuration parsed. |
| `docker compose build` | Exit 1: access denied to Docker config/buildx directory. Daemon access also denied by `docker info`. Image/startup/health inside Docker unverified. |
| `git fetch origin --dry-run` | Authentication failed: credential store unavailable and no interactive username prompt. Remote status/push/PR unverified. |

| Final full suite after duplicate-selection test | Exit 0: 123 passed in 47.34 seconds, no skips. |
| Final full suite after malformed-input guard | Exit 0: 124 passed in 41.07 seconds, no skips. |

The final test command used system Python 3.12.3 with `PYTHONPATH` pointing at the ignored `.venv/Lib/site-packages` directory containing pyflakes. The initial attempt to install requirements in the virtual environment did not finish in this session; a clean virtual-environment installation remains to be validated on a normal machine.

## Demonstrated scenarios

1. Missing Python colon: true diagnostic, candidate, temporary copy, independent compile, `VERIFIED` and diff.
2. New syntax error: `REJECTED`, original string unchanged.
3. Unrepairable undefined name: terminates within configured attempt count, no fabricated success.
4. Regressive and duplicate candidates followed by a valid candidate: duplicate skipped and valid candidate selected.
5. Simulated subprocess timeout: `INCONCLUSIVE`; temporary context exits.
6. Real HTTP application path: health, HTML and repair response checked by test.

## Security and acceptance limits

The application never executes submitted programs. Python uses a timed compile subprocess; C/C++ use syntax-only compiler adapters. Candidate files are temporary and removed. Local compiler processes are not verified as network-isolated or strictly confined to their temporary directory; Docker runtime protections were only statically checked. The default model is deterministic mock behavior. `VERIFIED` certifies configured static checks, not runtime outputs or semantic correctness. The remote feature branch must be published from a session with GitHub credentials; do not merge to a shared stable branch until checks and review are complete.
