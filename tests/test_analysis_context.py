"""Analysis Engineer: context building and reported-line mapping."""

from src.analysis_engine import build_context, detect
from src.analysis_engine.contracts import Diagnostic
from src.analysis_engine.context.line_mapping import candidate_lines
from src.analysis_engine.context.scanner import sanitize, scan_brackets, indentation_stack


def _root(message, line, column=None, source="gcc"):
    return Diagnostic(message=message, line=line, column=column, source=source)


# ---------------------------------------------------------------- Scanner

def test_sanitize_blanks_comments_and_strings_but_keeps_positions():
    text = 'x = "a(b"  # (comment\ny = 2\n'
    cleaned = sanitize(text, "python")
    assert len(cleaned) == len(text)
    assert "(" not in cleaned
    assert cleaned.count("\n") == text.count("\n")


def test_scan_brackets_reports_open_at_line_and_unclosed_at_eof():
    text = "f(a,\n  [1, 2)\n"
    sanitized = sanitize(text, "python")
    open_at_line2, unclosed = scan_brackets(sanitized, 2)
    assert [b.char for b in open_at_line2] == ["("]
    assert [b.char for b in unclosed] == []


def test_indentation_stack_tracks_open_blocks():
    lines = ["def f():", "    if x:", "        y = 1", "    z = 2"]
    assert indentation_stack(lines, 4) == [0, 4, 8]


# ---------------------------------------------------------------- Python context

def test_python_context_finds_scope_symbols_and_imports_on_broken_file():
    code = (
        "import math\n"
        "\n"
        "def area(r):\n"
        "    scale = 2\n"
        "    return math.pi * r * scale +\n"
        "\n"
        "value = area(3)\n"
    )
    result = detect(code, "python", layers="fast")
    ctx = build_context(code, result.root, "python")
    assert ctx.enclosing_scope is None or ctx.enclosing_scope == "area"
    assert "value" in ctx.symbols or "scale" in ctx.symbols
    assert "math" in ctx.imports
    assert ctx.line_text == code.splitlines()[ctx.reported_line - 1]


def test_python_context_reports_indent_and_enclosing_levels():
    code = "def f(x):\n    if x:\n        y = 1\n      return y\n"
    result = detect(code, "python", layers="fast")
    ctx = build_context(code, result.root, "python")
    assert ctx.indent_of_line == 6
    assert 4 in ctx.enclosing_indents and 8 in ctx.enclosing_indents


# ---------------------------------------------------------------- C context

def test_c_context_scope_includes_and_declared_names():
    code = (
        "#include <stdio.h>\n"
        "int square(int n) {\n"
        "    int result = n * n\n"
        "    return result;\n"
        "}\n"
    )
    result = detect(code, "c", layers="fast")
    ctx = build_context(code, result.root, "c")
    assert ctx.enclosing_scope == "square"
    assert "stdio.h" in ctx.imports
    assert {"square", "n", "result"}.issubset(set(ctx.symbols))


def test_c_context_open_brackets_ignore_brackets_in_strings():
    code = 'int main(void) {\n    printf("(((");\n    int a = (1 + 2;\n}\n'
    result = detect(code, "c", layers="fast")
    ctx = build_context(code, result.root, "c")
    assert [b.char for b in ctx.open_brackets] == ["{"]


def test_build_context_requires_a_root():
    try:
        build_context("int x;", None, "c")
    except ValueError:
        return
    raise AssertionError("expected ValueError when root is None")


# ---------------------------------------------------------------- Line mapping

def test_missing_semicolon_maps_gcc_line_back_to_previous_statement():
    # gcc reports the next token on line 5, but the missing ';' is on line 4
    lines = [
        "int main(void) {",
        "    int ret = 0",
        "    int other = 1;",
        "    return ret;",
        "}",
    ]
    root = _root("expected ';' before 'other'", line=3, column=9)
    assert candidate_lines(lines, 3, root, "c")[0] == 2


def test_missing_semicolon_stays_on_reported_line_when_token_is_mid_line():
    lines = ["int main(void) {", "    int x = 1 int y = 2;", "}"]
    root = _root("expected ';' before 'int'", line=2, column=16)
    assert candidate_lines(lines, 2, root, "c")[0] == 2


def test_undeclared_name_keeps_reported_line():
    lines = ["int main(void) {", "    int a = 1;", "    return b;", "}"]
    root = _root("'b' undeclared (first use in this function)", line=3, column=12)
    assert candidate_lines(lines, 3, root, "c")[0] == 3


def test_blanked_closing_brace_maps_to_blank_top_level_line():
    lines = ["int main(void) {", "    return 0;", ""]
    root = _root("expected declaration or statement at end of input", line=3)
    assert candidate_lines(lines, 3, root, "c", unclosed_brace_lines=[1])[0] == 3


def test_reported_line_is_clamped_to_file_length():
    code = "x = (1\n"
    result = detect(code, "python", layers="fast")
    ctx = build_context(code, result.root.model_copy(update={"line": 99}), "python")
    assert ctx.reported_line == 1
