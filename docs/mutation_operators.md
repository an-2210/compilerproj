# Mutation Operators Specification

The mutation engine implements **15 distinct AST-aware and token-aware mutation operators**.
All operators operate strictly outside comments and string literals, maintain deterministic seeding, and introduce exactly one controlled syntactic or semantic error.

---

## Operator Summary Table

| # | Operator ID | Supported Languages | Error Category | Subcategory |
|---|---|---|---|---|
| 1 | `C_MISSING_SEMICOLON` | C, C++ | `delimiter_punctuation` | `missing_semicolon` |
| 2 | `C_EXTRA_SEMICOLON` | C, C++ | `delimiter_punctuation` | `extra_semicolon` |
| 3 | `UNMATCHED_OPENING_BRACKET` | C, C++, Python | `delimiter_punctuation` | `unmatched_bracket` |
| 4 | `UNMATCHED_CLOSING_BRACKET` | C, C++, Python | `delimiter_punctuation` | `unmatched_bracket` |
| 5 | `UNMATCHED_PARENTHESIS` | C, C++, Python | `delimiter_punctuation` | `unmatched_parenthesis` |
| 6 | `MISSING_CLOSING_BRACE` | C, C++ | `delimiter_punctuation` | `missing_brace` |
| 7 | `ARITHMETIC_OPERATOR_MUTATION` | C, C++, Python | `expression_operator` | `invalid_expression_operator` |
| 8 | `COMPARISON_OPERATOR_MUTATION` | C, C++, Python | `expression_operator` | `invalid_comparison` |
| 9 | `ASSIGNMENT_VS_EQUALITY_MUTATION` | C, C++, Python | `expression_operator` | `invalid_assignment_target` |
| 10 | `MISSING_EXPRESSION_OPERAND` | C, C++, Python | `expression_operator` | `missing_operand` |
| 11 | `MISSING_DELIMITER_COMMA` | C, C++, Python | `delimiter_punctuation` | `missing_comma` |
| 12 | `IDENTIFIER_MISSPELLING` | C, C++, Python | `declaration_identifier` | `undeclared_identifier` |
| 13 | `EXTRA_FUNCTION_ARGUMENT` | C, C++, Python | `function_call_argument` | `too_many_arguments` |
| 14 | `MISSING_FUNCTION_ARGUMENT` | C, C++, Python | `function_call_argument` | `too_few_arguments` |
| 15 | `PYTHON_INDENTATION_ERROR` | Python | `indentation_block` | `indentation_error` |

---

## Detailed Operator Specifications

### 1. `C_MISSING_SEMICOLON`
- **Precondition:** Statement terminator `;` outside comments/strings exists.
- **Transformation:** Deletes a selected `;`.
- **Compiler Diagnostic:** GCC: `expected ';' before '}' token` or `expected ';' at end of input`.

### 2. `C_EXTRA_SEMICOLON`
- **Precondition:** Expression operator (`=`, `+`, `-`, `*`) exists.
- **Transformation:** Inserts `;` immediately adjacent to the operator (e.g. `x = ; 5;`).
- **Compiler Diagnostic:** GCC: `expected expression before ';' token`.

### 3. `UNMATCHED_OPENING_BRACKET`
- **Precondition:** Closing bracket `]` exists.
- **Transformation:** Deletes `]`, leaving unmatched `[`.
- **Compiler Diagnostic:** GCC: `expected ']' before ';' token`; Python: `SyntaxError: closing parenthesis ']' does not match`.

### 4. `UNMATCHED_CLOSING_BRACKET`
- **Precondition:** Enclosing delimiter or bracket exists.
- **Transformation:** Inserts extraneous closing bracket `]`.
- **Compiler Diagnostic:** GCC: `expected statement before ']' token`; Python: `SyntaxError: unmatched ']'`.

### 5. `UNMATCHED_PARENTHESIS`
- **Precondition:** Closing parenthesis `)` exists outside comments/strings.
- **Transformation:** Deletes `)`.
- **Compiler Diagnostic:** GCC: `expected ')' before '{' token`; Python: `SyntaxError: was never closed`.

### 6. `MISSING_CLOSING_BRACE`
- **Precondition:** Closing brace `}` exists outside comments/strings.
- **Transformation:** Deletes the final file-level closing brace `}`.
- **Compiler Diagnostic:** GCC: `expected declaration or statement at end of input`.

### 7. `ARITHMETIC_OPERATOR_MUTATION`
- **Precondition:** Binary operator (`+`, `-`, `*`, `/`, `%`) exists.
- **Transformation:** Juxtaposes an illegal second operator (e.g. `+ *` or `* /`).
- **Compiler Diagnostic:** GCC: `expected expression before '*' token`; Python: `SyntaxError: invalid syntax`.

### 8. `COMPARISON_OPERATOR_MUTATION`
- **Precondition:** Comparison operator (`<`, `>`, `<=`, `>=`) outside preprocessor directives.
- **Transformation:** Mutates to invalid comparison syntax `= <`.
- **Compiler Diagnostic:** GCC: `expected expression before '<' token`; Python: `SyntaxError: invalid syntax`.

### 9. `ASSIGNMENT_VS_EQUALITY_MUTATION`
- **Precondition:** Assignment or equality operator exists.
- **Transformation:** In Python, changes `==` to `=` in conditional. In C/C++, inserts chained rvalue `= 100 =`.
- **Compiler Diagnostic:** Python: `SyntaxError: invalid syntax. Maybe you meant '=='?`; GCC: `lvalue required as left operand of assignment`.

### 10. `MISSING_EXPRESSION_OPERAND`
- **Precondition:** Binary operator followed by an operand.
- **Transformation:** Deletes the right-hand operand, leaving a dangling operator.
- **Compiler Diagnostic:** GCC: `expected expression before ';' token`; Python: `SyntaxError: invalid syntax`.

### 11. `MISSING_DELIMITER_COMMA`
- **Precondition:** Comma `,` separator in argument list or array initializer exists.
- **Transformation:** Removes the comma delimiter.
- **Compiler Diagnostic:** GCC: `expected ')' before numeric constant`; Python: `SyntaxError: invalid syntax`.

### 12. `IDENTIFIER_MISSPELLING`
- **Precondition:** Non-keyword variable or function identifier.
- **Transformation:** Appends `_undeclared_id` to the identifier.
- **Compiler Diagnostic:** GCC: `'var_undeclared_id' undeclared`; G++: `'var_undeclared_id' was not declared in this scope`.

### 13. `EXTRA_FUNCTION_ARGUMENT`
- **Precondition:** Function call invocation exists.
- **Transformation:** Appends `, 99999` to the call argument list.
- **Compiler Diagnostic:** GCC: `too many arguments to function 'func'`.

### 14. `MISSING_FUNCTION_ARGUMENT`
- **Precondition:** Multi-argument function call exists.
- **Transformation:** Removes all arguments except the first one.
- **Compiler Diagnostic:** GCC: `too few arguments to function 'func'`.

### 15. `PYTHON_INDENTATION_ERROR`
- **Precondition:** Indented Python block (4 spaces).
- **Transformation:** Corrupts indentation level (e.g. 3 spaces or 1 space).
- **Compiler Diagnostic:** Python: `IndentationError: unindent does not match any outer indentation level`.
