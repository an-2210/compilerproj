# Environment and Docker setup

## Local setup

Use the `compilerproj` directory (it contains `pyproject.toml`). Python 3.10+ and Git are required. For C/C++ support, install GCC/G++ and confirm `gcc --version` and `g++ --version`. On Windows, MSYS2 UCRT64 is one option. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python dev_frontend/server.py
```

Open <http://127.0.0.1:8765/> and check <http://127.0.0.1:8765/health>. If activation is blocked by local policy, run `.\.venv\Scripts\python.exe` directly for install, tests and startup. On Unix, use `source .venv/bin/activate`. The service defaults to `APP_HOST=127.0.0.1` and `APP_PORT=8765`; set environment variables to override. `.env.example` documents them, but the server reads environment variables directly and does not load `.env` automatically. No AI key is required for the deterministic default provider.

## Docker

Docker Desktop with its Linux engine is needed on Windows; WSL 2 is commonly used as the backend. From `compilerproj`:

```powershell
docker compose config
docker compose build
docker compose up -d
docker compose ps
Invoke-WebRequest http://127.0.0.1:8765/health
docker compose logs --tail=100
docker compose down
```

The single `app` service exposes port 8765 on host loopback. It installs Python requirements and GCC/G++, runs as UID 10001, uses a read-only root filesystem and 64 MiB temporary filesystem, and has a health check. Compose config also applies 512 MiB memory and one CPU. The application runs `python dev_frontend/server.py`. To run tests in a one-off container, use `docker compose run --rm app python -m pytest -q`; test networking and compiler resource constraints depend on the Docker host.

Docker client 28.1.1 was present during development, but this session lacked permission to access its daemon. Image build, container startup and Compose health checks were therefore not executed here; run the commands above on a machine with Docker daemon access.

## Demo

Paste `def add(a, b)` followed by an indented `return a + b` into the UI, select Python, and choose **Analyze and verify**. Expect a missing-colon diagnostic, a candidate diff adding `:`, a real tool execution result, and `VERIFIED`. The API example is in `GUIDE.md`. Regression and timeout checks are in `tests/test_systems.py`.

## Troubleshooting and security boundary

If startup fails, check the active interpreter and installed requirements. If a port is busy, change `APP_PORT` locally or adjust both Compose port mappings. If Docker fails, inspect `docker compose ps -a` and `docker compose logs --tail=100`. If C/C++ verification is unavailable, check compiler paths and permissions. The app never executes submitted programs. Python compile occurs in a child interpreter with a timeout and temporary source; C/C++ compilers run with syntax-only flags. There is no verified network isolation or strict filesystem confinement for compiler processes outside Docker. Do not expose this development UI publicly for untrusted code. Never commit `.env` or credentials.
