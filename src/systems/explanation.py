"""Student- and beginner-friendly explanation generator for compiler error repairs.

Translates compiler diagnostics, AST context, and verification results into
clean, intuitive 4-part explanations:
  1. 🔴 Error: Simple description of what went wrong and where.
  2. 🔧 Fix: What was changed to correct it.
  3. 💡 Why?: Intuitive rationale for why the fix works.
  4. ✅ Corrected Code: Cleanly formatted final code ready to copy.
"""

from __future__ import annotations

import re
from typing import Any

from src.analysis_engine.contracts import DetectionResult, Diagnostic
from src.systems.verification import VerificationResult


def _clean_message(msg: str) -> str:
    """Strip file paths, compiler error codes, and technical prefix jargon."""
    if not msg:
        return ""
    # Strip paths like "input.c:3:5: error: "
    cleaned = re.sub(r"^.*?:\d+:(?:\d+:)?\s*(error|warning|note):\s*", "", msg, flags=re.IGNORECASE)
    # Strip bracketed error codes like [syntax] or [-Werror]
    cleaned = re.sub(r"\[-W[\w-]+\]", "", cleaned)
    cleaned = re.sub(r"\[[\w-]+\]$", "", cleaned)
    return cleaned.strip()


def _format_error_desc(root: Diagnostic | None, language: str) -> tuple[str, str, str]:
    """Return friendly (error_text, fix_text, why_text) based on diagnostic category and message."""
    if not root:
        return (
            "The compiler detected an issue with the program structure.",
            "Adjusted the syntax to satisfy compiler rules.",
            "All programming languages require strict adhering to grammatical rules."
        )

    line = root.line
    line_ref = f"on line {line}" if line and line > 0 else "in the code"
    msg = _clean_message(root.message)
    cat = (root.category or "").lower()
    subcat = (root.subcategory or "").lower()
    lang_name = "Python" if language == "python" else ("C++" if language in ("cpp", "c++") else "C")

    # 1. Missing Colon (Python)
    if subcat == "missing_colon" or "expected ':'" in msg.lower() or "missing colon" in msg.lower():
        return (
            f"A colon (':') was missing at the end of the statement {line_ref}.",
            f"Added a colon ':' to the end of the statement {line_ref}.",
            f"In {lang_name}, headers like 'def', 'if', 'for', 'while', and 'class' must end with a colon to start a code block."
        )

    # 2. Missing Semicolon (C / C++)
    if subcat == "missing_semicolon" or "expected ';'" in msg.lower() or "missing semicolon" in msg.lower():
        return (
            f"A semicolon (';') was missing at the end of the statement {line_ref}.",
            f"Added a terminating semicolon ';' to line {line if line else 'the statement'}.",
            f"In {lang_name}, statements must end with a semicolon so the compiler knows where each instruction finishes."
        )

    # 3. Indentation Error (Python)
    if cat == "indentation_block" or "indent" in subcat or "indent" in msg.lower():
        return (
            f"There was an indentation mismatch {line_ref}.",
            f"Aligned the indentation {line_ref} with its surrounding block.",
            f"{lang_name} uses consistent indentation (typically 4 spaces) instead of curly braces to define code blocks."
        )

    # 4. Missing Brace / Parenthesis / Bracket
    if "brace" in subcat or "expected '}'" in msg.lower() or "never closed" in msg.lower():
        return (
            f"A closing curly brace ('}}') was missing near {line_ref}.",
            "Added the matching closing curly brace '}' to enclose the code block.",
            f"In {lang_name}, every opening curly brace '{{' must be paired with a closing brace '}}' to define a block."
        )
    if "parenthesis" in subcat or "bracket" in subcat or "unmatched" in msg.lower() or "closing parenthesis" in msg.lower():
        return (
            f"Unmatched parenthesis or bracket detected {line_ref}.",
            "Balanced the opening and closing parentheses/brackets.",
            "Opening and closing brackets must always appear in matching pairs."
        )

    # 5. Missing Include or Import
    if subcat in ("missing_header", "missing_include") or "undeclared library function" in msg.lower() or "implicit declaration" in msg.lower():
        match_sym = re.search(r"'(?P<sym>\w+)'", msg)
        sym = f" for '{match_sym.group('sym')}'" if match_sym else ""
        return (
            f"A standard library function was used {line_ref} without its required header file.",
            f"Added the appropriate #include directive{sym} at the top of the file.",
            f"In {lang_name}, header files must be included so the compiler knows the function declaration and argument types."
        )
    if subcat == "missing_import" or ("name" in msg.lower() and "not defined" in msg.lower() and language == "python"):
        match_sym = re.search(r"'(?P<sym>\w+)'", msg)
        sym = f" for '{match_sym.group('sym')}'" if match_sym else ""
        return (
            f"A module or identifier was used {line_ref} without being imported.",
            f"Added the required import statement{sym} at the top of the file.",
            f"In {lang_name}, library modules must be imported before you can use their functions."
        )

    # 6. Undeclared Identifier / Typo
    if "undeclared" in msg.lower() or "undefined name" in msg.lower() or "not defined" in msg.lower():
        match_sym = re.search(r"'(?P<sym>\w+)'", msg)
        sym = f" '{match_sym.group('sym')}'" if match_sym else ""
        return (
            f"The variable or function{sym} was used {line_ref} before being defined.",
            f"Corrected the identifier name{sym} to match the intended definition.",
            "Identifiers must be properly defined or declared before they can be referenced in code."
        )

    # 7. Assignment vs Comparison
    if "lvalue" in msg.lower() or "assignment" in subcat or "maybe you meant '=='" in msg.lower():
        return (
            f"An assignment operator '=' was used instead of a comparison operator '==' {line_ref}.",
            f"Replaced the assignment '=' with the comparison operator '==' {line_ref}.",
            "In conditional statements, '==' tests whether values are equal, whereas '=' is used to assign values."
        )

    # 8. Extra Semicolon or Operator
    if "extra_semicolon" in subcat or "primary-expression before ';'" in msg.lower():
        return (
            f"An unnecessary semicolon was placed inside an expression {line_ref}.",
            f"Removed the stray semicolon from line {line if line else 'the expression'}.",
            "Semicolons should only be placed at the end of completed statements, not within expressions."
        )

    # 9. Argument Count
    if "too many arguments" in msg.lower() or "too few arguments" in msg.lower() or "function_call_argument" in cat:
        return (
            f"A function was called {line_ref} with the wrong number of arguments.",
            "Adjusted the function call arguments to match the function's declaration.",
            "The number of arguments provided in a function call must match what the function expects."
        )

    # Fallback with sanitized message
    clean_msg = msg if msg else "Syntax error"
    return (
        f"The compiler found a syntax issue {line_ref}: {clean_msg}.",
        f"Corrected the syntax error {line_ref}.",
        f"The corrected syntax satisfies {lang_name} language requirements."
    )


def generate_beginner_explanation(
    status: str,
    reason: str,
    detection: DetectionResult,
    original_code: str,
    language: str,
    context: dict[str, Any] | None = None,
    repair: dict[str, Any] | None = None,
    selected: VerificationResult | None = None,
    repaired_code: str | None = None,
) -> dict[str, Any]:
    """Generate a 4-part beginner-friendly explanation.

    Returns a dictionary with:
      - status: 'clean' | 'fixed' | 'unresolved'
      - error: 🔴 Error description
      - fix: 🔧 Fix description
      - why: 💡 Why the fix works
      - corrected_code: ✅ Complete code ready to copy
      - summary: Brief one-line takeaway
    """
    root = detection.root if detection else None

    # Case 1: Clean code (no errors detected)
    if not detection.detected or root is None or reason == "no error detected":
        return {
            "status": "clean",
            "error": "No errors detected! Your code is syntactically correct and compiled cleanly.",
            "fix": "No fix needed — code runs as written.",
            "why": "Your program satisfies all syntax and grammatical requirements of the language.",
            "corrected_code": original_code,
            "summary": "Everything looks good! No errors were found.",
        }

    # Case 2: Successfully verified repair
    if status == "VERIFIED" and repaired_code:
        err_text, default_fix, why_text = _format_error_desc(root, language)

        # Use specific beginner-friendly fix text, falling back to rule description if generic
        fix_text = default_fix
        if default_fix.startswith("Corrected the syntax"):
            if repair and repair.get("chosen") and repair["chosen"].get("description"):
                rule_desc = repair["chosen"]["description"]
                fix_text = f"Applied rule: {rule_desc}."
            elif selected and selected.candidate_id and selected.candidate_id.startswith("rule_"):
                rule_name = selected.candidate_id[5:].replace("_", " ")
                fix_text = f"Fixed using {rule_name} rule."

        return {
            "status": "fixed",
            "error": err_text,
            "fix": fix_text,
            "why": why_text,
            "corrected_code": repaired_code,
            "summary": "Error resolved and independently verified by the compiler.",
        }

    # Case 3: Could not be automatically repaired within budget
    err_text, _, why_text = _format_error_desc(root, language)
    line_ref = f"line {root.line}" if root and root.line else "the highlighted section"
    return {
        "status": "unresolved",
        "error": err_text,
        "fix": "Automated repair could not be safely verified.",
        "why": (
            f"The system attempted automated repairs, but none could be safely verified without risking "
            f"unintended changes to your program's logic. Please inspect {line_ref} and check variable names, types, or syntax."
        ),
        "corrected_code": original_code,
        "summary": "Could not automatically resolve safely; please check the error details.",
    }
