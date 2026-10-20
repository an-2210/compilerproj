"""Diagnostic Collector: manages compiler execution, limits, and diagnostic categorization."""

import logging
import re
from typing import Dict, List, Optional, Tuple

from src.data_engine.language_adapters import (
    LanguageAdapter,
    CompilationResult,
    get_adapter,
)
from src.data_engine.schemas import (
    Language,
    ErrorInfo,
    ErrorCategory,
    DiagnosticMessage,
    DiagnosticSeverity,
)

logger = logging.getLogger(__name__)


def categorize_diagnostic_message(message: str) -> Tuple[str, str]:
    """Map raw diagnostic message to error category and subcategory."""
    msg = message.lower()

    # Syntax / Delimiter / Punctuation
    if "expected ';'" in msg or "missing ';'" in msg:
        return (ErrorCategory.DELIMITER_PUNCTUATION.value, "missing_semicolon")
    if "expected" in msg and any(tok in msg for tok in ("')'", "']'", "'}'", "':'", "','")):
        return (ErrorCategory.DELIMITER_PUNCTUATION.value, "missing_delimiter")
    if "unmatched" in msg or "closing" in msg or "mismatched" in msg:
        return (ErrorCategory.DELIMITER_PUNCTUATION.value, "unmatched_bracket")

    # Python Indentation / Syntax
    if "indent" in msg or "unindent" in msg:
        return (ErrorCategory.INDENTATION_BLOCK.value, "indentation_error")
    if "expected an indented block" in msg:
        return (ErrorCategory.INDENTATION_BLOCK.value, "missing_indentation")

    # Declaration / Identifier
    if "undeclared" in msg or "not declared" in msg or "has not been declared" in msg:
        return (ErrorCategory.DECLARATION_IDENTIFIER.value, "undeclared_identifier")
    if "unknown type" in msg or "expected type" in msg:
        return (ErrorCategory.DECLARATION_IDENTIFIER.value, "invalid_type_declaration")
    if "redefinition" in msg or "redeclaration" in msg:
        return (ErrorCategory.DECLARATION_IDENTIFIER.value, "redefinition")

    # Function call / Argument
    if "too few arguments" in msg or "too many arguments" in msg:
        return (ErrorCategory.FUNCTION_CALL_ARGUMENT.value, "argument_count_mismatch")
    if "cannot convert" in msg or "incompatible type" in msg or "invalid conversion" in msg:
        return (ErrorCategory.TYPE_ERROR.value, "type_mismatch")

    # Expression / Operator
    if "expected expression" in msg or "invalid operands" in msg:
        return (ErrorCategory.EXPRESSION_OPERATOR.value, "invalid_expression_operator")
    if "lvalue required" in msg or "assignment to" in msg:
        return (ErrorCategory.EXPRESSION_OPERATOR.value, "invalid_assignment_target")

    # General syntax
    if "syntax" in msg or "parse error" in msg or "expected" in msg:
        return (ErrorCategory.SYNTAX.value, "syntax_error")

    return (ErrorCategory.UNKNOWN.value, "general_error")


class DiagnosticCollector:
    """Orchestrates diagnostic collection and normalization for source code."""

    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = timeout_seconds
        self._adapters: Dict[str, LanguageAdapter] = {}

    def get_adapter_for(self, language: Language | str) -> LanguageAdapter:
        lang_key = language.value if isinstance(language, Language) else str(language).lower()
        if lang_key not in self._adapters:
            self._adapters[lang_key] = get_adapter(lang_key)
        return self._adapters[lang_key]

    def compile_and_collect(
        self,
        source: str,
        language: Language | str,
        extra_flags: Optional[List[str]] = None,
    ) -> CompilationResult:
        """Execute compiler/parser safely and extract diagnostics."""
        adapter = self.get_adapter_for(language)
        return adapter.compile_or_parse(
            source=source,
            timeout_seconds=self.timeout_seconds,
            extra_flags=extra_flags,
        )

    def extract_error_info(
        self,
        compilation_result: CompilationResult,
        default_category: Optional[str] = None,
        default_subcategory: Optional[str] = None,
    ) -> ErrorInfo:
        """Create structured ErrorInfo from CompilationResult."""
        if compilation_result.success:
            return ErrorInfo(
                category=ErrorCategory.NONE.value,
                subcategory="none",
                compiler=compilation_result.tool_name,
                compiler_version=compilation_result.tool_version,
                exit_code=0,
                diagnostics=[],
                raw_output=compilation_result.stdout or "",
                execution_duration_ms=compilation_result.duration_ms,
            )

        # Categorize based on primary diagnostic message if available
        primary_msg = ""
        if compilation_result.diagnostics:
            primary_msg = compilation_result.diagnostics[0].message
        elif compilation_result.stderr:
            primary_msg = compilation_result.stderr.splitlines()[0]

        cat, subcat = categorize_diagnostic_message(primary_msg)
        if default_category and cat == ErrorCategory.UNKNOWN.value:
            cat = default_category
        if default_subcategory and subcat == "general_error":
            subcat = default_subcategory

        return compilation_result.to_error_info(category=cat, subcategory=subcat)
