"""Layered error detector.

Python is checked in layers, cheapest first, and a later layer only runs when the
earlier ones found nothing:

    ast       -> parser errors (SyntaxError), exact line and column
    pyflakes  -> undefined names (allow-listed; style warnings are ignored)
    mypy      -> name, call and operator errors (allow-listed codes; "full" only)

C and C++ use the Data Engineer's gcc / g++ adapter (`-fsyntax-only -Wall`), so the
Analysis and Data layers agree on what counts as a compiler error.
"""

import ast
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.data_engine.language_adapters import LanguageAdapter, get_adapter
from src.analysis_engine.contracts import Diagnostic, DetectionResult
from src.analysis_engine.detect.normalizer import dedupe, rank
from src.analysis_engine.detect.taxonomy import classify_message


# pyflakes messages that are real errors here. Unused imports and similar style
# warnings are deliberately excluded so clean programs are not flagged.
PYFLAKES_ERROR_CLASSES = {"UndefinedName", "UndefinedLocal"}

# mypy error codes treated as errors. Other codes (for example untyped-call and
# misc notes) are too noisy on unannotated student code.
MYPY_ERROR_CODES = {"name-defined", "call-arg", "operator", "index", "attr-defined"}

MYPY_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>error|warning|note):\s*"
    r"(?P<msg>.*?)(?:\s+\[(?P<code>[\w-]+)\])?$"
)

LAYER_SETS = {
    "fast": ("ast", "pyflakes"),
    "full": ("ast", "pyflakes", "mypy"),
}

_LANGUAGE_ALIASES = {"c": "c", "cpp": "cpp", "c++": "cpp", "python": "python", "py": "python"}
_adapter_cache: Dict[str, LanguageAdapter] = {}


def normalize_language(language: str) -> str:
    key = str(getattr(language, "value", language)).lower()
    if key not in _LANGUAGE_ALIASES:
        raise ValueError(f"Unsupported language: {language}")
    return _LANGUAGE_ALIASES[key]


def _category(message: str) -> Tuple[str, str]:
    return classify_message(message)


def _python_syntax_diagnostic(err: SyntaxError) -> Diagnostic:
    message = err.msg or "invalid syntax"
    category, subcategory = _category(message)
    # CPython can report 0 or None for unknown positions; the contract needs >= 1 or None
    line = err.lineno if err.lineno and err.lineno >= 1 else None
    column = err.offset if err.offset and err.offset >= 1 else None
    return Diagnostic(
        message=message,
        line=line,
        column=column,
        severity="error",
        source="ast",
        category=category,
        subcategory=subcategory,
        raw=f"SyntaxError: {message} (line {err.lineno}, column {err.offset})",
    )


def _run_pyflakes(tree: ast.AST) -> List[Diagnostic]:
    from pyflakes import checker

    found = []
    for msg in checker.Checker(tree, filename="input.py").messages:
        cls_name = type(msg).__name__
        if cls_name not in PYFLAKES_ERROR_CLASSES:
            continue
        name = msg.message_args[0]
        found.append(
            Diagnostic(
                message=f"undefined name {name!r}",
                line=msg.lineno,
                column=msg.col + 1,
                severity="error",
                source="pyflakes",
                code=cls_name,
                category="declaration_identifier",
                subcategory="undeclared_identifier",
                raw=f"input.py:{msg.lineno}:{msg.col + 1}: {msg.message % msg.message_args}",
            )
        )
    return found


def _run_mypy(code: str) -> List[Diagnostic]:
    try:
        import mypy.api
    except ImportError:
        # Type checking is an optional layer; AST and pyflakes have already run.
        return []

    found = []
    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "input.py"
        source_file.write_text(code, encoding="utf-8")
        stdout, _stderr, _status = mypy.api.run([
            str(source_file),
            "--no-error-summary",
            "--hide-error-context",
            "--show-column-numbers",
            "--show-error-codes",
            "--no-incremental",
            f"--cache-dir={Path(tmpdir) / 'mypy-cache'}",
            "--follow-imports=skip",
        ])
    for raw_line in stdout.splitlines():
        match = MYPY_LINE.match(raw_line.strip())
        if not match or match.group("sev") != "error":
            continue
        code_name = match.group("code")
        if code_name not in MYPY_ERROR_CODES:
            continue
        category, subcategory = _category(match.group("msg"))
        found.append(
            Diagnostic(
                message=match.group("msg").strip(),
                line=int(match.group("line")),
                column=int(match.group("col")) + 1 if match.group("col") else None,
                severity="error",
                source="mypy",
                code=code_name,
                category=category,
                subcategory=subcategory,
                raw=raw_line,
            )
        )
    return found


def _detect_python(code: str, layers: str) -> Tuple[List[Diagnostic], Optional[str]]:
    import sys

    version = f"Python {sys.version.split()[0]}"
    try:
        tree = ast.parse(code, filename="input.py")
    except SyntaxError as err:
        # Later layers need a parse tree, so a syntax error ends detection here
        return [_python_syntax_diagnostic(err)], version
    except ValueError as err:
        # Raised for source containing null bytes
        return [Diagnostic(message=str(err), severity="error", source="ast",
                           category="syntax", subcategory="syntax_error", raw=str(err))], version

    diags: List[Diagnostic] = []
    if "pyflakes" in LAYER_SETS[layers]:
        diags += _run_pyflakes(tree)
    if "mypy" in LAYER_SETS[layers] and not any(d.severity == "error" for d in diags):
        diags += _run_mypy(code)
    return diags, version


def _detect_c_family(code: str, language: str) -> Tuple[List[Diagnostic], Optional[str]]:
    if language not in _adapter_cache:
        _adapter_cache[language] = get_adapter(language)
    adapter = _adapter_cache[language]
    result = adapter.compile_or_parse(code, timeout_seconds=5.0)

    if not result.compiler_available and result.tool_name != "pycparser":
        raise RuntimeError(f"{result.tool_name} is not installed; cannot run {language} detection")

    diags = []
    for raw in result.diagnostics:
        category, subcategory = _category(raw.message)
        severity = getattr(raw.severity, "value", str(raw.severity))
        if severity not in ("error", "warning", "note"):
            severity = "note"
        diags.append(
            Diagnostic(
                message=raw.message,
                line=raw.line,
                column=raw.column,
                severity=severity,
                source=result.tool_name,
                category=category,
                subcategory=subcategory,
                raw=raw.raw_text or raw.message,
            )
        )
    if not result.success and not any(d.severity == "error" for d in diags):
        # Non-zero exit with no parsable diagnostic still counts as a failure
        diags.append(
            Diagnostic(
                message=(result.stderr or "compilation failed").strip().splitlines()[0],
                severity="error",
                source=result.tool_name,
                category="unknown",
                subcategory="general_error",
                raw=result.stderr,
            )
        )
    return diags, result.tool_version


def detect(code: str, language: str, layers: str = "full") -> DetectionResult:
    """Detect compiler-level errors in `code`.

    `layers` is "fast" (ast and pyflakes for Python) or "full" (adds mypy).
    C and C++ always use the compiler; `layers` has no effect there.
    """
    if layers not in LAYER_SETS:
        raise ValueError(f"layers must be one of {sorted(LAYER_SETS)}, got {layers!r}")
    lang = normalize_language(language)

    if lang == "python":
        diags, version = _detect_python(code, layers)
    else:
        diags, version = _detect_c_family(code, lang)

    diags = dedupe(diags)
    root, cascades = rank(diags)
    detected = any(d.severity == "error" for d in diags)
    return DetectionResult(
        language=lang,
        detected=detected,
        layer=root.source if root is not None else None,
        tool_version=version,
        diagnostics=sorted(diags, key=lambda d: (d.line or 10**9, d.column or 0)),
        root=root,
        cascades=cascades,
    )
