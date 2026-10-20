"""Diagnostic normalization: de-duplication and root-most error ranking.

A single syntax mistake often produces a chain of follow-on errors (for example,
an undeclared identifier that only appears because an earlier declaration failed
to parse). Ranking picks the error that most plausibly started the chain.
"""

import re
from typing import List, Optional, Tuple

from src.analysis_engine.contracts import Diagnostic


# Messages produced by the parser / tokenizer stage
_PARSE_PATTERN = re.compile(
    r"expected|before|syntax|unmatched|never closed|end of input|indent|unterminated|unindent",
    re.IGNORECASE,
)

# Messages produced after parsing succeeds (type and name checking)
_SEMANTIC_PATTERN = re.compile(
    r"undeclared|not defined|undefined name|too few|too many|lvalue|invalid type|"
    r"incompatible|conversion|implicit declaration|redefinition|redeclaration|invalid operands",
    re.IGNORECASE,
)


def is_parse_level(diag: Diagnostic) -> bool:
    """True for errors raised by the parser rather than by name or type checking."""
    if diag.source == "ast":
        return True
    if _SEMANTIC_PATTERN.search(diag.message):
        return False
    return bool(_PARSE_PATTERN.search(diag.message))


def dedupe(diags: List[Diagnostic]) -> List[Diagnostic]:
    """Remove exact duplicates (same location, severity and message) keeping first-seen order."""
    seen = set()
    unique = []
    for diag in diags:
        key = (diag.line, diag.column, diag.severity, diag.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diag)
    return unique


def _position(diag: Diagnostic) -> Tuple[int, int]:
    return (diag.line if diag.line is not None else 10**9, diag.column or 0)


def rank(diags: List[Diagnostic]) -> Tuple[Optional[Diagnostic], List[Diagnostic]]:
    """Return (root, cascades) from a list of diagnostics.

    Rule: a semantic error that appears after the first parse-level error is treated
    as a cascade and suppressed. The root is the first remaining error by position.
    """
    errors = sorted(
        (d for d in diags if d.severity == "error"),
        key=_position,
    )
    if not errors:
        return None, []

    parse_lines = [d.line for d in errors if d.line is not None and is_parse_level(d)]
    first_parse_line = min(parse_lines) if parse_lines else None

    kept: List[Diagnostic] = []
    cascades: List[Diagnostic] = []
    for diag in errors:
        is_cascade = (
            first_parse_line is not None
            and diag.line is not None
            and diag.line > first_parse_line
            and not is_parse_level(diag)
        )
        (cascades if is_cascade else kept).append(diag)

    root = kept[0] if kept else errors[0]
    return root, cascades
