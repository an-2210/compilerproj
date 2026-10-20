"""Lexical helpers shared by the Python and C/C++ context builders.

These work on broken code. They never parse, so a file that fails to compile still
yields brackets, indentation levels and comment-free text.
"""

from typing import Dict, List, Optional, Tuple

from src.analysis_engine.contracts import BracketInfo


OPENERS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {v: k for k, v in OPENERS.items()}


def sanitize(text: str, language: str) -> str:
    """Blank out comments and string/char literal contents, keeping positions.

    Every character that is not code becomes a space, newlines are kept, so line and
    column numbers in the result match the original text exactly.
    """
    out = []
    i = 0
    n = len(text)
    is_python = language == "python"

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if is_python and ch == "#":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if not is_python and ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if not is_python and ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for c in text[i:end]:
                out.append("\n" if c == "\n" else " ")
            i = end
            continue

        if ch in ("'", '"'):
            triple = is_python and text[i:i + 3] == ch * 3
            quote = ch * 3 if triple else ch
            out.append(" " * len(quote))
            i += len(quote)
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    # Escape sequence: two source characters, two output characters
                    out.append(" ")
                    out.append("\n" if text[i + 1] == "\n" else " ")
                    i += 2
                    continue
                if text.startswith(quote, i):
                    out.append(" " * len(quote))
                    i += len(quote)
                    break
                if text[i] == "\n" and not triple:
                    # Unterminated literal: stop at end of line so one bad quote
                    # does not blank the rest of the file
                    break
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def scan_brackets(
    sanitized: str,
    stop_line: int,
) -> Tuple[List[BracketInfo], List[BracketInfo]]:
    """Track bracket nesting over sanitized text.

    Returns (open_at_start_of_stop_line, unclosed_at_eof). A closer that does not
    match the innermost opener closes the nearest matching opener below it, and any
    openers skipped over are dropped as unclosed.
    """
    stack: List[BracketInfo] = []
    open_at_stop: Optional[List[BracketInfo]] = None
    line = 1
    col = 0

    for ch in sanitized:
        if line == stop_line and col == 0 and open_at_stop is None:
            open_at_stop = list(stack)
        if ch == "\n":
            line += 1
            col = 0
            continue
        col += 1
        if ch in OPENERS:
            stack.append(BracketInfo(char=ch, line=line, column=col))
        elif ch in CLOSERS:
            opener = CLOSERS[ch]
            for idx in range(len(stack) - 1, -1, -1):
                if stack[idx].char == opener:
                    del stack[idx:]
                    break

    if open_at_stop is None:
        open_at_stop = list(stack)
    return open_at_stop, stack


def indentation_stack(lines: List[str], before_line: int) -> List[int]:
    """Indentation levels of the blocks open just before `before_line` (1-indexed).

    This mirrors the tokenizer: the stack starts at [0] and each new deeper level
    is pushed, while shallower lines pop back to a matching level.
    """
    stack = [0]
    for raw in lines[: max(before_line - 1, 0)]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        while len(stack) > 1 and stack[-1] > indent:
            stack.pop()
        if stack[-1] < indent:
            stack.append(indent)
    return stack


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def code_part(line: str, language: str) -> str:
    """The line without a trailing comment, respecting string literals."""
    in_str: Optional[str] = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in ("'", '"'):
            in_str = ch
        elif language == "python" and ch == "#":
            return line[:i]
        elif language != "python" and line.startswith(("//", "/*"), i):
            return line[:i]
        i += 1
    return line
