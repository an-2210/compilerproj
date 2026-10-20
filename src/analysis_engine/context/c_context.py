"""C and C++ context: functions, declared names, includes and open brackets.

This is lexical rather than a full parse, because the code being repaired does not
compile. It is accurate for the common shapes of student and mutated code, and it
never raises on malformed input.
"""

import re
from typing import Any, Dict, List, Tuple

from src.analysis_engine.context.scanner import sanitize, scan_brackets


_TYPE = (
    r"(?:(?:struct|enum|union)\s+\w+"
    r"|(?:int|char|short|long|float|double|void|bool|_Bool|size_t|auto|FILE|"
    r"unsigned|signed|\w+_t))"
)
_DECLARATION = re.compile(
    rf"(?<![\w.>])(?:(?:const|static|volatile|register|extern|inline)\s+)*{_TYPE}"
    r"\s*(?:\*+\s*)?(?P<name>[A-Za-z_]\w*)\s*(?=[=;,\[\)\(:])"
)
_FUNCTION_HEADER = re.compile(r"([A-Za-z_]\w*)\s*\(([^()]*)\)\s*(?:const\s*)?$")
_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)", re.MULTILINE)
_INCLUDE = re.compile(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", re.MULTILINE)


def _functions(sanitized: str) -> List[Tuple[str, int, int, str]]:
    """Return (name, open_line, close_line, parameter_text) for each top-level function."""
    functions = []
    depth = 0
    line = 1
    segment_start = 0
    pending: Dict[str, Any] = {}

    for idx, ch in enumerate(sanitized):
        if ch == "\n":
            line += 1
            continue
        if ch == "{":
            if depth == 0:
                header = sanitized[segment_start:idx].strip()
                match = _FUNCTION_HEADER.search(header)
                if match:
                    pending = {"name": match.group(1), "line": line, "params": match.group(2)}
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
            if depth == 0:
                if pending:
                    functions.append((pending["name"], pending["line"], line, pending["params"]))
                    pending = {}
                segment_start = idx + 1
        elif ch == ";" and depth == 0:
            segment_start = idx + 1

    total_lines = sanitized.count("\n") + 1
    if pending:
        # Function body never closed: it runs to the end of the file
        functions.append((pending["name"], pending["line"], total_lines, pending["params"]))
    return functions


def analyze(code: str, reported_line: int) -> Dict[str, Any]:
    sanitized = sanitize(code, "c")
    functions = _functions(sanitized)

    scope = None
    for name, start, end, _params in functions:
        if start <= reported_line <= end:
            scope = name

    symbols = {m.group("name") for m in _DECLARATION.finditer(sanitized)}
    symbols.update(name for name, _s, _e, _p in functions)
    symbols.update(_DEFINE.findall(sanitized))
    symbols.update(
        param_name
        for _name, _s, _e, params in functions
        for param_name in re.findall(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:,|$)", params)
    )

    open_at_line, unclosed = scan_brackets(sanitized, reported_line)
    return {
        "enclosing_scope": scope,
        "symbols": sorted(symbols),
        "imports": sorted(set(_INCLUDE.findall(code))),
        "open_brackets": open_at_line,
        "unclosed_at_eof": unclosed,
        "indent_of_line": None,
        "enclosing_indents": [],
    }
