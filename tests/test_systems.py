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
