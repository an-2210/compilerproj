"""Tests for compiler/parser adapters, diagnostic parsing, and toolchain timeouts."""

import pytest
from src.data_engine.language_adapters import get_adapter
from src.data_engine.diagnostic_collector import DiagnosticCollector
from src.data_engine.schemas import Language, DiagnosticSeverity


def test_python_adapter_valid_source():
    adapter = get_adapter(Language.PYTHON)
    res = adapter.compile_or_parse("def foo():\n    return 42\n")
    assert res.success is True
    assert res.exit_code == 0
    assert len(res.diagnostics) == 0


def test_python_adapter_syntax_error():
    adapter = get_adapter(Language.PYTHON)
    res = adapter.compile_or_parse("def foo()\n    return 42\n")
    assert res.success is False
    assert res.exit_code != 0
    assert len(res.diagnostics) >= 1
    diag = res.diagnostics[0]
    assert diag.line == 1
    assert diag.severity == DiagnosticSeverity.ERROR
    assert "expected ':'" in diag.message or "invalid syntax" in diag.message


def test_c_adapter_valid_source():
    adapter = get_adapter(Language.C)
    if not adapter.is_available():
        pytest.skip("GCC not available")
    res = adapter.compile_or_parse("int main() { return 0; }\n")
    assert res.success is True
    assert res.exit_code == 0


def test_c_adapter_syntax_error():
    adapter = get_adapter(Language.C)
    if not adapter.is_available():
        pytest.skip("GCC not available")
    res = adapter.compile_or_parse("int main() { return 0 }\n")
    assert res.success is False
    assert res.exit_code != 0
    assert len(res.diagnostics) >= 1
    diag = res.diagnostics[0]
    assert diag.line == 1
    assert "expected ';'" in diag.message


def test_c_adapter_normalizes_gcc_typographic_quotes_without_losing_raw_output():
    adapter = get_adapter(Language.C)
    raw = "input.c:1:23: error: expected ‘;’ before ‘}’ token"
    diagnostics = adapter.extract_diagnostics(raw, "")
    assert len(diagnostics) == 1
    assert diagnostics[0].message == "expected ';' before '}' token"
    assert diagnostics[0].raw_text == raw


def test_cpp_adapter_valid_source():
    adapter = get_adapter(Language.CPP)
    if not adapter.is_available():
        pytest.skip("G++ not available")
    res = adapter.compile_or_parse("#include <iostream>\nint main() { return 0; }\n")
    assert res.success is True


def test_diagnostic_collector_error_info():
    collector = DiagnosticCollector()
    res = collector.compile_and_collect("x = [1, 2\n", Language.PYTHON)
    info = collector.extract_error_info(res, default_category="delimiter_punctuation")
    assert info.exit_code != 0
    assert len(info.diagnostics) >= 1
    assert info.category in ("syntax", "delimiter_punctuation")


def test_timeout_handling():
    # Verify timeout parameter does not crash adapter
    adapter = get_adapter(Language.PYTHON)
    res = adapter.compile_or_parse("x = 1\n", timeout_seconds=0.0001)
    # Even if very short, returns CompilationResult gracefully
    assert res is not None
