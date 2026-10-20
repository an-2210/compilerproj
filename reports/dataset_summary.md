# Compiler Error Detection & Repair — Dataset Report
**Generated at:** 2026-10-20T05:51:14.612575+00:00
**Total Records:** `216`

## 1. High-Level Dataset Overview
| Metric | Value |
|---|---|
| Total Records | **216** |
| Synthetic Examples | 208 |
| Real-Bug Examples | 8 |
| Train Set Size | 164 |
| Validation Set Size | 20 |
| Test Set Size | 24 |
| Real-Bug Test Set Size | 8 |
| Diagnostic Extraction Rate | 100.00% |
| Leakage-Free Audit | `PASSED` |

## 2. Language Distribution
| Language | Count | Percentage |
|---|---|---|
| `c` | 83 | 38.4% |
| `python` | 71 | 32.9% |
| `cpp` | 62 | 28.7% |

## 3. Error Category Balance
| Error Category | Count | Percentage |
|---|---|---|
| `delimiter_punctuation` | 98 | 45.4% |
| `expression_operator` | 79 | 36.6% |
| `function_call_argument` | 19 | 8.8% |
| `declaration_identifier` | 13 | 6.0% |
| `indentation_block` | 7 | 3.2% |

## 4. Mutation Operator Counts
| Operator ID | Count |
|---|---|
| `ASSIGNMENT_VS_EQUALITY_MUTATION` | 29 |
| `COMPARISON_OPERATOR_MUTATION` | 19 |
| `UNMATCHED_PARENTHESIS` | 18 |
| `MISSING_DELIMITER_COMMA` | 18 |
| `ARITHMETIC_OPERATOR_MUTATION` | 18 |
| `UNMATCHED_CLOSING_BRACKET` | 15 |
| `MISSING_EXPRESSION_OPERAND` | 12 |
| `UNMATCHED_OPENING_BRACKET` | 12 |
| `C_EXTRA_SEMICOLON` | 12 |
| `IDENTIFIER_MISSPELLING` | 12 |
| `MISSING_CLOSING_BRACE` | 11 |
| `MISSING_FUNCTION_ARGUMENT` | 9 |
| `EXTRA_FUNCTION_ARGUMENT` | 9 |
| `C_MISSING_SEMICOLON` | 8 |
| `PYTHON_INDENTATION_ERROR` | 6 |

## 5. Leakage-Safe Split Audit
All split groups are isolated to prevent data leakage:

| Boundary Check | Forbidden Intersection Size | Status |
|---|---|---|
| `train_val` | `0` | **EMPTY (PASS)** |
| `train_test` | `0` | **EMPTY (PASS)** |
| `val_test` | `0` | **EMPTY (PASS)** |
| `train_real` | `0` | **EMPTY (PASS)** |
| `val_real` | `0` | **EMPTY (PASS)** |

