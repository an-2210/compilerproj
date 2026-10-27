# User and demo guide

This project detects Python, C and C++ errors, proposes local rule or mock-model repairs, and independently checks proposed full-source replacements. A verified result means the configured static compiler/parser and fast diagnostic checks passed. It does not prove runtime behavior.

## Quick start

Use Python 3.10+ with `python -m venv .venv`, activate the environment, then run `python -m pip install -r requirements.txt` in the `compilerproj` checkout. Use that same interpreter for `python -m pytest -q` and startup; `python -m pip show pyflakes` confirms the required package is present in it. C and C++ require `gcc` and `g++` respectively for full compiler checks. The Python workflow uses AST, required `pyflakes`, and an independent Python compile subprocess. `mypy` is an optional full-detection layer; the repair pipeline uses fast detection.

Start the existing HTML UI and API together:

```powershell
python dev_frontend/server.py
```

Open <http://127.0.0.1:8765/>. Readiness is <http://127.0.0.1:8765/health>. The UI accepts pasted code or a dataset sample, shows diagnostic location and context, rule candidate explanations, verification status, unified diffs, and attempt history. It offers a download only when a candidate is `VERIFIED` for the current code and language. Editing the input clears the prior result and requires another verification.

For an API demo, send a JSON body to `POST http://127.0.0.1:8765/api/repair`:

```powershell
$body = @{language='python'; code="def add(a, b)`n    return a + b`n"} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/repair -Method Post -ContentType application/json -Body $body
```

The exact output includes `detection`, `context`, `repair`, `attempts`, `selected`, `status`, `reason`, and `repaired_code`. For the example, the rule engine proposes a colon, the verifier writes that candidate to a temporary `.py` file, runs a separate Python compile command, and reports `VERIFIED` when no detected errors remain.

## Document Import and AI Engine Selection

The web interface (<http://127.0.0.1:8765/>) supports:
1. **Document Import**: Click **Import File** to load `.c`, `.cpp`, `.java`, `.py`, or `.txt` files directly into the editor.
2. **AI Engine Selector**: Choose between:
   - `⚡ Local Rules / Mock`: Deterministic local rules and fast offline baseline.
   - `🦙 Ollama Local LLM`: Connects to a locally running Ollama instance (e.g. `deepseek-coder`, `llama3`, `codellama`, `qwen2.5-coder`).
   - `☁️ Hosted API`: Uses external LLM providers configured via API keys.
3. **Model Detection**: When Ollama is running (`ollama serve`), the UI dynamically populates available downloaded models and displays a live connection status badge (`● Ollama Ready`).

## Unified Repair CLI (`scripts/repair_cli.py`)

A full-featured command-line interface provides the complete Detect -> Explain -> Repair -> Verify pipeline:

```bash
# Repair a file directly
python scripts/repair_cli.py --file path/to/broken.py

# Repair code passed as a string
python scripts/repair_cli.py --code "def add(a, b) return a + b" --language python

# Specify engine and model (e.g., local Ollama)
python scripts/repair_cli.py --file main.c --provider ollama --model deepseek-coder:1.3b

# Save verified code to file or output JSON
python scripts/repair_cli.py --file broken.py --output fixed.py
python scripts/repair_cli.py --file broken.py --json
```

Output includes 4 clear sections:
- `[-] ERROR`: File, line, column, and raw compiler diagnostic.
- `[*] FIX`: Concise explanation of the applied fix.
- `[?] WHY`: Root cause rationale and underlying language rule.
- `[OK] CORRECTED CODE`: Syntax-highlighted verified replacement or diff.

## Local Ollama Setup

To use Ollama for local LLM-powered repairs:

1. **Install and Start Ollama**:
   ```bash
   # Download from https://ollama.com
   ollama serve
   ```
2. **Pull a Code Model**:
   ```bash
   ollama pull deepseek-coder:1.3b
   # or
   ollama pull qwen2.5-coder:1.5b
   ```
3. **Configure Environment (Optional)**:
   Copy `.env.example` to `.env` or set environment variables:
   ```bash
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=deepseek-coder:1.3b
   MODEL_PROVIDER=ollama
   ```
4. If Ollama is offline or not installed, the system automatically falls back to deterministic rule-based repair with zero runtime errors.

## Docker Deployment

To launch with Docker Compose:

```bash
docker compose up --build
```
`compose.yaml` maps `host.docker.internal:host-gateway` and configures `OLLAMA_BASE_URL: "http://host.docker.internal:11434"` so containerized services can access Ollama running on your host machine.

## Result meanings

| Status | Action |
| --- | --- |
| `VERIFIED` | Review the diff and download the result if desired. |
| `REJECTED` | An individual candidate is stale, invalid, excessive, or regressive. |
| `NOT_REPAIRED` | The attempt budget was exhausted or existing errors remain. |
| `INCONCLUSIVE` | A tool failure or timeout prevented a trustworthy decision. |

The outer pipeline may say `NOT_REPAIRED` while a particular attempt says `REJECTED`. Only the outer `VERIFIED` status includes downloadable repaired source. Compare the changed lines and explanation before using it.

For a C function defined with a single unnamed `const char *` parameter, the rule engine can infer its name only when compiler diagnostics identify one undeclared body identifier and the body uses that identifier repeatedly. For example, `bool is_palindrome(const char *)` with repeated `s` references is repaired to `bool is_palindrome(const char *s)`; if the compiler also reports missing declarations for `bool` and `strlen`, the candidate adds their standard headers. Ambiguous or weak evidence produces no parameter-name rule. Every candidate still needs independent compiler verification before download.

## Tests and repository map

Run `python -m pytest -q`. `src/data_engine` owns fixtures and compiler adapters, `src/analysis_engine` owns detection and rules, `src/model` owns candidate generation (including `OllamaProvider`), `src/systems` owns verification and selection, and `dev_frontend` owns the API and UI. `tests/test_systems.py` and `tests/test_ollama.py` cover the real static path, HTTP routes, and provider integration. Related details are in `docs/INTERFACES.md`, `docs/REPOSITORY_AUDIT.md`, `INSTRUCTION.md` and `EXPLANATION.md`.

## Troubleshooting and limits

Install dependencies into the active interpreter if `pyflakes` is missing. Ensure `gcc`/`g++` are in `PATH` for C/C++. If 8765 is occupied, set `APP_PORT` before starting. A 503 means required analysis tooling is unavailable. Candidate generation defaults to a deterministic mock model and local rules; it requires no API key. Unsupported repairs can correctly end as `NOT_REPAIRED`. The system compiles or parses source but never runs the submitted program. Compiler preprocessing is not a strong sandbox; use trusted local input or add an isolated worker before exposing this service publicly.

