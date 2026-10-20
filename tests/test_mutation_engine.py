"""Tests for mutation registry, operators, and comment/string protection."""

import pytest
import src.data_engine
from src.data_engine.mutation_registry import default_registry
from src.data_engine.schemas import Language

C_SAMPLE = r"""#include <stdio.h>
// Comment with semicolon;
int compute(int x, int y) {
    /* Multi-line
       comment */
    int arr[2] = {x, y};
    if (x == y) {
        printf("String with ; and ()\n");
        return x + y;
    }
    return x * 2;
}

int main() {
    int ans = compute(10, 20);
    return 0;
}
"""

PY_SAMPLE = """def calculate(a, b):
    # Comment with ; and []
    items = [a, b]
    if a == b:
        msg = "String with ; and {}"
        return a + b
    return a * 2

if __name__ == '__main__':
    res = calculate(10, 20)
"""


def test_operator_count():
    ops = default_registry.list_all()
    assert len(ops) >= 15, f"Expected at least 15 registered operators, found {len(ops)}"


def test_unique_operator_ids():
    ops = default_registry.list_all()
    ids = [op.operator_id for op in ops]
    assert len(ids) == len(set(ids)), "Operator IDs must be unique"


def test_operators_have_supported_languages():
    for op in default_registry.list_all():
        assert len(op.supported_languages) > 0
        assert op.intended_category
        assert op.intended_subcategory


def test_reproducible_mutation():
    op = default_registry.get("C_MISSING_SEMICOLON")
    assert op is not None
    res1 = op.apply(C_SAMPLE, Language.C, seed=123)
    res2 = op.apply(C_SAMPLE, Language.C, seed=123)
    assert res1.success
    assert res2.success
    assert res1.mutated_code == res2.mutated_code
    assert res1.target_line == res2.target_line


def test_comments_and_strings_protected():
    op = default_registry.get("C_MISSING_SEMICOLON")
    res = op.apply(C_SAMPLE, Language.C, seed=42)
    assert res.success
    assert "// Comment with semicolon;" in res.mutated_code
    assert "String with ; and ()" in res.mutated_code


def test_inapplicable_mutation_fails_safely():
    op = default_registry.get("PYTHON_INDENTATION_ERROR")
    # Code with no indentation
    unindented = "x = 1\ny = 2\n"
    can = op.can_apply(unindented, Language.PYTHON)
    assert can is False
    res = op.apply(unindented, Language.PYTHON, seed=42)
    assert res.success is False
    assert res.error_message is not None


def test_all_15_operators_have_applicable_fixtures():
    for op in default_registry.list_all():
        lang = op.supported_languages[0]
        sample = PY_SAMPLE if lang == Language.PYTHON else C_SAMPLE
        can = op.can_apply(sample, lang)
        assert can is True, f"Operator {op.operator_id} failed precondition check on sample {lang.value}"
        res = op.apply(sample, lang, seed=42)
        assert res.success is True, f"Operator {op.operator_id} failed to apply: {res.error_message}"
        assert res.target_line is not None
