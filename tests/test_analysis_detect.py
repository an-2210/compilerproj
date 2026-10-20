"""Analysis Engineer: layered detection and root-error ranking."""

import pytest

from src.analysis_engine import detect
from src.analysis_engine.contracts import Diagnostic
from src.analysis_engine.detect.normalizer import dedupe, rank


def _diag(message, line, source="gcc", severity="error", column=1):
    return Diagnostic(message=message, line=line, column=column, severity=severity, source=source)


# ---------------------------------------------------------------- Python layers

def test_python_syntax_error_reported_by_ast_layer():
    result = detect("def f(x)\n    return x\n", "python", layers="fast")
    assert result.detected
    assert result.layer == "ast"
    assert result.root.line == 1
    assert result.root.category == "delimiter_punctuation"


def test_python_clean_program_is_not_flagged():
    code = "import math\n\n\ndef area(r):\n    return math.pi * r * r\n"
    result = detect(code, "python", layers="full")
    assert not result.detected
    assert result.root is None
    assert result.diagnostics == []


def test_python_undefined_name_found_by_pyflakes_layer():
    result = detect("total = 1\nprint(totl)\n", "python", layers="fast")
    assert result.detected
    assert result.layer == "pyflakes"
    assert result.root.line == 2
    assert "totl" in result.root.message


def test_python_style_warnings_do_not_count_as_errors():
    # An unused import is a pyflakes warning, not an error
    result = detect("import os\nx = 1\n", "python", layers="fast")
    assert not result.detected


def test_unknown_layer_name_is_rejected():
    with pytest.raises(ValueError):
        detect("x = 1\n", "python", layers="turbo")


def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError):
        detect("x = 1\n", "rust")


# ---------------------------------------------------------------- C / C++ (compiler)

@pytest.mark.compiler
def test_c_clean_program_is_not_flagged():
    code = '#include <stdio.h>\nint main(void) {\n    printf("hi\\n");\n    return 0;\n}\n'
    result = detect(code, "c")
    assert not result.detected


@pytest.mark.compiler
def test_c_missing_semicolon_detected_with_compiler_source():
    code = "int main(void) {\n    int x = 1\n    return x;\n}\n"
    result = detect(code, "c")
    assert result.detected
    assert result.layer == "gcc"
    # The compiler may report the missing ';' on line 2 or on the next token's line 3
    assert result.root.line in {2, 3}


@pytest.mark.compiler
def test_cpp_mismatched_bracket_detected():
    code = "int main() {\n    int a[3 = {1, 2, 3};\n    return 0;\n}\n"
    result = detect(code, "cpp")
    assert result.detected
    assert result.root.line == 2


# ---------------------------------------------------------------- Normalizer

def test_dedupe_removes_exact_duplicates_only():
    a = _diag("expected ';'", 4)
    b = _diag("expected ';'", 4)
    c = _diag("expected ';'", 5)
    assert dedupe([a, b, c]) == [a, c]


def test_rank_suppresses_semantic_cascade_after_parse_error():
    parse = _diag("expected ';' before 'printf'", 5)
    cascade = _diag("'ret' undeclared (first use in this function)", 9)
    root, cascades = rank([cascade, parse])
    assert root == parse
    assert cascades == [cascade]


def test_rank_keeps_semantic_error_that_comes_before_parse_error():
    early = _diag("too few arguments to function 'f'", 3)
    later = _diag("expected ')' before ';'", 8)
    root, cascades = rank([later, early])
    assert root == early
    assert cascades == []


def test_rank_returns_none_when_no_errors():
    warning = _diag("unused variable", 2, severity="warning")
    assert rank([warning]) == (None, [])
