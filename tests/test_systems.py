"""Real static-verification path and failure status regression tests."""

from src.systems.pipeline import run_pipeline
from src.systems.verification import source_hash, verify_candidate


BROKEN = "def add(a, b)\n    return a + b\n"
FIXED = "def add(a, b):\n    return a + b\n"


def test_verified_python_repair_and_immutable_original():
    original = BROKEN
    result = verify_candidate(original, FIXED, "python", expected_hash=source_hash(original))
    assert result.status == "VERIFIED"
    assert result.verification_ran and result.patch_applied
    assert result.tool_exit_code == 0 and result.target_resolved
    assert "+def add(a, b):" in result.diff
    assert original == BROKEN


def test_regression_is_rejected():
    result = verify_candidate(BROKEN, "def add(a, b):\n    return a +\n", "python")
    assert result.status == "REJECTED"
    assert result.new_diagnostics


def test_stale_hash_rejected_before_application():
    result = verify_candidate(BROKEN, FIXED, "python", expected_hash="0" * 64)
    assert result.status == "REJECTED"
    assert not result.patch_applied and not result.verification_ran


def test_pipeline_selects_real_verified_candidate():
    report = run_pipeline(BROKEN, "python")
    assert report.status == "VERIFIED"
    assert report.selected and report.selected.verification_ran
    assert report.repaired_code == FIXED
    assert report.attempts


def test_pipeline_unrepairable_terminates():
    report = run_pipeline("x = zzqqwwxx(1)\n", "python", max_attempts=2)
    assert report.status in {"NOT_REPAIRED", "INCONCLUSIVE"}
    assert len(report.attempts) <= 2


def test_verification_timeout_is_inconclusive(monkeypatch):
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = verify_candidate(BROKEN, FIXED, "python")
    assert result.status == "INCONCLUSIVE"
    assert result.patch_applied


def test_real_http_repair_endpoint_and_ui():
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from dev_frontend.server import Handler

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            assert json.load(response)["status"] == "ok"
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            assert b"Verification and attempt history" in response.read()
        body = json.dumps({"code": BROKEN, "language": "python"}).encode()
        request = urllib.request.Request(base + "/api/repair", data=body,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            report = json.load(response)
        assert report["status"] == "VERIFIED"
        assert report["selected"]["verification_ran"]
        assert report["repaired_code"] == FIXED
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_c_compiler_exit_code_when_available():
    import pytest
    from src.data_engine.language_adapters import get_adapter

    adapter = get_adapter("c")
    if not adapter.is_available():
        pytest.skip("C compiler unavailable")
    result = verify_candidate("int main(){return 0}", "int main(){return 0;}", "c")
    assert result.status == "VERIFIED"
    assert result.tool_exit_code == 0 and result.verification_ran
