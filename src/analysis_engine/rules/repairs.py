"""Rule proposals for rule-based repair.

Each rule reads an ErrorContext and yields Proposals. A Proposal is one or more
line edits; the engine applies them and checks the result with the detector.
Rules are ordered by how specific their message pattern is.
"""

import builtins
import difflib
import re
import sys
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Tuple

from src.analysis_engine.contracts import ErrorContext
from src.analysis_engine.context.c_context import function_spans
from src.analysis_engine.context.line_mapping import lacks_terminator
from src.analysis_engine.context.scanner import OPENERS, code_part, indent_of, sanitize


# (1-indexed line number, replacement text for that line; may contain "\n")
Edit = Tuple[int, str]


@dataclass
class Proposal:
    rule_id: str
    description: str
    edits: List[Edit]
    confidence: float


RuleFn = Callable[[ErrorContext], Iterator[Proposal]]

_MISSING_TERMINATOR = re.compile(r"expected [^\n]*';'", re.IGNORECASE)
_PY_HEADER = re.compile(r"\s*(if|elif|else|for|while|def|class|try|except|finally|with|async)\b")
_C_HEADER_FOR_SYMBOL = {
    **{s: "stdio.h" for s in ("printf", "fprintf", "sprintf", "snprintf", "scanf", "fscanf",
                              "sscanf", "puts", "fputs", "fgets", "fopen", "fclose", "fgetc",
                              "getchar", "putchar", "fread", "fwrite", "perror", "FILE", "EOF")},
    **{s: "stdlib.h" for s in ("malloc", "calloc", "realloc", "free", "exit", "abort", "atoi",
                               "atof", "rand", "srand", "abs", "qsort", "strtol")},
    **{s: "string.h" for s in ("strlen", "strcpy", "strncpy", "strcmp", "strncmp", "strcat",
                               "strchr", "strstr", "memcpy", "memset", "memmove", "memcmp")},
    **{s: "math.h" for s in ("sqrt", "pow", "sin", "cos", "tan", "fabs", "floor", "ceil", "log", "exp")},
    **{s: "stdbool.h" for s in ("bool", "true", "false")},
    **{s: "limits.h" for s in ("INT_MAX", "INT_MIN")},
    **{s: "ctype.h" for s in ("isalpha", "isdigit", "isspace", "toupper", "tolower")},
    **{s: "stdint.h" for s in ("uint8_t", "uint16_t", "uint32_t", "int32_t", "uint64_t", "int64_t")},
}
_BINARY_OPERATORS = ("<=", ">=", "==", "!=", "&&", "||", "<", ">", "+", "-", "*", "/", "%", "&", "|", "^")
_OPERATOR_CHARS = "=+-*/%<>!&|^"


def _lines(ctx: ErrorContext) -> List[str]:
    return ctx.code.split("\n")


def _message(ctx: ErrorContext) -> str:
    return ctx.root.message or ""


def _col0(ctx: ErrorContext, line_no: int, line: str) -> int:
    """0-indexed insertion column: the reported column on the reported line, else end of code."""
    if line_no == ctx.reported_line and ctx.root.column:
        return min(ctx.root.column - 1, len(line))
    return len(code_part(line, ctx.language).rstrip())


def _append_before_comment(line: str, suffix: str, language: str) -> str:
    code = code_part(line, language).rstrip()
    return code + suffix + line[len(code):]


def _replace_word(line: str, old: str, new: str) -> str:
    return re.sub(rf"\b{re.escape(old)}\b", new, line, count=1)


def apply_edits(code: str, edits: List[Edit]) -> str:
    lines = code.split("\n")
    for line_no, text in edits:
        lines[line_no - 1] = text
    return "\n".join(lines)


# ---------------------------------------------------------------- Python layout

def py_missing_colon(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language != "python" or "expected ':'" not in _message(ctx):
        return
    lines = _lines(ctx)
    for rank, k in enumerate(ctx.candidate_lines[:2]):
        line = lines[k - 1]
        code = code_part(line, "python").rstrip()
        if code.endswith(":") or not _PY_HEADER.match(code):
            continue
        yield Proposal("py_missing_colon", f"add ':' to end of line {k}",
                       [(k, _append_before_comment(line, ":", "python"))],
                       0.9 if rank == 0 else 0.6)


def _previous_nonblank(lines: List[str], line_no: int) -> Optional[int]:
    for k in range(line_no - 1, 0, -1):
        if lines[k - 1].strip() and not lines[k - 1].lstrip().startswith("#"):
            return k
    return None


def py_expected_indent(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language != "python" or not _message(ctx).startswith("expected an indented block"):
        return
    lines = _lines(ctx)
    k = ctx.reported_line
    header = _previous_nonblank(lines, k)
    if header is None:
        return
    header_code = code_part(lines[header - 1], "python").rstrip()
    if not header_code.endswith(":"):
        return
    target = indent_of(lines[header - 1]) + 4
    yield Proposal("py_expected_indent", f"indent line {k} to {target} spaces",
                   [(k, " " * target + lines[k - 1].lstrip())], 0.8)


def py_unexpected_indent(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language != "python" or "unexpected indent" not in _message(ctx):
        return
    lines = _lines(ctx)
    k = ctx.reported_line
    levels = sorted(set(ctx.enclosing_indents), reverse=True)
    for rank, level in enumerate(levels[:3]):
        if level == ctx.indent_of_line:
            continue
        yield Proposal("py_unexpected_indent", f"dedent line {k} to {level} spaces",
                       [(k, " " * level + lines[k - 1].lstrip())],
                       0.6 if rank == 0 else 0.4)


def py_unindent_mismatch(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language != "python" or "unindent does not match" not in _message(ctx):
        return
    lines = _lines(ctx)
    k = ctx.reported_line
    current = ctx.indent_of_line or 0

    # Targets in priority order: body of the header above (header + 4) first, then the
    # open block levels, nearest to the current indent first (deeper level on a tie)
    targets: List[Tuple[int, float]] = []
    prev = _previous_nonblank(lines, k)
    if prev is not None and code_part(lines[prev - 1], "python").rstrip().endswith(":"):
        targets.append((indent_of(lines[prev - 1]) + 4, 0.85))
    levels = sorted(set(ctx.enclosing_indents), key=lambda lvl: (abs(lvl - current), -lvl))
    for rank, level in enumerate(levels):
        targets.append((level, 0.6 - 0.05 * rank))

    seen = set()
    for level, confidence in targets:
        if level in seen or level == current:
            continue
        seen.add(level)
        yield Proposal("py_unindent_mismatch", f"align line {k} to indent {level}",
                       [(k, " " * level + lines[k - 1].lstrip())], max(confidence, 0.05))


# ------------------------------------------------------------- C / C++ and Python punctuation

def c_missing_terminator(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language == "python" or not _MISSING_TERMINATOR.search(_message(ctx)):
        return
    lines = _lines(ctx)
    for rank, k in enumerate(ctx.candidate_lines[:2]):
        line = lines[k - 1]
        code = code_part(line, ctx.language).rstrip()
        confidence = 0.9 if rank == 0 else 0.6
        if lacks_terminator(lines, k, ctx.language):
            yield Proposal("c_missing_terminator", f"add ';' to end of line {k}",
                           [(k, _append_before_comment(line, ";", ctx.language))], confidence)
        elif code.endswith("}") and re.match(r"\s*(struct|class|union|enum|typedef)\b", code):
            # Type definitions need a ';' after their closing brace
            yield Proposal("c_missing_terminator", f"add ';' after closing brace on line {k}",
                           [(k, _append_before_comment(line, ";", ctx.language))], confidence - 0.2)


def bracket_insert(ctx: ErrorContext) -> Iterator[Proposal]:
    """Insert or substitute the closer the parser expected."""
    lines = _lines(ctx)
    msg = _message(ctx)
    expected = None
    if (m := re.search(r"expected '([)\]}])'", msg)):
        expected = m.group(1)
    elif (m := re.search(r"'([(\[{])' was never closed", msg)):
        expected = OPENERS[m.group(1)]
    elif "at end of input" in msg and ("declaration or statement" in msg or "'}'" in msg):
        expected = "}"

    if expected is None:
        return

    if ctx.unclosed_at_eof and ("end of input" in msg or "never closed" in msg):
        closers = "".join(OPENERS[b.char] for b in reversed(ctx.unclosed_at_eof))
        last = len(lines)
        suffix = "" if lines[last - 1].strip() == "" else "\n"
        yield Proposal("bracket_eof", f"append '{closers}' at end of file",
                       [(last, lines[last - 1] + suffix + closers)], 0.6)

    if "end of input" in msg:
        # Reported at EOF, so the missing closer is not at the reported column
        return

    if "never closed" in msg:
        for rank, k in enumerate(ctx.candidate_lines[:1]):
            line = lines[k - 1]
            yield Proposal("bracket_insert", f"append '{expected}' to end of line {k}",
                           [(k, _append_before_comment(line, expected, ctx.language))],
                           0.6 if rank == 0 else 0.4)
        return

    for rank, k in enumerate(ctx.candidate_lines[:2]):
        line = lines[k - 1]
        c0 = _col0(ctx, k, line)
        at = line[c0:c0 + 1]
        base = 0.7 if rank == 0 else 0.45
        if at.isalnum() or at == "_":
            # A name at the error column usually means a missing comma, not a closer
            base *= 0.6
        if at in (")", "]", "}") and at != expected:
            # Wrong closer present (for example ')' where ']' was expected): substitute
            yield Proposal("bracket_substitute", f"replace '{at}' with '{expected}' on line {k}",
                           [(k, line[:c0] + expected + line[c0 + 1:])], base + 0.05)
        yield Proposal("bracket_insert", f"insert '{expected}' on line {k}",
                       [(k, line[:c0] + expected + line[c0:])], base)


def closing_brace_restore(ctx: ErrorContext) -> Iterator[Proposal]:
    """A '}' that was blanked out, leaving an empty line where the brace used to be.

    Only used when the file ends with a block still open. The most likely line is a
    blank line at column 0 after the last statement (end of a top-level function).
    """
    if ctx.language == "python" or not re.search(r"end of input|expected '\}'", _message(ctx)):
        return
    openers = [b for b in ctx.unclosed_at_eof if b.char == "{"]
    if not openers:
        return
    lines = _lines(ctx)
    opener_line = openers[-1].line
    yielded = 0
    for k in range(opener_line + 1, len(lines) + 1):
        if lines[k - 1].strip():
            continue
        following = next((j for j in range(k + 1, len(lines) + 1) if lines[j - 1].strip()), None)
        prev = _previous_nonblank(lines, k)
        if prev is None or prev <= opener_line:
            continue
        at_top_level = following is None or not lines[following - 1][:1].isspace()
        confidence = 0.8 if at_top_level else 0.35
        yield Proposal("closing_brace_restore", f"fill empty line {k} with '}}'", [(k, "}")], confidence)
        yielded += 1
        if yielded >= 3:
            break


def closer_delete(ctx: ErrorContext) -> Iterator[Proposal]:
    """Delete a closing bracket that has no opener, or that the parser did not expect."""
    msg = _message(ctx)
    m = re.search(r"unmatched '([)\]}])'", msg) or re.search(r"before '([)\]}])'", msg)
    if not m:
        return
    lines = _lines(ctx)
    k = ctx.reported_line
    line = lines[k - 1]
    c0 = _col0(ctx, k, line)
    if line[c0:c0 + 1] == m.group(1):
        yield Proposal("closer_delete", f"delete '{m.group(1)}' on line {k}",
                       [(k, line[:c0] + line[c0 + 1:])], 0.5)


def extra_semicolon(ctx: ErrorContext) -> Iterator[Proposal]:
    msg = _message(ctx)
    if not re.match(r"expected (expression|unqualified-id)", msg):
        return
    lines = _lines(ctx)
    k = ctx.reported_line
    line = lines[k - 1]
    c0 = _col0(ctx, k, line)
    if line[c0:c0 + 1] == ";":
        yield Proposal("extra_semicolon", f"delete stray ';' on line {k}",
                       [(k, line[:c0] + line[c0 + 1:])], 0.6)


def insert_comma(ctx: ErrorContext) -> Iterator[Proposal]:
    """Two list items with no comma between them."""
    if ctx.language == "python":
        return
    msg = _message(ctx)
    lines = _lines(ctx)
    k = ctx.reported_line
    line = lines[k - 1]
    c0 = _col0(ctx, k, line)
    # gcc says "expected ',' ... before 'x'"; clang says "expected ')'" at the start of 'x'
    names_next_item = c0 < len(line) and (line[c0].isalnum() or line[c0] == "_")
    wants_comma = (
        re.search(r"expected [^\n]*','", msg)
        or (re.search(r"expected '\)' before", msg) and names_next_item)
        or (re.search(r"expected '\)'$", msg) and names_next_item)
        or re.search(r"expected '\}' before", msg)
    )
    if not wants_comma:
        return
    yield Proposal("insert_comma", f"insert ',' before column {c0 + 1} on line {k}",
                   [(k, line[:c0] + "," + line[c0:])], 0.55)


def operator_removal(ctx: ErrorContext) -> Iterator[Proposal]:
    """An injected operator next to a real one: remove the injected one.

    `j = < n` (injected '=' on the left) and `j + * 1` (injected '*' at the column) are
    both produced by operator mutations. A plain '=' is never a binary operator inside an
    expression, so a left-hand '=' is the injected one; otherwise the column operator is.
    """
    if not ctx.root.column:
        return
    lines = _lines(ctx)
    k = ctx.reported_line
    line = lines[k - 1]
    c0 = ctx.root.column - 1
    op = next((o for o in _BINARY_OPERATORS if line[c0:c0 + len(o)] == o), None)
    if op is None:
        return

    # Operator run immediately to the left of the column, skipping spaces
    j = c0
    while j > 0 and line[j - 1] == " ":
        j -= 1
    end_left = j
    while j > 0 and line[j - 1] in _OPERATOR_CHARS:
        j -= 1
    left_run = line[j:end_left]

    if left_run and left_run.rstrip("=") == "" and left_run.endswith("="):
        yield Proposal("operator_removal", f"remove stray '{left_run.strip()}' before '{op}' on line {k}",
                       [(k, line[:j] + line[c0:])], 0.7)
    # Remove the operator at the column, plus one following space
    trailing = 1 if line[c0 + len(op):c0 + len(op) + 1] == " " else 0
    yield Proposal("operator_removal", f"remove stray '{op}' on line {k}",
                   [(k, line[:c0] + line[c0 + len(op) + trailing:])], 0.65)
    if left_run and not left_run.endswith("="):
        yield Proposal("operator_removal", f"remove stray '{left_run.strip()}' before '{op}' on line {k}",
                       [(k, line[:j] + line[c0:])], 0.3)

def stray_assignment_removal(ctx: ErrorContext) -> Iterator[Proposal]:
    """`x = 100 = 0`: an operand and '=' injected in front of the real value."""
    if ctx.language == "python" or not re.search(r"lvalue required|not assignable", _message(ctx)):
        return
    lines = _lines(ctx)
    for rank, k in enumerate(ctx.candidate_lines[:2]):
        line = lines[k - 1]
        code = code_part(line, ctx.language)
        for match in list(re.finditer(r"=\s*[\w.]+\s*=(?!=)\s*", code))[:3]:
            new_line = line[:match.start()] + "= " + line[match.end():]
            yield Proposal("stray_assignment_removal",
                           f"remove stray '{match.group(0).split('=', 1)[1].strip()}' assignment on line {k}",
                           [(k, new_line)], 0.75 if rank == 0 else 0.5)


def equality_assignment(ctx: ErrorContext) -> Iterator[Proposal]:
    """'=' where '==' was meant, in a condition."""
    msg = _message(ctx)
    if not re.search(r"lvalue required|not assignable|Maybe you meant '=='|instead of '='|cannot assign to", msg):
        return
    lines = _lines(ctx)
    for rank, k in enumerate(ctx.candidate_lines[:2]):
        line = lines[k - 1]
        code = code_part(line, ctx.language)
        in_condition = bool(re.match(r"\s*(if|while|elif|assert)\b", code)) or "(" in code
        found = 0
        for match in re.finditer(r"(?<![=!<>+\-*/%&|^])=(?!=)", code):
            idx = match.start()
            new_line = line[:idx] + "==" + line[idx + 1:]
            yield Proposal("equality_assignment", f"replace '=' with '==' on line {k}",
                           [(k, new_line)],
                           (0.8 if in_condition else 0.5) - 0.2 * rank)
            found += 1
            if found >= 3:
                break


def _call_spans(line: str) -> List[Tuple[str, int, int, List[Tuple[int, int]]]]:
    """Calls `name(...)` on a line as (name, open_index, close_index, argument_spans).

    Argument spans are (start, end) indices into `line`, split at top-level commas.
    """
    calls = []
    for match in re.finditer(r"([A-Za-z_]\w*)\s*\(", line):
        open_idx = match.end() - 1
        depth = 0
        args: List[Tuple[int, int]] = []
        start = open_idx + 1
        close_idx = None
        for idx in range(open_idx, len(line)):
            ch = line[idx]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    args.append((start, idx))
                    close_idx = idx
                    break
            elif ch == "," and depth == 1:
                args.append((start, idx))
                start = idx + 1
        if close_idx is not None:
            calls.append((match.group(1), open_idx, close_idx, args))
    return calls


def extra_argument_removal(ctx: ErrorContext) -> Iterator[Proposal]:
    """A call with more arguments than the function takes: drop one argument."""
    msg = _message(ctx)
    if "too many arguments" not in msg:
        return
    counted = re.search(r"expected (\d+), have (\d+)", msg)
    if counted:
        expected = int(counted.group(1))
    else:
        # C++ names the signature instead of counting: count its parameters
        signature = re.search(r"\(([^()]*)\)", msg)
        if not signature:
            return
        params = [p.strip() for p in signature.group(1).split(",") if p.strip()]
        expected = 0 if params == ["void"] else len(params)

    lines = _lines(ctx)
    k = ctx.reported_line
    line = lines[k - 1]
    for name, _open_idx, close_idx, args in _call_spans(line):
        if len(args) <= expected or (counted and len(args) != int(counted.group(2))):
            continue
        texts = [line[a:b].strip() for a, b in args]
        for rank, drop in enumerate(reversed(range(len(texts)))):
            if rank >= 3:
                break
            kept = [t for i, t in enumerate(texts) if i != drop]
            start = args[0][0]
            rebuilt = line[:start] + ", ".join(kept) + line[close_idx:]
            yield Proposal("extra_argument_removal",
                           f"drop argument {drop + 1} of call to '{name}' on line {k}",
                           [(k, rebuilt)], 0.6 if rank == 0 else 0.3)


def identifier_typo(ctx: ErrorContext) -> Iterator[Proposal]:
    msg = _message(ctx)
    m = (re.search(r"'([A-Za-z_]\w*)' undeclared", msg)
         or re.search(r"undeclared identifier '([A-Za-z_]\w*)'", msg)
         or re.search(r"name '([A-Za-z_]\w*)' is not defined", msg)
         or re.search(r"call to undeclared function '([A-Za-z_]\w*)'", msg)
         or re.search(r"undefined name '([A-Za-z_]\w*)'", msg))
    if not m:
        return
    name = m.group(1)
    lines = _lines(ctx)
    k = ctx.reported_line
    line = lines[k - 1]
    if not re.search(rf"\b{re.escape(name)}\b", line):
        return

    pool = [s for s in ctx.symbols if s != name]
    if ctx.language == "python":
        pool += [b for b in dir(builtins) if not b.startswith("_")]
    # Rank by similarity; the compile check later rejects renames to undeclared names
    ranked = sorted(
        {m for m in difflib.get_close_matches(name, pool, n=5, cutoff=0.35)},
        key=lambda m: -difflib.SequenceMatcher(None, name, m).ratio(),
    )
    for match in ranked[:3]:
        ratio = difflib.SequenceMatcher(None, name, match).ratio()
        yield Proposal("identifier_typo", f"rename '{name}' to '{match}' on line {k}",
                       [(k, _replace_word(line, name, match))], round(0.3 + 0.5 * ratio, 3))


def c_unnamed_char_parameter(ctx: ErrorContext) -> Iterator[Proposal]:
    """Name one unnamed string parameter only when compiler and body uses agree.

    This deliberately covers a single-line, single-parameter C definition. Multiple
    missing names or other undeclared identifiers make the inference ambiguous.
    """
    if ctx.language != "c":
        return
    sanitized = sanitize(ctx.code, "c")
    clean_lines = sanitized.split("\n")
    lines = _lines(ctx)
    errors = [d for d in ctx.diagnostics if d.severity == "error"]
    # GCC can emit ASCII or typographic quotes; its Linux build may also omit
    # the separate "parameter name omitted" diagnostic after an earlier error.
    messages = [(d, d.message.replace("‘", "'").replace("’", "'")) for d in errors]
    for function, start, end, _params in function_spans(sanitized):
        header = clean_lines[start - 1]
        if not re.fullmatch(
            rf"\s*(?:[A-Za-z_]\w*\s+)+\**\s*{re.escape(function)}\s*"
            r"\(\s*const\s+char\s*\*\s*\)\s*\{\s*", header,
        ):
            continue
        body = "\n".join(clean_lines[start:end])
        names = set()
        for diag, message in messages:
            if diag.line is None or not start < diag.line <= end:
                continue
            match = (re.search(r"'([A-Za-z_]\w*)' undeclared", message)
                     or re.search(r"undeclared identifier '([A-Za-z_]\w*)'", message))
            if match and match.group(1) not in _C_HEADER_FOR_SYMBOL:
                names.add(match.group(1))
        if len(names) != 1:
            continue
        name = names.pop()
        if name in ctx.symbols or len(re.findall(rf"\b{re.escape(name)}\b", body)) < 2:
            continue
        pointer = re.search(r"const\s+char\s*\*", header)
        if pointer is None:
            continue
        changed_header = lines[start - 1][:pointer.end()] + name + lines[start - 1][pointer.end():]
        edits = [(start, changed_header)]
        headers = []
        error_messages = [message for _diag, message in messages]
        if "stdbool.h" not in ctx.imports and any(
            "unknown type name 'bool'" in m or re.search(r"'(true|false)' undeclared", m)
            for m in error_messages
        ):
            headers.append("#include <stdbool.h>")
        if "string.h" not in ctx.imports and any(
            "implicit declaration of function 'strlen'" in m for m in error_messages
        ):
            headers.append("#include <string.h>")
        if headers:
            prefix = "\n".join(headers) + "\n"
            if start == 1:
                edits = [(1, prefix + changed_header)]
            else:
                edits.append((1, prefix + lines[0]))
        description = f"name unnamed const char * parameter '{name}' from repeated body uses"
        if headers:
            description += " and include compiler-indicated headers"
        yield Proposal("c_unnamed_char_parameter", description, edits, 0.95)


# ------------------------------------------------------------- Imports and headers

def missing_import_python(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language != "python":
        return
    m = (re.search(r"name '([A-Za-z_]\w*)' is not defined", _message(ctx))
         or re.search(r"undefined name '([A-Za-z_]\w*)'", _message(ctx)))
    if not m or m.group(1) not in sys.stdlib_module_names or m.group(1) in ctx.imports:
        return
    lines = _lines(ctx)
    # An exact stdlib module name is stronger evidence than a similar-looking rename
    yield Proposal("missing_import_python", f"add 'import {m.group(1)}' at top of file",
                   [(1, f"import {m.group(1)}\n{lines[0]}")], 0.75)


def missing_include_c(ctx: ErrorContext) -> Iterator[Proposal]:
    if ctx.language == "python":
        return
    msg = _message(ctx)
    m = (re.search(r"implicit declaration of function '(\w+)'", msg)
         or re.search(r"undeclared (?:library )?function '(\w+)'", msg)
         or re.search(r"'(\w+)' undeclared", msg)
         or re.search(r"undeclared identifier '(\w+)'", msg))
    if not m or m.group(1) not in _C_HEADER_FOR_SYMBOL:
        return
    header = _C_HEADER_FOR_SYMBOL[m.group(1)]
    if header in ctx.imports:
        return
    lines = _lines(ctx)
    include_line = f"#include <{header}>"
    include_lines = [i + 1 for i, text in enumerate(lines) if text.lstrip().startswith("#include")]
    if include_lines:
        last = include_lines[-1]
        edit = (last, lines[last - 1] + "\n" + include_line)
    else:
        edit = (1, include_line + "\n" + lines[0])
    yield Proposal("missing_include_c", f"add '#include <{header}>' for '{m.group(1)}'",
                   [edit], 0.7)


RULES: List[RuleFn] = [
    py_missing_colon,
    py_expected_indent,
    py_unexpected_indent,
    py_unindent_mismatch,
    c_missing_terminator,
    bracket_insert,
    closer_delete,
    stray_assignment_removal,
    equality_assignment,
    operator_removal,
    extra_semicolon,
    insert_comma,
    extra_argument_removal,
    closing_brace_restore,
    c_unnamed_char_parameter,
    identifier_typo,
    missing_import_python,
    missing_include_c,
]
