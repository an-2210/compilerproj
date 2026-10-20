"""Validate a proposed full-source edit without touching the submitted source."""

from __future__ import annotations

import difflib
import hashlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.analysis_engine.contracts import Diagnostic
from src.analysis_engine.detect.detector import detect, normalize_language

MAX_SOURCE_BYTES = 100_000
MAX_CHANGED_LINES = 30


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


class VerificationResult(BaseModel):
    status: Literal["VERIFIED", "REJECTED", "NOT_REPAIRED", "INCONCLUSIVE"]
    reason: str
    candidate_id: str
    original_hash: str
    candidate_hash: str | None = None
    patch_applied: bool = False
    verification_ran: bool = False
    baseline_diagnostics: list[Diagnostic] = Field(default_factory=list)
    candidate_diagnostics: list[Diagnostic] = Field(default_factory=list)
    new_diagnostics: list[Diagnostic] = Field(default_factory=list)
    target_resolved: bool = False
    changed_lines: int = 0
    diff: str = ""
    tool_exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0


def _identity(diag: Diagnostic) -> tuple[str, str, str | None]:
    return (diag.source, diag.message, diag.code)


def verify_candidate(
    original: str,
    candidate: str,
    language: str,
    *,
    candidate_id: str = "candidate",
    expected_hash: str | None = None,
    timeout_seconds: float = 5.0,
) -> VerificationResult:
    """Static verification on a temporary copy. Source is never executed."""
    started = time.monotonic()
    digest = source_hash(original)
    result = VerificationResult(status="REJECTED", reason="invalid candidate", candidate_id=candidate_id,
                                original_hash=digest)

    def finish() -> VerificationResult:
        result.duration_ms = round((time.monotonic() - started) * 1000, 2)
        return result

    if expected_hash is not None and expected_hash != digest:
        result.reason = "stale original source hash"
        return finish()
    if not isinstance(original, str) or not isinstance(candidate, str) or not original.strip() or not candidate.strip():
        result.reason = "source and candidate must be non-empty strings"
        return finish()
    if len(original.encode("utf-8")) > MAX_SOURCE_BYTES or len(candidate.encode("utf-8")) > MAX_SOURCE_BYTES:
        result.reason = "source exceeds size limit"
        return finish()
    if candidate == original:
        result.reason = "candidate does not change source"
        return finish()
    if timeout_seconds <= 0 or timeout_seconds > 30:
        result.reason = "timeout must be greater than zero and at most 30 seconds"
        return finish()
    try:
        lang = normalize_language(language)
    except ValueError:
        result.reason = "unsupported language"
        return finish()

    before = original.splitlines(keepends=True)
    after = candidate.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    result.changed_lines = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")
    if result.changed_lines > MAX_CHANGED_LINES:
        result.reason = "candidate changes too many lines"
        return finish()
    result.diff = "".join(difflib.unified_diff(before, after, fromfile="original", tofile="candidate"))
    result.candidate_hash = source_hash(candidate)

    try:
        baseline = detect(original, lang, layers="fast")
        result.baseline_diagnostics = baseline.diagnostics
        if not baseline.detected:
            result.reason = "original source has no detected error"
            return finish()
        suffix = {"python": ".py", "c": ".c", "cpp": ".cpp"}[lang]
        with tempfile.TemporaryDirectory(prefix="compiler-repair-") as tmp:
            path = Path(tmp) / ("candidate" + suffix)
            path.write_bytes(candidate.encode("utf-8"))
            result.patch_applied = True
            if lang == "python":
                # compile() parses and emits bytecode but never executes submitted code.
                checker = "import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], 'exec')"
                proc = subprocess.run([sys.executable, "-I", "-c", checker, str(path)],
                                      cwd=tmp, capture_output=True, text=True, timeout=timeout_seconds)
                result.tool_exit_code = proc.returncode
                result.stdout = proc.stdout[:8192]
                result.stderr = proc.stderr[:8192]
                result.verification_ran = True
            candidate_detection = detect(candidate, lang, layers="fast")
            result.candidate_diagnostics = candidate_detection.diagnostics
            if lang != "python":
                # C/C++ detection invokes the real compiler through the existing adapter.
                result.verification_ran = True
                result.tool_exit_code = 1 if candidate_detection.detected else 0
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        result.status = "INCONCLUSIVE"
        result.reason = f"verification timed out: {type(exc).__name__}"
        return finish()
    except (OSError, RuntimeError, ImportError) as exc:
        result.status = "INCONCLUSIVE"
        result.reason = f"verification tool unavailable: {type(exc).__name__}: {exc}"
        return finish()

    old_errors = [d for d in result.baseline_diagnostics if d.severity == "error"]
    new_errors = [d for d in result.candidate_diagnostics if d.severity == "error"]
    old_keys = {_identity(d) for d in old_errors}
    result.new_diagnostics = [d for d in new_errors if _identity(d) not in old_keys]
    target = baseline.root
    result.target_resolved = target is not None and all(_identity(d) != _identity(target) for d in new_errors)
    if result.tool_exit_code != 0 and not new_errors:
        result.status = "INCONCLUSIVE"
        result.reason = "compiler failed without a normalized diagnostic"
    elif result.new_diagnostics:
        result.status = "REJECTED"
        result.reason = "candidate introduced a new error"
    elif not result.target_resolved:
        result.status = "NOT_REPAIRED"
        result.reason = "target error remains"
    elif new_errors or result.tool_exit_code != 0:
        result.status = "NOT_REPAIRED"
        result.reason = "target resolved but other errors remain"
    else:
        result.status = "VERIFIED"
        result.reason = "target resolved with no detected errors"
    return finish()
