"""Compiler-grounded regression checks for unnamed C string parameters."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from dev_frontend.server import Handler
from src.analysis_engine import build_context, detect, rule_repair
from src.analysis_engine.contracts import Diagnostic
from src.data_engine.language_adapters import get_adapter
from src.model.candidate_generator import analyze_and_repair
from src.systems.pipeline import run_pipeline
from src.systems.verification import verify_candidate


REPRO = """bool is_palindrome(const char *) {
    int left = 0;
    int right = strlen(s) - 1;
    while (left < right) {
        if (s[left] != s[right]) {
            return false;
        }
        left++;
        right--;
    }
    return true;
}
"""
FIXED = "#include <stdbool.h>\n#include <string.h>\n" + REPRO.replace(
    "const char *)", "const char *s)")


def _normalize_gcc_quotes(message: str) -> str:
    return message.translate(str.maketrans({"‘": "'", "’": "'"}))


@pytest.fixture(autouse=True)
def require_c_compiler():
    if not get_adapter("c").is_available():
        pytest.skip("C compiler unavailable")


def test_exact_reproduction_names_parameter_and_verifies():
    source = REPRO
    report = run_pipeline(source, "c")
    assert _normalize_gcc_quotes(report.detection.root.message) == "unknown type name 'bool'"
    assert any("'s' undeclared" in _normalize_gcc_quotes(d.message)
               for d in report.detection.diagnostics)
    assert report.repair["chosen"]["rule_id"] == "c_unnamed_char_parameter"
    assert report.status == "VERIFIED" and report.repaired_code == FIXED
    assert report.selected.verification_ran and report.selected.tool_exit_code == 0
    assert report.selected.target_resolved and not report.selected.new_diagnostics
    assert "+bool is_palindrome(const char *s)" in report.selected.diff
    assert "while (left < right) {:" not in report.selected.diff
    assert source == REPRO


def test_named_parameter_rule_uses_compiler_evidence():
    source = "#include <string.h>\nint length(const char *) {\n    return strlen(s) + s[0];\n}\n"
    detection = detect(source, "c", layers="fast")
    context = build_context(source, detection.root, "c", detection.diagnostics)
    repair = rule_repair(context)
    assert repair.chosen and repair.chosen.rule_id == "c_unnamed_char_parameter"
    report = run_pipeline(source, "c", include_model=False)
    assert report.status == "VERIFIED"
    assert "const char *s" in report.repaired_code


def test_linux_gcc_diagnostics_without_omitted_parameter_message():
    """The running image uses curly quotes and omits GCC's separate name error."""
    diagnostics = [
        Diagnostic(message="unknown type name ‘bool’", line=1, severity="error", source="gcc"),
        Diagnostic(message="implicit declaration of function ‘strlen’", line=3,
                   severity="error", source="gcc"),
        Diagnostic(message="‘s’ undeclared (first use in this function)", line=3,
                   severity="error", source="gcc"),
        Diagnostic(message="‘false’ undeclared (first use in this function)", line=6,
                   severity="error", source="gcc"),
        Diagnostic(message="‘true’ undeclared (first use in this function)", line=11,
                   severity="error", source="gcc"),
    ]
    context = build_context(REPRO, diagnostics[0], "c", diagnostics)
    repair = rule_repair(context)
    assert repair.chosen and repair.chosen.rule_id == "c_unnamed_char_parameter"
    assert repair.chosen.code == FIXED
    assert verify_candidate(REPRO, repair.chosen.code, "c").status == "VERIFIED"


def test_ambiguous_or_weak_name_evidence_produces_no_rule():
    for body in ("return s[0] + t[0] + s[1] + t[1];", "return s[0];"):
        source = f"int f(const char *) {{\n    {body}\n}}\n"
        detection = detect(source, "c", layers="fast")
        context = build_context(source, detection.root, "c", detection.diagnostics)
        repair = rule_repair(context)
        assert all(c.rule_id != "c_unnamed_char_parameter" for c in repair.rule_candidates)
    assert run_pipeline(source, "c", include_model=False).status == "NOT_REPAIRED"


def test_mock_never_adds_python_colon_or_placeholder_comment_to_c():
    detection = detect(REPRO, "c", layers="fast")
    context = build_context(REPRO, detection.root, "c", detection.diagnostics)
    candidates = analyze_and_repair(context, k=2)
    assert candidates and candidates[0].repaired_code == FIXED
    assert "while (left < right) {:" not in candidates[0].repaired_code
    ambiguous = "int f(const char *) {\n    return s[0] + t[0] + s[1] + t[1];\n}\n"
    detection = detect(ambiguous, "c", layers="fast")
    context = build_context(ambiguous, detection.root, "c", detection.diagnostics)
    assert analyze_and_repair(context, k=2) == []


def test_malformed_c_candidate_is_rejected_as_regression():
    malformed = REPRO.replace("while (left < right) {", "while (left < right) {:")
    result = verify_candidate(REPRO, malformed, "c")
    assert result.status == "REJECTED" and result.verification_ran
    assert any("expected expression" in d.message for d in result.new_diagnostics)
    assert "+    while (left < right) {:" in result.diff


def test_syntactically_valid_candidate_leaving_original_error_is_not_accepted():
    source = "#include <stdbool.h>\n#include <string.h>\n" + REPRO
    candidate = source.replace("int left = 0;", "int left = 0; /* unchanged behavior */")
    result = verify_candidate(source, candidate, "c")
    assert result.status == "NOT_REPAIRED" and result.verification_ran
    assert result.tool_exit_code != 0 and not result.target_resolved
    assert not result.new_diagnostics


def test_new_unrelated_c_error_is_rejected():
    candidate = FIXED.replace("return true;", "return other_missing_name;")
    result = verify_candidate(REPRO, candidate, "c")
    assert result.status == "REJECTED" and result.verification_ran
    assert any("other_missing_name" in d.message for d in result.new_diagnostics)
    assert result.target_resolved  # the original bool error was resolved


def test_http_reproduction_exposes_diff_verification_and_ui_contract():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            page = response.read().decode("utf-8")
        assert "attempt.diff" in page
        assert 'data.status === "VERIFIED" ? data.repaired_code : null' in page
        assert "No deterministic rule has enough evidence" in page
        body = json.dumps({"code": REPRO, "language": "c"}).encode()
        request = urllib.request.Request(base + "/api/repair", data=body,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            assert response.status == 200
            report = json.load(response)
        assert report["status"] == "VERIFIED"
        assert report["repaired_code"] == FIXED
        assert report["attempts"][0]["status"] == "VERIFIED"
        assert "+bool is_palindrome(const char *s)" in report["attempts"][0]["diff"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
