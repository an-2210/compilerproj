"""Python context: scope, symbols and imports for code that may not parse.

parso is used instead of the stdlib ast module because it recovers from syntax
errors and still returns a usable tree for the parts of the file that are valid.
"""

from typing import Any, Dict, List, Optional

import parso

from src.analysis_engine.context.scanner import (
    indent_of,
    indentation_stack,
    sanitize,
    scan_brackets,
)


_GRAMMAR = parso.load_grammar()


def _enclosing_scope(module: Any, line: int) -> Optional[str]:
    best = None
    for node in list(module.iter_funcdefs()) + list(module.iter_classdefs()):
        start, end = node.start_pos[0], node.end_pos[0]
        if start <= line <= end and (best is None or start > best[0]):
            best = (start, node.name.value)
    return best[1] if best else None


def analyze(code: str, reported_line: int) -> Dict[str, Any]:
    lines = code.split("\n") or [""]
    module = _GRAMMAR.parse(code)

    used = module.get_used_names()
    symbols = sorted(
        name for name, leaves in used.items()
        if any(leaf.is_definition() for leaf in leaves)
    )
    imports = sorted({
        name.value
        for imp in module.iter_imports()
        for name in imp.get_defined_names()
    })

    sanitized = sanitize(code, "python")
    open_at_line, unclosed = scan_brackets(sanitized, reported_line)

    indent_here = indent_of(lines[reported_line - 1]) if lines[reported_line - 1].strip() else None
    return {
        "enclosing_scope": _enclosing_scope(module, reported_line),
        "symbols": symbols,
        "imports": imports,
        "open_brackets": open_at_line,
        "unclosed_at_eof": unclosed,
        "indent_of_line": indent_here,
        "enclosing_indents": indentation_stack(lines, reported_line),
    }
