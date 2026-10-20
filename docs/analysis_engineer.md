# Analysis Engineer Layer: DETECT, CONTEXT and Rule-Based REPAIR

This layer owns `src/analysis_engine/`. It reads the Data Engineer's records and returns the
hand-off objects that the ML Engineer (repair model) and the Systems Engineer (verify, API) use.

```
detect(code, language) -> DetectionResult
build_context(code, root, language) -> ErrorContext
rule_repair(ctx) -> RepairResult
```

---

## 1. Contracts (`src/analysis_engine/contracts.py`)

| Model | Purpose | Key fields |
|---|---|---|
| `Diagnostic` | One normalized compiler or analyzer message | `message`, `line`, `column`, `severity`, `source` (`ast`, `pyflakes`, `mypy`, `gcc`, `g++`), `category`, `subcategory`, `raw` |
| `DetectionResult` | Output of the layered detector | `detected`, `layer`, `diagnostics`, `root`, `cascades` |
| `ErrorContext` | Everything needed to repair one error | `root`, `reported_line`, `candidate_lines`, `line_text`, `enclosing_scope`, `symbols`, `imports`, `open_brackets`, `unclosed_at_eof`, `indent_of_line`, `enclosing_indents` |
| `RepairCandidate` | One proposed patch, already checked | `rule_id`, `description`, `line`, `confidence`, `code`, `compiles` |
| `RepairResult` | Output of rule-based repair | `rule_candidates`, `chosen`, `applicable` |

Notes for downstream users:
- `language` is `c`, `cpp` or `python`. Aliases `c++` and `py` are accepted.
- `category` and `subcategory` use the Data Engineer's taxonomy, so they can be compared with
  `expected.intended_category` in the records.
- `ErrorContext.candidate_lines` is ranked. The first entry is the line the layer believes holds
  the mistake; the compiler's own line is `reported_line`.
- `RepairResult.chosen` is the highest-confidence candidate that compiles. If nothing compiles it
  is the highest-confidence candidate with `compiles=False`. `chosen` is `None` when no rule applies.
- `compiles` means the detector found no error-severity diagnostic in the patched program
  (`layers="fast"`). It is not a semantic check.

---

## 2. DETECT (`src/analysis_engine/detect/`)

- **Python** runs in layers and each layer runs only if the earlier ones found nothing:
  1. `ast.parse` for syntax errors (exact line and column).
  2. `pyflakes` for undefined names only. Style warnings such as unused imports are ignored.
  3. `mypy` for `name-defined`, `call-arg`, `operator`, `index` and `attr-defined` errors. Only in `layers="full"`.
- **C and C++** use the Data Engineer's `get_adapter` (gcc or g++ with `-fsyntax-only -Wall`), so both
  teams see the same compiler output.
- **Normalizer** removes duplicates and ranks the root. A semantic error (undeclared name, wrong
  argument count) that appears after the first parse error is a cascade and is suppressed.
- **Taxonomy** (`detect/taxonomy.py`) maps messages to the Data Engineer's categories. It covers
  clang and gcc wording the shared categorizer misses, and falls back to the shared categorizer.

The detector has zero false positives on the 52 seed programs and on the 60 unique clean sources
in the splits.

---

## 3. CONTEXT (`src/analysis_engine/context/`)

- `python_context.py` uses **parso**, which recovers from syntax errors. It provides the enclosing
  function or class, defined names, and imports.
- `c_context.py` is lexical. It blanks comments and string literals, then finds functions, declared
  names, `#include`s and `#define`s. It does not parse C, so it never raises on malformed code.
- `scanner.py` tracks open brackets and indentation levels on the sanitized text.
- `line_mapping.py` maps the reported line to the true line:
  - **Missing `;`**: gcc reports the next token, which is usually on the following line. When the
    reported token starts its line, the nearest unterminated statement above it ranks first.
  - **Blanked `}`**: when the file ends inside an open `{`, the likely line is the blank top-level
    line after the last statement.
  - **Python "unexpected indent"**: when the line above has an indent that is not a multiple of the
    file's indent unit, that line ranks first.

---

## 4. Rule-based REPAIR (`src/analysis_engine/rules/`)

Each rule proposes small edits (`repairs.py`). `engine.py` applies every proposal, checks each patched
program with the detector, and returns the candidates.

| Rule | Triggers on | Example fix |
|---|---|---|
| `py_missing_colon` | `expected ':'` | `if x` to `if x:` |
| `py_expected_indent` | `expected an indented block` | indent to header + 4 |
| `py_unexpected_indent`, `py_unindent_mismatch` | indentation errors | align to header + 4, then to the nearest open block |
| `c_missing_terminator` | `expected ';'` or `expected initializer` | append `;` to the unterminated line |
| `bracket_insert`, `bracket_substitute`, `bracket_eof` | a closer was expected, or a bracket was never closed | insert or replace the closer |
| `closing_brace_restore` | file ends inside a `{` | fill the blank line with `}` |
| `closer_delete` | unmatched or unexpected closer | delete it |
| `extra_semicolon` | `expected expression` at a `;` | delete the `;` |
| `operator_removal` | a stray operator next to a real one | remove the injected operator |
| `stray_assignment_removal` | `x = 100 = 0` | remove `100 =` |
| `equality_assignment` | `lvalue required`, `not assignable`, `Maybe you meant '=='` | `=` to `==` in a condition |
| `extra_argument_removal` | `too many arguments` | drop one argument (last first) |
| `insert_comma` | a missing comma between list items | insert `,` |
| `identifier_typo` | undeclared or undefined name | rename to the closest declared name |
| `missing_import_python` | stdlib module used but not imported | add `import X` |
| `missing_include_c` | a standard function without its header | add `#include <header>` |

Rules are deliberately narrow. Where the correct fix needs information the error does not contain
(which operand is missing, which argument value is missing, which of two operators was injected),
no rule guesses a value. The compiler check and the confidence order decide between candidates.

---

## 5. Reproducing the numbers

### Setup
```bash
pip install -r requirements.txt
python -m pytest tests -q            # full suite, including 51 analysis tests
```

### Compiler used for the labels
The Data Engineer's records were produced by **gcc 16.1 (MSYS2)**. On macOS, Apple `gcc` is clang, whose
messages differ enough to change the results (for example, `expression is not assignable` instead of
`lvalue required`). For results that match the labels, use gcc 16 from Homebrew:

```bash
brew install gcc                       # provides gcc-16 and g++-16
export GCC_PATH="$PWD/scripts/tools/gcc-macos-sdk.sh"
export GXX_PATH="$PWD/scripts/tools/gxx-macos-sdk.sh"
```

The two wrappers pass `-isysroot "$(xcrun --show-sdk-path)"`. Without it, Homebrew gcc cannot find
`stdio.h` on macOS and reports every program with an `#include` as broken. The wrappers hard-code the
`gcc-16` / `g++-16` names, so edit them if your install differs. On Windows (MSYS2), set `GCC_PATH` and
`GXX_PATH` to the MSYS2 binaries or leave them unset.

### Evaluation
```bash
python scripts/evaluate_analysis.py                    # all four splits
python scripts/evaluate_analysis.py --splits test real_test
```
Writes `reports/analysis_eval.json` (per record) and `reports/analysis_summary.md`.

Gold localization is `mutation.target_location.line` when present, otherwise the first line that differs
from `source_code`. Repair is scored against `source_code`, both exactly and ignoring whitespace.

### Dev frontend (not Streamlit)
```bash
python3 dev_frontend/server.py          # open http://127.0.0.1:8765
```
A single HTML page with a sample picker (mutated programs from the splits), a code box, and panels for
detection, context, repair and the candidate list. It is standard library only and listens on
`127.0.0.1`. It is a test harness; the Systems Engineer's API and UI replace it.

---

## 6. Results (gcc 16, all four splits)

From `reports/analysis_summary.md`:

| Metric | Overall |
|---|---|
| Detection recall | 100.0% |
| Clean sources flagged (60 unique) | 0.0% |
| Category agreement | 73.6% |
| Localization: compiler line | 88.0% |
| Localization: mapped line | 94.9% |
| Localization: mapped line within 1 | 97.2% |
| Repair: fix equals source, ignoring whitespace | 49.5% |
| Repair: fix equals source, exact text | 40.3% |
| Repair: correct fix among candidates | 53.2% |

Per split, repair (ignoring whitespace) is 48.2% on train, 70.0% on val, 37.5% on test and 62.5% on
real_test (5 of 8). The real-bug set is only 8 records, so one record moves its percentage by 12.5 points.

**These numbers are in-sample for the rules.** I wrote the rules while reading error messages from all
four splits. Treat them as the baseline for this rule set, not as held-out accuracy. A fair held-out
check needs fresh mutants and real bugs that nobody has read.

---

## 7. Known limits

- **Repair coverage is the main ceiling.** Of the 109 wrong repairs across the four splits, 101 have no
  correct candidate at all, so they need new rules. The other 8 have the right fix ranked lower, which is
  the only headroom for better ranking. The unsolved families need a value the error message does not
  contain: a missing operand (`MISSING_EXPRESSION_OPERAND`), a missing argument (`MISSING_FUNCTION_ARGUMENT`,
  "too few arguments"), or which of several brackets is missing (`UNMATCHED_PARENTHESIS`,
  `UNMATCHED_OPENING_BRACKET`). These are the ML Engineer's targets.
- **Python category labels are weak.** `invalid syntax` has no subcategory, so Python operator and comma
  errors fall back to `syntax_error`.
- **C and C++ context is lexical**, not a parse. Unusual declarations (function pointers, macros that
  declare names) can be missed in `symbols`.
- **pyright is not used.** The Python type-checking layer is mypy (`layers="full"`). `layers="fast"`
  skips mypy and is what the repair engine uses for its compile checks.
- **Compiler wording varies.** Results depend on the compiler. Compare runs only with the same compiler.
- **The real-bug set is small** (8 records), so its numbers are not statistically meaningful yet.

---

## 8. Integration with the Data Engineer

- Reads `mutated_code`, `source_code`, `language`, `mutation.target_location` and `expected.intended_category`
  from the splits. It never trains on or changes the Data Engineer's files.
- Reuses the Data Engineer's `get_adapter` (compiler invocation and diagnostic parsing), and
  `categorize_diagnostic_message` as the fallback taxonomy.
- It re-runs the compiler rather than reading the stored `diagnostics`, so the layer keeps working on
  new records that do not have stored output.
