"""Published contracts for the Analysis Engineer layer (DETECT, CONTEXT, RULE REPAIR).

These models are the hand-off format to the ML Engineer (repair model input) and
the Systems Engineer (verification and API). Field names are stable; add fields
rather than renaming them.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Severity = Literal["error", "warning", "note"]


class BracketInfo(BaseModel):
    """An opening bracket that is still unclosed at a given point in the source."""
    char: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class Diagnostic(BaseModel):
    """One normalized compiler or analyzer diagnostic."""
    message: str
    line: Optional[int] = Field(default=None, ge=1)
    column: Optional[int] = Field(default=None, ge=1)
    severity: Severity = "error"
    # Which tool produced it: "ast", "pyflakes", "mypy", "gcc", "g++", "pycparser"
    source: str
    # Tool-specific code when available, e.g. pyflakes "UndefinedName" or mypy "name-defined"
    code: Optional[str] = None
    # Taxonomy shared with the Data Engineer (see data_engine.diagnostic_collector)
    category: str = "unknown"
    subcategory: str = "general_error"
    raw: str = ""


class DetectionResult(BaseModel):
    """Output of the layered detector for one program."""
    language: str
    detected: bool
    # Layer that produced the first error: "ast", "pyflakes", "mypy", "gcc", "g++", "pycparser"
    layer: Optional[str] = None
    tool_version: Optional[str] = None
    diagnostics: List[Diagnostic] = Field(default_factory=list)
    # Root-most error after cascade suppression, or None for clean code
    root: Optional[Diagnostic] = None
    # Follow-on errors suppressed because they sit after the root syntax error
    cascades: List[Diagnostic] = Field(default_factory=list)


class ErrorContext(BaseModel):
    """Everything a repair model or rule needs to know about one detected error."""
    language: str
    code: str
    root: Diagnostic
    # The line the compiler reported, clamped to the file
    reported_line: int = Field(ge=1)
    # Ranked guesses for the line that actually holds the mistake, best first
    candidate_lines: List[int] = Field(default_factory=list)
    line_text: str = ""
    prev_line_text: Optional[str] = None
    next_line_text: Optional[str] = None
    # Innermost function or class containing the reported line
    enclosing_scope: Optional[str] = None
    # Names defined anywhere in the file (variables, functions, parameters)
    symbols: List[str] = Field(default_factory=list)
    # Imported modules (Python) or included headers (C/C++)
    imports: List[str] = Field(default_factory=list)
    # Brackets open at the start of the reported line
    open_brackets: List[BracketInfo] = Field(default_factory=list)
    # Brackets still open at end of file (in opening order)
    unclosed_at_eof: List[BracketInfo] = Field(default_factory=list)
    # Python only: indentation (in spaces) of the reported line, and the stack of
    # indentation levels that enclose it
    indent_of_line: Optional[int] = None
    enclosing_indents: List[int] = Field(default_factory=list)


class RepairCandidate(BaseModel):
    """One proposed patch, already checked against the compiler or parser."""
    rule_id: str
    description: str
    line: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    code: str
    # True when the patched program has no error-severity diagnostics
    compiles: bool


class RepairResult(BaseModel):
    """Output of rule-based repair for one ErrorContext."""
    rule_candidates: List[RepairCandidate] = Field(default_factory=list)
    # First candidate that compiles, else the highest-confidence candidate, else None
    chosen: Optional[RepairCandidate] = None
    applicable: bool = False
