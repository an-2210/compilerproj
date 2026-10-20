"""Map the line a compiler reports to the line that actually holds the mistake.

The best-known case is a missing semicolon. The parser only notices it at the next
token, which is usually on the following line:

    int ret = 0          <- real mistake (line 4)
    printf("hi\\n");      <- compiler reports "expected ';' before 'printf'" (line 5)

Other messages (undeclared names, bad operators) point at the real line, so the
reported line stays first for them.
"""

import re
from typing import List, Sequence

from src.analysis_engine.contracts import Diagnostic
from collections import Counter

from src.analysis_engine.context.scanner import code_part, indent_of


# gcc: "expected ';' ..."; clang: "expected ';' at end of declaration"; gcc also says
# "expected initializer before X" when a declaration is followed by a new statement
_MISSING_TERMINATOR = re.compile(r"expected [^\n]*';'|expected initializer before", re.IGNORECASE)
_CONTROL_WORDS = ("if", "else", "for", "while", "switch", "do", "case", "default")


def _nonblank(lines: List[str], k: int) -> bool:
    return 1 <= k <= len(lines) and bool(lines[k - 1].strip())


def lacks_terminator(lines: List[str], k: int, language: str) -> bool:
    """True when line k (1-indexed) looks like a finished C/C++ statement with no ';'."""
    if language == "python" or not (1 <= k <= len(lines)):
        return False
    code = code_part(lines[k - 1], language).rstrip()
    stripped = code.lstrip()
    if not stripped or stripped.startswith("#"):
        return False
    if code.endswith((";", "{", "}", ",", "(", "[", "\\", ":")):
        return False
    if code[-1] in "+-*/%=&|^<>!?.":
        return False
    if code.count("(") > code.count(")"):
        # Multi-line call or condition: not a finished statement
        return False

    first_word = re.match(r"[A-Za-z_]\w*", stripped)
    if first_word and first_word.group(0) in _CONTROL_WORDS and code.endswith((")", "else", "do")):
        return False
    # A function header is followed by its body, which starts with "{"
    next_idx = k
    while next_idx < len(lines) and not lines[next_idx].strip():
        next_idx += 1
    if next_idx < len(lines) and lines[next_idx].lstrip().startswith("{") and code.endswith(")"):
        return False
    return True


def _indent_unit(lines: List[str]) -> int:
    """Most common non-zero indentation width in the file, defaulting to 4."""
    widths = Counter(
        indent_of(line) for line in lines
        if line.strip() and indent_of(line) > 0 and not line.lstrip().startswith("#")
    )
    return widths.most_common(1)[0][0] if widths else 4


def _first_nonspace_column(line: str) -> int:
    return len(line) - len(line.lstrip()) + 1


def _blank_top_level_lines(lines: List[str], opener_line: int) -> List[int]:
    """Blank lines after `opener_line` that sit at column 0 (end of a top-level block)."""
    found = []
    for k in range(opener_line + 1, len(lines) + 1):
        if lines[k - 1].strip():
            continue
        following = next((j for j in range(k + 1, len(lines) + 1) if lines[j - 1].strip()), None)
        if following is None or not lines[following - 1][:1].isspace():
            found.append(k)
    return found


def candidate_lines(
    lines: List[str],
    reported: int,
    root: Diagnostic,
    language: str,
    unclosed_brace_lines: Sequence[int] = (),
) -> List[int]:
    """Ranked candidate lines for the true error location, best first.

    `reported` must already be clamped to the file. `unclosed_brace_lines` are the
    lines of '{' still open at end of file. The result always contains at least one line.
    """
    n = len(lines)
    reported = min(max(reported, 1), max(n, 1))
    ordered: List[int] = []

    # "expected declaration or statement at end of input" is reported at EOF, but the
    # missing '}' belongs to the open block. Its likely place is a blank top-level line.
    msg = root.message or ""
    if language != "python" and re.search(r"end of input|expected '\}'", msg) and unclosed_brace_lines:
        ordered = _blank_top_level_lines(lines, unclosed_brace_lines[-1])[:2]

    # Python "unexpected indent" is often caused by the line above, which is indented by a
    # width that does not match the file's indent unit (for example 3 spaces in a 4-space file)
    if language == "python" and "unexpected indent" in msg and reported >= 2:
        prev = reported - 1
        while prev >= 1 and not lines[prev - 1].strip():
            prev -= 1
        if prev >= 1 and indent_of(lines[prev - 1]) % _indent_unit(lines) != 0:
            ordered = [prev, reported]

    if not ordered and language != "python" and _MISSING_TERMINATOR.search(root.message or ""):
        above = [k for k in range(reported - 1, max(0, reported - 4), -1)
                 if lacks_terminator(lines, k, language)]
        reported_lacks = lacks_terminator(lines, reported, language)

        token_starts_line = (
            root.column is None
            or (reported <= n and root.column <= _first_nonspace_column(lines[reported - 1]))
        )
        if token_starts_line and above:
            # The statement before the reported token is the one missing ';'
            ordered = above + ([reported] if reported_lacks else [])
        elif reported_lacks:
            ordered = [reported] + above
        else:
            ordered = above

    for k in (reported, reported - 1):
        if _nonblank(lines, k) and k not in ordered:
            ordered.append(k)
    if reported not in ordered:
        ordered.append(reported)

    if not ordered:
        ordered = [reported]
    return ordered
