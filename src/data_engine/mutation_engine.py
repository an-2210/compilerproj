"""Mutation engine implementing 15 distinct AST and token-based mutation operators.

Each operator declares supported languages, error categories, preconditions,
tracks target locations, and prevents accidental modifications inside strings or comments.
"""

import ast
import io
import random
import re
import tokenize
from typing import List, Optional, Tuple, NamedTuple

from src.data_engine.schemas import Language, ErrorCategory
from src.data_engine.mutation_registry import (
    MutationOperator,
    MutationResult,
    default_registry,
)


class SourceToken(NamedTuple):
    text: str
    start_line: int
    start_col: int
    start_offset: int
    end_offset: int
    token_type: str


def scan_c_cpp_tokens(source: str) -> List[SourceToken]:
    """Scan C/C++ source code into tokens, strictly excluding comments, strings, and preprocessor lines."""
    tokens: List[SourceToken] = []
    i = 0
    n = len(source)
    line = 1
    col = 1

    in_str = False
    in_char = False
    in_s_cmt = False
    in_m_cmt = False
    in_preproc = False

    while i < n:
        ch = source[i]
        c2 = source[i : i + 2] if i + 1 < n else ""

        # Preprocessor directive line handling (#include, #define, etc.)
        if col == 1 and ch == "#":
            in_preproc = True

        if in_s_cmt:
            if ch == "\n":
                in_s_cmt = False
                in_preproc = False
                line += 1
                col = 1
            else:
                col += 1
            i += 1
            continue

        if in_m_cmt:
            if c2 == "*/":
                in_m_cmt = False
                i += 2
                col += 2
            elif ch == "\n":
                line += 1
                col = 1
                i += 1
            else:
                col += 1
                i += 1
            continue

        if in_preproc:
            if ch == "\n":
                in_preproc = False
                line += 1
                col = 1
            else:
                col += 1
            i += 1
            continue

        if in_str:
            if ch == "\\" and i + 1 < n:
                i += 2
                col += 2
            elif ch == '"':
                in_str = False
                i += 1
                col += 1
            elif ch == "\n":
                line += 1
                col = 1
                i += 1
            else:
                col += 1
                i += 1
            continue

        if in_char:
            if ch == "\\" and i + 1 < n:
                i += 2
                col += 2
            elif ch == "'":
                in_char = False
                i += 1
                col += 1
            elif ch == "\n":
                line += 1
                col = 1
                i += 1
            else:
                col += 1
                i += 1
            continue

        # Check comment / string starts
        if c2 == "//":
            in_s_cmt = True
            i += 2
            col += 2
            continue
        if c2 == "/*":
            in_m_cmt = True
            i += 2
            col += 2
            continue
        if ch == '"':
            in_str = True
            i += 1
            col += 1
            continue
        if ch == "'":
            in_char = True
            i += 1
            col += 1
            continue

        if ch == "\n":
            line += 1
            col = 1
            i += 1
            continue

        # Check two-character operators
        two_char_ops = {"==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "->", "::"}
        if c2 in two_char_ops:
            tokens.append(SourceToken(c2, line, col, i, i + 2, "OPERATOR"))
            col += 2
            i += 2
            continue

        # Check single-character tokens
        single_ops = {"+", "-", "*", "/", "%", "=", "<", ">", "!", "&", "|", "^", "~", "?", ":"}
        single_delims = {";", ",", "(", ")", "[", "]", "{", "}"}

        if ch in single_ops:
            tokens.append(SourceToken(ch, line, col, i, i + 1, "OPERATOR"))
            col += 1
            i += 1
            continue
        elif ch in single_delims:
            tokens.append(SourceToken(ch, line, col, i, i + 1, "DELIMITER"))
            col += 1
            i += 1
            continue
        elif ch.isalnum() or ch == "_":
            start_off = i
            start_col = col
            val_chars = []
            while i < n and (source[i].isalnum() or source[i] == "_"):
                val_chars.append(source[i])
                i += 1
                col += 1
            val_str = "".join(val_chars)
            tok_type = "NUMBER" if val_str[0].isdigit() else "IDENTIFIER"
            tokens.append(SourceToken(val_str, line, start_col, start_off, i, tok_type))
            continue
        else:
            col += 1
            i += 1

    return tokens


def scan_python_tokens(source: str) -> List[SourceToken]:
    """Scan Python source code into tokens, excluding comments and docstrings."""
    tokens: List[SourceToken] = []
    try:
        readline = io.BytesIO(source.encode("utf-8")).readline
        for tok in tokenize.tokenize(readline):
            if tok.type in (tokenize.ENCODING, tokenize.ENDMARKER, tokenize.COMMENT, tokenize.NL):
                continue
            lines = source.splitlines(keepends=True)
            start_line, start_col = tok.start
            end_line, end_col = tok.end

            start_offset = sum(len(lines[l - 1]) for l in range(1, start_line)) + start_col
            end_offset = sum(len(lines[l - 1]) for l in range(1, end_line)) + end_col

            tok_type = tokenize.tok_name.get(tok.type, "TOKEN")
            tokens.append(SourceToken(tok.string, start_line, start_col + 1, start_offset, end_offset, tok_type))
    except Exception:
        pass
    return tokens


# =====================================================================
# OPERATOR 1: C_MISSING_SEMICOLON
# =====================================================================
class CMissingSemicolon(MutationOperator):
    operator_id = "C_MISSING_SEMICOLON"
    supported_languages = [Language.C, Language.CPP]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "missing_semicolon"
    description = "Removes a statement terminator semicolon outside comments and strings."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_c_cpp_tokens(source)
        return any(t.text == ";" for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_c_cpp_tokens(source)
        semicolons = [t for t in tokens if t.text == ";"]
        if not semicolons:
            return MutationResult(success=False, error_message="No semicolon found")

        rng = random.Random(seed)
        target = rng.choice(semicolons)

        mutated = source[: target.start_offset] + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Removed semicolon statement terminator",
            original_token=";",
            mutated_token="",
        )


# =====================================================================
# OPERATOR 2: C_EXTRA_SEMICOLON
# =====================================================================
class CExtraSemicolon(MutationOperator):
    operator_id = "C_EXTRA_SEMICOLON"
    supported_languages = [Language.C, Language.CPP]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "extra_semicolon"
    description = "Inserts an illegal misplaced semicolon in an expression or declaration."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_c_cpp_tokens(source)
        return any(t.text in ("=", "+", "-", "*") for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_c_cpp_tokens(source)
        candidates = [t for t in tokens if t.text in ("=", "+", "-", "*")]
        if not candidates:
            return MutationResult(success=False, error_message="No suitable operator location")

        rng = random.Random(seed)
        target = rng.choice(candidates)
        mutated = source[: target.end_offset] + " ; " + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Inserted misplaced semicolon in expression",
            original_token=target.text,
            mutated_token=f"{target.text} ;",
        )


# =====================================================================
# OPERATOR 3: UNMATCHED_OPENING_BRACKET
# =====================================================================
class UnmatchedOpeningBracket(MutationOperator):
    operator_id = "UNMATCHED_OPENING_BRACKET"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "unmatched_bracket"
    description = "Removes a closing bracket ']' creating an unmatched opening bracket."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text == "]" for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        brackets = [t for t in tokens if t.text == "]"]
        if not brackets:
            return MutationResult(success=False, error_message="No closing bracket ']' found")

        rng = random.Random(seed)
        target = rng.choice(brackets)
        mutated = source[: target.start_offset] + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Removed closing bracket ']' leaving unmatched '['",
            original_token="]",
            mutated_token="",
        )


# =====================================================================
# OPERATOR 4: UNMATCHED_CLOSING_BRACKET
# =====================================================================
class UnmatchedClosingBracket(MutationOperator):
    operator_id = "UNMATCHED_CLOSING_BRACKET"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "unmatched_bracket"
    description = "Inserts an extraneous closing bracket ']' creating a syntax error."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text in (")", "]") for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        candidates = [t for t in tokens if t.text in (")", "]")]
        if not candidates:
            return MutationResult(success=False, error_message="No bracket/parenthesis found")

        rng = random.Random(seed)
        target = rng.choice(candidates)
        mutated = source[: target.end_offset] + "]" + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col + 1,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Inserted extraneous closing bracket ']'",
            original_token=target.text,
            mutated_token=f"{target.text}]",
        )


# =====================================================================
# OPERATOR 5: UNMATCHED_PARENTHESIS
# =====================================================================
class UnmatchedParenthesis(MutationOperator):
    operator_id = "UNMATCHED_PARENTHESIS"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "unmatched_parenthesis"
    description = "Removes a closing parenthesis ')' creating unmatched parenthesis."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text == ")" for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        parens = [t for t in tokens if t.text == ")"]
        if not parens:
            return MutationResult(success=False, error_message="No closing parenthesis ')' found")

        rng = random.Random(seed)
        target = rng.choice(parens)
        mutated = source[: target.start_offset] + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Removed closing parenthesis ')'",
            original_token=")",
            mutated_token="",
        )


# =====================================================================
# OPERATOR 6: MISSING_CLOSING_BRACE
# =====================================================================
class MissingClosingBrace(MutationOperator):
    operator_id = "MISSING_CLOSING_BRACE"
    supported_languages = [Language.C, Language.CPP]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "missing_brace"
    description = "Removes a closing brace '}' in C/C++."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_c_cpp_tokens(source)
        return any(t.text == "}" for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_c_cpp_tokens(source)
        braces = [t for t in tokens if t.text == "}"]
        if not braces:
            return MutationResult(success=False, error_message="No closing brace '}' found")

        # Pick the final closing brace of the file to guarantee file-level unclosed brace
        target = braces[-1]
        mutated = source[: target.start_offset] + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Removed final closing brace '}'",
            original_token="}",
            mutated_token="",
        )


# =====================================================================
# OPERATOR 7: ARITHMETIC_OPERATOR_MUTATION
# =====================================================================
class ArithmeticOperatorMutation(MutationOperator):
    operator_id = "ARITHMETIC_OPERATOR_MUTATION"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.EXPRESSION_OPERATOR.value
    intended_subcategory = "invalid_expression_operator"
    description = "Mutates an arithmetic operator into an invalid juxtaposed operator syntax."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text in ("+", "-", "*", "/", "%") for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        candidates = [t for t in tokens if t.text in ("+", "-", "*", "/", "%")]
        if not candidates:
            return MutationResult(success=False, error_message="No arithmetic operator found")

        rng = random.Random(seed)
        target = rng.choice(candidates)
        # Create an invalid operator juxtaposition: '+ *' or '* /'
        replacement = f"{target.text} *"
        mutated = source[: target.start_offset] + replacement + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description=f"Mutated operator '{target.text}' to invalid juxtaposition '{replacement}'",
            original_token=target.text,
            mutated_token=replacement,
        )


# =====================================================================
# OPERATOR 8: COMPARISON_OPERATOR_MUTATION
# =====================================================================
class ComparisonOperatorMutation(MutationOperator):
    operator_id = "COMPARISON_OPERATOR_MUTATION"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.EXPRESSION_OPERATOR.value
    intended_subcategory = "invalid_comparison"
    description = "Replaces a comparison operator with an invalid comparison token syntax."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text in ("<", ">", "<=", ">=", "==") for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        candidates = [t for t in tokens if t.text in ("<", ">", "<=", ">=", "==")]
        if not candidates:
            return MutationResult(success=False, error_message="No comparison operator found")

        rng = random.Random(seed)
        target = rng.choice(candidates)
        replacement = "= <"  # Syntax error in C, C++, and Python
        mutated = source[: target.start_offset] + replacement + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Replaced comparison operator with invalid syntax '= <'",
            original_token=target.text,
            mutated_token=replacement,
        )


# =====================================================================
# OPERATOR 9: ASSIGNMENT_VS_EQUALITY_MUTATION
# =====================================================================
class AssignmentVsEqualityMutation(MutationOperator):
    operator_id = "ASSIGNMENT_VS_EQUALITY_MUTATION"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.EXPRESSION_OPERATOR.value
    intended_subcategory = "invalid_assignment_target"
    description = "Mutates assignment/equality creating an invalid assignment target or comparison syntax."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text in ("==", "=") for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        if language == Language.PYTHON:
            eqs = [t for t in tokens if t.text == "=="]
            if not eqs:
                return MutationResult(success=False, error_message="No '==' equality found in Python")
            target = eqs[0]
            mutated = source[: target.start_offset] + "=" + source[target.end_offset :]
            return MutationResult(
                success=True,
                mutated_code=mutated,
                target_line=target.start_line,
                target_column=target.start_col,
                operator_id=self.operator_id,
                intended_category=self.intended_category,
                intended_subcategory=self.intended_subcategory,
                description="Replaced '==' with '=' in Python condition (SyntaxError)",
                original_token="==",
                mutated_token="=",
            )
        else:
            # In C/C++: replace assignment target with constant or rvalue, e.g. '10 = '
            assigns = [t for t in tokens if t.text == "="]
            if not assigns:
                return MutationResult(success=False, error_message="No '=' assignment found")
            target = assigns[0]
            # Replace preceding identifier with constant (100 = ...)
            mutated = source[: target.start_offset] + "= 100 =" + source[target.end_offset :]
            return MutationResult(
                success=True,
                mutated_code=mutated,
                target_line=target.start_line,
                target_column=target.start_col,
                operator_id=self.operator_id,
                intended_category=self.intended_category,
                intended_subcategory=self.intended_subcategory,
                description="Inserted invalid chained rvalue assignment target",
                original_token="=",
                mutated_token="= 100 =",
            )


# =====================================================================
# OPERATOR 10: MISSING_EXPRESSION_OPERAND
# =====================================================================
class MissingExpressionOperand(MutationOperator):
    operator_id = "MISSING_EXPRESSION_OPERAND"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.EXPRESSION_OPERATOR.value
    intended_subcategory = "missing_operand"
    description = "Removes the right-hand operand of an expression leaving a dangling binary operator."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        for i, t in enumerate(tokens[:-1]):
            if t.text in ("+", "-", "*") and tokens[i + 1].token_type in ("NUMBER", "IDENTIFIER"):
                return True
        return False

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        candidates = []
        for i, t in enumerate(tokens[:-1]):
            if t.text in ("+", "-", "*") and tokens[i + 1].token_type in ("NUMBER", "IDENTIFIER"):
                candidates.append((t, tokens[i + 1]))

        if not candidates:
            return MutationResult(success=False, error_message="No binary operand candidate found")

        rng = random.Random(seed)
        op_tok, rhs_tok = rng.choice(candidates)
        mutated = source[: rhs_tok.start_offset] + source[rhs_tok.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=rhs_tok.start_line,
            target_column=rhs_tok.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description=f"Deleted right operand '{rhs_tok.text}' after '{op_tok.text}'",
            original_token=rhs_tok.text,
            mutated_token="",
        )


# =====================================================================
# OPERATOR 11: MISSING_DELIMITER_COMMA
# =====================================================================
class MissingDelimiterComma(MutationOperator):
    operator_id = "MISSING_DELIMITER_COMMA"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.DELIMITER_PUNCTUATION.value
    intended_subcategory = "missing_comma"
    description = "Removes a comma ',' separator in an argument list or initializer."

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.text == "," for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        commas = [t for t in tokens if t.text == ","]
        if not commas:
            return MutationResult(success=False, error_message="No comma ',' found")

        rng = random.Random(seed)
        target = rng.choice(commas)
        mutated = source[: target.start_offset] + " " + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Removed comma delimiter in argument/element list",
            original_token=",",
            mutated_token=" ",
        )


# =====================================================================
# OPERATOR 12: IDENTIFIER_MISSPELLING
# =====================================================================
class IdentifierMisspelling(MutationOperator):
    operator_id = "IDENTIFIER_MISSPELLING"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.DECLARATION_IDENTIFIER.value
    intended_subcategory = "undeclared_identifier"
    description = "Mangles a variable or function identifier into an undeclared name."

    RESERVED = {
        "int", "char", "float", "double", "void", "return", "if", "else", "for",
        "while", "do", "switch", "case", "default", "break", "continue", "struct",
        "class", "public", "private", "const", "bool", "true", "false", "def",
        "import", "from", "class", "return", "if", "elif", "else", "try", "except",
        "finally", "with", "as", "pass", "in", "is", "and", "or", "not", "main",
        "printf", "std", "cout", "endl", "vector", "string", "print", "len", "range"
    }

    def can_apply(self, source: str, language: Language) -> bool:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        return any(t.token_type in ("IDENTIFIER", "NAME") and t.text not in self.RESERVED for t in tokens)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        tokens = scan_python_tokens(source) if language == Language.PYTHON else scan_c_cpp_tokens(source)
        candidates = [t for t in tokens if t.token_type in ("IDENTIFIER", "NAME") and t.text not in self.RESERVED]
        if not candidates:
            return MutationResult(success=False, error_message="No eligible identifier found")

        rng = random.Random(seed)
        target = rng.choice(candidates)
        mangled = f"{target.text}_undeclared_id"
        mutated = source[: target.start_offset] + mangled + source[target.end_offset :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target.start_line,
            target_column=target.start_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description=f"Mangled identifier '{target.text}' to '{mangled}'",
            original_token=target.text,
            mutated_token=mangled,
        )


# =====================================================================
# OPERATOR 13: EXTRA_FUNCTION_ARGUMENT
# =====================================================================
class ExtraFunctionArgument(MutationOperator):
    operator_id = "EXTRA_FUNCTION_ARGUMENT"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.FUNCTION_CALL_ARGUMENT.value
    intended_subcategory = "too_many_arguments"
    description = "Inserts an extra argument into a function call causing argument count error."

    def can_apply(self, source: str, language: Language) -> bool:
        matches = list(re.finditer(r"\b([a-zA-Z_]\w*)\s*\(([^()\n]*)\)", source))
        exclude = {"if", "while", "for", "switch", "catch", "sizeof", "main"}
        return any(m.group(1) not in exclude for m in matches)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        matches = list(re.finditer(r"\b([a-zA-Z_]\w*)\s*\(([^()\n]*)\)", source))
        exclude = {"if", "while", "for", "switch", "catch", "sizeof", "main"}
        valid_calls = [m for m in matches if m.group(1) not in exclude]
        if not valid_calls:
            return MutationResult(success=False, error_message="No eligible function call found")

        rng = random.Random(seed)
        m = rng.choice(valid_calls)
        inner_args = m.group(2).strip()
        new_args = f"{inner_args}, 99999" if inner_args else "99999"
        replacement = f"{m.group(1)}({new_args})"

        lines_before = source[: m.start()].splitlines(keepends=True)
        target_line = len(lines_before) if lines_before else 1
        target_col = len(lines_before[-1]) + 1 if lines_before else 1

        mutated = source[: m.start()] + replacement + source[m.end() :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target_line,
            target_column=target_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description=f"Appended extra argument to function call '{m.group(1)}'",
            original_token=m.group(0),
            mutated_token=replacement,
        )


# =====================================================================
# OPERATOR 14: MISSING_FUNCTION_ARGUMENT
# =====================================================================
class MissingFunctionArgument(MutationOperator):
    operator_id = "MISSING_FUNCTION_ARGUMENT"
    supported_languages = [Language.C, Language.CPP, Language.PYTHON]
    intended_category = ErrorCategory.FUNCTION_CALL_ARGUMENT.value
    intended_subcategory = "too_few_arguments"
    description = "Removes a required argument from a multi-argument function call."

    def can_apply(self, source: str, language: Language) -> bool:
        matches = list(re.finditer(r"\b([a-zA-Z_]\w*)\s*\(([^()\n]+,[^()\n]+)\)", source))
        exclude = {"if", "while", "for", "switch", "printf"}
        return any(m.group(1) not in exclude for m in matches)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        matches = list(re.finditer(r"\b([a-zA-Z_]\w*)\s*\(([^()\n]+,[^()\n]+)\)", source))
        exclude = {"if", "while", "for", "switch", "printf"}
        candidates = [m for m in matches if m.group(1) not in exclude]
        if not candidates:
            return MutationResult(success=False, error_message="No multi-argument function call found")

        rng = random.Random(seed)
        m = rng.choice(candidates)
        args = [a.strip() for a in m.group(2).split(",")]
        new_args = args[0]
        replacement = f"{m.group(1)}({new_args})"

        lines_before = source[: m.start()].splitlines(keepends=True)
        target_line = len(lines_before) if lines_before else 1
        target_col = len(lines_before[-1]) + 1 if lines_before else 1

        mutated = source[: m.start()] + replacement + source[m.end() :]
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target_line,
            target_column=target_col,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description=f"Dropped argument in function call '{m.group(1)}'",
            original_token=m.group(0),
            mutated_token=replacement,
        )


# =====================================================================
# OPERATOR 15: PYTHON_INDENTATION_ERROR
# =====================================================================
class PythonIndentationError(MutationOperator):
    operator_id = "PYTHON_INDENTATION_ERROR"
    supported_languages = [Language.PYTHON]
    intended_category = ErrorCategory.INDENTATION_BLOCK.value
    intended_subcategory = "indentation_error"
    description = "Corrupts Python block indentation causing IndentationError."

    def can_apply(self, source: str, language: Language) -> bool:
        if language != Language.PYTHON:
            return False
        lines = source.splitlines()
        return any(line.startswith("    ") and not line.strip().startswith("#") for line in lines)

    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        if language != Language.PYTHON:
            return MutationResult(success=False, error_message="Only Python supports indentation mutations")

        lines = source.splitlines(keepends=True)
        candidate_indices = [
            idx for idx, line in enumerate(lines)
            if line.startswith("    ") and not line.strip().startswith("#") and line.strip()
        ]
        if not candidate_indices:
            return MutationResult(success=False, error_message="No indented line found")

        rng = random.Random(seed)
        target_idx = rng.choice(candidate_indices)
        orig_line = lines[target_idx]

        corrupted_indent = "   " if orig_line.startswith("    ") else " "
        corrupted_line = corrupted_indent + orig_line.lstrip()

        lines[target_idx] = corrupted_line
        mutated = "".join(lines)
        return MutationResult(
            success=True,
            mutated_code=mutated,
            target_line=target_idx + 1,
            target_column=1,
            operator_id=self.operator_id,
            intended_category=self.intended_category,
            intended_subcategory=self.intended_subcategory,
            description="Corrupted block indentation level",
            original_token=orig_line[:4],
            mutated_token=corrupted_indent,
        )


# Register all 15 operators in the default registry
ALL_OPERATORS: List[MutationOperator] = [
    CMissingSemicolon(),
    CExtraSemicolon(),
    UnmatchedOpeningBracket(),
    UnmatchedClosingBracket(),
    UnmatchedParenthesis(),
    MissingClosingBrace(),
    ArithmeticOperatorMutation(),
    ComparisonOperatorMutation(),
    AssignmentVsEqualityMutation(),
    MissingExpressionOperand(),
    MissingDelimiterComma(),
    IdentifierMisspelling(),
    ExtraFunctionArgument(),
    MissingFunctionArgument(),
    PythonIndentationError(),
]

for op in ALL_OPERATORS:
    try:
        default_registry.register(op)
    except ValueError:
        pass
