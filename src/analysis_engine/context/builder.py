"""Build an ErrorContext from source code and its root diagnostic."""

from src.analysis_engine.contracts import Diagnostic, ErrorContext
from src.analysis_engine.context import c_context, python_context
from src.analysis_engine.context.line_mapping import candidate_lines
from src.analysis_engine.detect.detector import normalize_language


def build_context(code: str, root: Diagnostic, language: str) -> ErrorContext:
    """Collect scope, symbols, brackets and candidate lines for one detected error.

    `root` is the root diagnostic from `detect()`. If the compiler reported a line
    past the end of the file, the line is clamped and `reported_line` shows the
    clamped value.
    """
    if root is None:
        raise ValueError("build_context needs a root diagnostic; run detect() first")

    lang = normalize_language(language)
    # Split on "\n" only, so line numbers match the compiler and the rule edits
    lines = code.split("\n") or [""]
    # A trailing newline leaves an empty last element that the compiler does not count
    n = len(lines) - 1 if len(lines) > 1 and lines[-1] == "" else len(lines)
    reported = min(max(root.line or 1, 1), n)

    if lang == "python":
        info = python_context.analyze(code, reported)
    else:
        info = c_context.analyze(code, reported)

    return ErrorContext(
        language=lang,
        code=code,
        root=root,
        reported_line=reported,
        candidate_lines=candidate_lines(
            lines, reported, root, lang,
            unclosed_brace_lines=[b.line for b in info["unclosed_at_eof"] if b.char == "{"],
        ),
        line_text=lines[reported - 1],
        prev_line_text=lines[reported - 2] if reported >= 2 else None,
        next_line_text=lines[reported] if reported < n else None,
        enclosing_scope=info["enclosing_scope"],
        symbols=info["symbols"],
        imports=info["imports"],
        open_brackets=info["open_brackets"],
        unclosed_at_eof=info["unclosed_at_eof"],
        indent_of_line=info["indent_of_line"],
        enclosing_indents=info["enclosing_indents"],
    )
