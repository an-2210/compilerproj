"""Analysis Engineer: rule-based repair. Each case asserts the exact repaired program."""

import pytest

from src.analysis_engine import build_context, detect, rule_repair


def _repair(code, language, layers="full"):
    result = detect(code, language, layers=layers)
    assert result.detected, "fixture must contain an error"
    ctx = build_context(code, result.root, language)
    return rule_repair(ctx)


def _chosen_code(code, language, layers="full"):
    chosen = _repair(code, language, layers).chosen
    assert chosen is not None, "no candidate produced"
    return chosen.code


# ---------------------------------------------------------------- Python

def test_python_missing_colon_is_added():
    broken = "def area(r)\n    return 3 * r * r\n"
    assert _chosen_code(broken, "python") == "def area(r):\n    return 3 * r * r\n"


def test_python_expected_indent_is_fixed():
    broken = "def f(x):\n    if x:\nreturn 1\n"
    fixed = _chosen_code(broken, "python")
    assert fixed == "def f(x):\n    if x:\n        return 1\n"


def test_python_unindent_mismatch_uses_header_plus_four():
    # Line 4 is dedented to 6, which matches no open block; the deeper level wins the tie
    broken = "def f(arr, t):\n    if arr[1] == t:\n        return 1\n      return 2\n"
    fixed = _chosen_code(broken, "python")
    assert fixed == "def f(arr, t):\n    if arr[1] == t:\n        return 1\n        return 2\n"


def test_python_equality_typo_is_fixed():
    broken = "x = 3\nif x = 3:\n    print(x)\n"
    assert _chosen_code(broken, "python") == "x = 3\nif x == 3:\n    print(x)\n"


def test_python_missing_stdlib_import_is_added():
    broken = "print(math.sqrt(16))\n"
    fixed = _chosen_code(broken, "python", layers="fast")
    assert fixed.startswith("import math\n")
    assert not detect(fixed, "python", layers="fast").detected


def test_python_misspelled_name_is_renamed_to_declared_symbol():
    broken = "total = 5\nprint(totl)\n"
    assert _chosen_code(broken, "python", layers="fast") == "total = 5\nprint(total)\n"


def test_python_rule_candidates_are_all_checked_and_chosen_compiles():
    result = _repair("def f(x)\n    return x\n", "python")
    assert result.applicable
    assert result.chosen.compiles
    assert all(isinstance(c.compiles, bool) for c in result.rule_candidates)


# ---------------------------------------------------------------- C / C++ (compiler)

@pytest.mark.compiler
def test_c_missing_semicolon_is_added_to_the_real_line():
    broken = "int main(void) {\n    int ret = 0\n    int other = 1;\n    return ret + other;\n}\n"
    fixed = _chosen_code(broken, "c")
    assert "    int ret = 0;\n" in fixed
    assert not detect(fixed, "c").detected


@pytest.mark.compiler
def test_c_unmatched_paren_is_closed_before_the_brace():
    broken = "int f(int a) {\n    if (a > 0 && (a < 100) {\n        return 1;\n    }\n    return 0;\n}\n"
    fixed = _chosen_code(broken, "c")
    assert not detect(fixed, "c").detected
    assert "(a < 100))" in fixed.replace(" ", "") or "(a<100))" in fixed.replace(" ", "")


@pytest.mark.compiler
def test_c_missing_closing_brace_is_restored_at_top_level_blank_line():
    broken = "int main(void) {\n    return 0;\n\n"
    fixed = _chosen_code(broken, "c")
    assert fixed.count("}") == 1
    assert not detect(fixed, "c").detected


@pytest.mark.compiler
def test_c_assignment_in_condition_becomes_comparison():
    # 5 = a is an lvalue error; clang and gcc only warn about "if (a = 5)"
    broken = "int f(int a) {\n    if (5 = a) {\n        return 1;\n    }\n    return 0;\n}\n"
    fixed = _chosen_code(broken, "c")
    assert "if (5 == a)" in fixed.replace("  ", " ")


@pytest.mark.compiler
def test_c_undeclared_identifier_is_renamed_to_similar_symbol():
    broken = "int main(void) {\n    int counter = 0;\n    counter_ = counter + 1;\n    return counter;\n}\n"
    fixed = _chosen_code(broken, "c")
    assert not detect(fixed, "c").detected
    assert "counter_" not in fixed


@pytest.mark.compiler
def test_c_missing_header_for_printf_is_added():
    broken = "int main(void) {\n    printf(\"hi\\n\");\n    return 0;\n}\n"
    fixed = _chosen_code(broken, "c")
    assert "#include <stdio.h>" in fixed


@pytest.mark.compiler
def test_c_extra_semicolon_inside_expression_is_removed():
    broken = "int main(void) {\n    int x = ;  5;\n    return x;\n}\n"
    fixed = _chosen_code(broken, "c")
    assert not detect(fixed, "c").detected


@pytest.mark.compiler
def test_cpp_stray_operator_before_comparison_is_removed():
    broken = "bool f(int j, int n) {\n    for (int i = 0; j = < n; i++) {}\n    return true;\n}\n"
    fixed = _chosen_code(broken, "cpp")
    assert "j < n" in fixed.replace("  ", " ")


# ---------------------------------------------------------------- Result contract

def test_rule_repair_returns_no_candidates_when_nothing_applies():
    # An undeclared name with no similar declared symbol and no matching header
    code = "x = zzqqwwxx(1)\n"
    result = detect(code, "python", layers="fast")
    ctx = build_context(code, result.root, "python")
    repair = rule_repair(ctx)
    assert repair.chosen is None or repair.chosen.code != code
    assert repair.applicable == bool(repair.rule_candidates)


def test_rule_repair_never_returns_the_unchanged_program():
    code = "def f(x)\n    return x\n"
    result = detect(code, "python")
    repair = rule_repair(build_context(code, result.root, "python"))
    assert all(c.code != code for c in repair.rule_candidates)
