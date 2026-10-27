"""Tests for beginner-friendly explanation generator and document import UI integration."""

import json
from pathlib import Path
from src.systems.explanation import generate_beginner_explanation
from src.systems.pipeline import run_pipeline


def test_clean_python_code_explanation():
    clean_code = "def add(a, b):\n    return a + b\n"
    report = run_pipeline(clean_code, "python")
    assert report.status == "NOT_REPAIRED"
    assert report.explanation is not None
    assert report.explanation["status"] == "clean"
    assert "No errors detected" in report.explanation["error"]
    assert report.explanation["corrected_code"] == clean_code


def test_verified_python_missing_colon_explanation():
    broken_code = "def add(a, b)\n    return a + b\n"
    report = run_pipeline(broken_code, "python")
    assert report.status == "VERIFIED"
    assert report.explanation is not None
    assert report.explanation["status"] == "fixed"
    assert "colon" in report.explanation["error"].lower()
    assert "colon" in report.explanation["fix"].lower()
    assert "why" in report.explanation and len(report.explanation["why"]) > 10
    assert report.explanation["corrected_code"] == "def add(a, b):\n    return a + b\n"


def test_verified_c_missing_semicolon_explanation():
    import pytest
    from src.data_engine.language_adapters import get_adapter

    if not get_adapter("c").is_available():
        pytest.skip("C compiler unavailable")

    broken_c = "int main(void) {\n    int ret = 0\n    int other = 1;\n    return ret + other;\n}\n"
    report = run_pipeline(broken_c, "c")
    assert report.status == "VERIFIED"
    assert report.explanation is not None
    assert report.explanation["status"] == "fixed"
    assert "semicolon" in report.explanation["error"].lower()
    assert "semicolon" in report.explanation["fix"].lower()
    assert "why" in report.explanation and len(report.explanation["why"]) > 10
    assert "int ret = 0;" in report.explanation["corrected_code"]


def test_unresolvable_error_explanation():
    unresolvable = "x = zzqqwwxx(1)\n"
    report = run_pipeline(unresolvable, "python", max_attempts=2)
    assert report.status in ("NOT_REPAIRED", "INCONCLUSIVE")
    assert report.explanation is not None
    assert report.explanation["status"] == "unresolved"
    assert "Automated repair could not be safely verified" in report.explanation["fix"]
    assert "safely" in report.explanation["why"].lower()
    assert report.explanation["corrected_code"] == unresolvable


def test_ui_contains_document_import_and_explanation_markup():
    index_html = (Path(__file__).resolve().parent.parent / "dev_frontend" / "index.html").read_text(encoding="utf-8")
    # Verify Document import controls
    assert "id=\"tab-file\"" in index_html
    assert "id=\"file-input\"" in index_html
    assert ".c,.cpp,.cc,.cxx,.h,.hpp,.java,.py,.txt" in index_html
    assert "id=\"file-badge-wrap\"" in index_html
    assert "id=\"drop-box\"" in index_html
    assert "id=\"file-error\"" in index_html

    # Verify 4-part Simplified Final Explanation
    assert "id=\"explanation-card\"" in index_html
    assert "### 🔴 Error" in index_html
    assert "### 🔧 Fix" in index_html
    assert "### 💡 Why?" in index_html
    assert "### ✅ Corrected Code" in index_html

    # Verify backward compatibility with existing tests
    assert "Verification and attempt history" in index_html
