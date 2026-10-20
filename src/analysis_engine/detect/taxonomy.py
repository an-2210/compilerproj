"""Compiler message -> (category, subcategory), using the Data Engineer's taxonomy.

The Data Engineer's `categorize_diagnostic_message` covers the common gcc wording. This
module adds the messages it misses (clang wording, "never closed", "lvalue required",
argument-count errors). Rules are ordered; the first match wins. Anything unmatched
falls back to the Data Engineer's function, so the two layers never disagree on
messages that only the Data Engineer knows.

Note: several compiler messages fit more than one subcategory (for example
"expected expression before ';'" is an extra semicolon or a missing operand). The
rules pick the most common reading, so this is a best-effort mapping.
"""

import re
from typing import List, Optional, Tuple

from src.data_engine.diagnostic_collector import categorize_diagnostic_message


# (pattern, category, subcategory), checked in order
_RULES: List[Tuple[re.Pattern, str, str]] = [
    # Brackets and braces
    (re.compile(r"'\{' was never closed|expected '\}'|expected '\}' at end of input|"
                r"expected declaration or statement at end of input", re.I),
     "delimiter_punctuation", "missing_brace"),
    (re.compile(r"(?:'\(' was never closed|expected '\)'|unmatched '\)'|"
                r"closing parenthesis '\)' does not match|\)' does not match)", re.I),
     "delimiter_punctuation", "unmatched_parenthesis"),
    (re.compile(r"(?:'\[' was never closed|expected '\]'|unmatched '\]'|extraneous '\]'|"
                r"closing parenthesis '\]' does not match|\]' does not match)", re.I),
     "delimiter_punctuation", "unmatched_bracket"),

    # Argument counts
    (re.compile(r"too many arguments", re.I), "function_call_argument", "too_many_arguments"),
    (re.compile(r"too few arguments", re.I), "function_call_argument", "too_few_arguments"),

    # Assignment and operators
    (re.compile(r"lvalue required|not assignable|Maybe you meant '=='|instead of '='|"
                r"cannot assign to", re.I),
     "expression_operator", "invalid_assignment_target"),
    (re.compile(r"invalid type argument of unary|indirection requires pointer|invalid operands", re.I),
     "expression_operator", "invalid_expression_operator"),

    # Stray or missing punctuation
    (re.compile(r"expected [^\n]*';' before|expected expression before ';'|"
                r"expected primary-expression before ';'|expected unqualified-id before ';'", re.I),
     "delimiter_punctuation", "extra_semicolon"),
    (re.compile(r"expected ';' at end of declaration|expected initializer before", re.I),
     "delimiter_punctuation", "missing_semicolon"),
    (re.compile(r"missing ',' between|expected '\}' before numeric|"
                r"expected ';', ',' or '\)' before|expected ',' or '\.\.\.' before", re.I),
     "delimiter_punctuation", "missing_comma"),

    # Comparison operators sitting where an operand should be
    (re.compile(r"expected (?:primary-)?expression before '(?:<|>|<=|>=|==|!=)' token|"
                r"expected (?:primary-)?expression before '(?:<|>|<=|>=|==|!=)'", re.I),
     "expression_operator", "invalid_comparison"),

    # Names
    (re.compile(r"undeclared|not defined|undefined name", re.I),
     "declaration_identifier", "undeclared_identifier"),

    # Python layout
    (re.compile(r"expected an indented block", re.I), "indentation_block", "missing_indentation"),
    (re.compile(r"unexpected indent|unindent does not match", re.I), "indentation_block", "indentation_error"),
]


def classify_message(message: str) -> Tuple[str, str]:
    for pattern, category, subcategory in _RULES:
        if pattern.search(message or ""):
            return category, subcategory
    return categorize_diagnostic_message(message or "")
