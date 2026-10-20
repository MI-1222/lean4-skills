---
name: lean4-syntax
description: Comprehensive syntax guide and fast syntax/elaboration checker for Lean 4 mathematical proofs. Use whenever generating, checking, or repairing Lean 4 proof code, validating snippets or files with `check_syntax.py`, preventing Lean 3 syntax contamination (such as `begin ... end`, trailing commas, `<-`, or invalid `split`), formatting `calc` blocks, managing tactic indentation and focus dots (`·`), or debugging compilation errors.
---

# Lean 4 Syntax & Proof Conventions

This skill provides a canonical syntax reference, indentation guidelines, and an automated verification tool (`check_syntax.py`) for Lean 4 mathematical proofs.

In Lean 4, syntax parsing and type elaboration are tightly coupled. Formatting errors (such as offside rule violations or obsolete Lean 3 syntax) cause fatal compilation errors before any proof search or tactic automation can take place. Follow this guide to produce syntactically robust Lean 4 code.

---

## 1. Quick Syntax Checklist

| Context                | DO (Lean 4 Standard)                  | DON'T (Common Failure)   | Rationale                                                                                                      |
| :--------------------- | :------------------------------------ | :----------------------- | :------------------------------------------------------------------------------------------------------------- |
| **Proof Mode**         | `by`                                  | `begin ... end`          | `begin` is not a keyword in Lean 4; it causes an immediate elaboration error.                                  |
| **Line Ending**        | Newline or `;`                        | Trailing comma `,`       | Tactics are separated by newlines, never commas.                                                               |
| **Rewrite Direction**  | `rw [← h]` (`\l`)                     | `rw [<- h]`              | ASCII `<-` conflicts with monad bind syntax and is rejected by the parser.                                     |
| **Equational Chains**  | `calc a = b := proof`                 | `calc a = b : proof`     | Lean 4 uses assignment `:=` rather than typing `:` for `calc` steps.                                           |
| **Conjunction Goals**  | `constructor` or `refine ⟨?_, ?_⟩`    | `split`                  | In Lean 4, `split` only decomposes `if` and `match` constructs.                                                |
| **Subgoals**           | `· tactic` (`\.`) with +2 spaces      | `{ tactic }`             | Focus dots `·` enforce strict goal isolation and completion.                                                   |
| **Local Proofs**       | `have h : P := by` (+2 spaces)        | `have h : P, from proof` | `from` is retired. In nested `by`, indent tactics deeper than `have`.                                          |
| **Trivial Proofs**     | Term mode (`fun h => h`)              | `:= by exact fun h => h` | Term mode avoids unnecessary tactic state and metavariable overhead.                                           |
| **Identifier Escapes** | `«my-submodule»`, `«def»` (`\<< \>>`) | `my-submodule`           | Hyphens `-` are parsed as subtraction operators. Enclose non-standard names or keywords in guillemets `«...»`. |

---

## 2. Fast Syntax Checker Tool (`scripts/check_syntax.py`)

A standalone CLI tool is bundled in `scripts/check_syntax.py` to validate Lean 4 code snippets, standard input, or full `.lean` files. It features:

1. **Static Lean 3 Deprecation Linter**: Instantly detects obsolete syntax (`begin ... end`, trailing commas, `<-`, bad `split`, etc.).
2. **Compiler Elaboration Validator**: Invokes `lake env lean --json` on a temporary file in `.lake/temp_check/` to report structured errors with exact line and column numbers.

### CLI Usage

```bash
# 1. Check an inline code snippet (with static linter & compiler check)
python3 skills/lean4-syntax/scripts/check_syntax.py -s "theorem my_imp_self (P : Prop) : P → P := fun h => h"

# 2. Check an existing Lean file
python3 skills/lean4-syntax/scripts/check_syntax.py path/to/Proof.lean

# 3. Read snippet from standard input
echo "theorem my_test (p : Prop) (h : p) : p := by exact h" | python3 skills/lean4-syntax/scripts/check_syntax.py --stdin

# 4. Run static Lean 3 linter only (instant, does not invoke Lean compiler)
python3 skills/lean4-syntax/scripts/check_syntax.py --lint-only -s "theorem bad : P := begin sorry end"

# 5. Output structured JSON for automated agent pipelines
python3 skills/lean4-syntax/scripts/check_syntax.py --json -s "theorem bad (p : Prop) : p := by intro h,"
```

### JSON Output Specification

When run with `--json`, the tool returns:

```json
{
  "is_valid": false,
  "has_warnings": false,
  "checked_path": "<snippet>",
  "diagnostics": [
    {
      "severity": "error",
      "line": 1,
      "column": 40,
      "message": "[LEAN3_TRAILING_COMMA] Found trailing comma at end of tactic line...",
      "source": "lean3-linter"
    }
  ],
  "raw_output": ""
}
```

---

## 3. Essential Proof Syntax Patterns

### 3.1. Term Mode vs. Tactic Mode

- **Use Term Mode** for pure term constructions, lambda abstractions, constructor packaging, and direct lemma calls.
- **Use Tactic Mode** (`by`) when navigating multi-step rewrites, induction, or decision procedures (`omega`, `ring`, `aesop`).

```lean
-- Recommended: Pure Term Mode
theorem my_imp_self (P : Prop) : P → P :=
  fun h => h

-- Recommended: Hybrid Tactic & Term Mode
theorem and_comm_proof (P Q : Prop) : P ∧ Q → Q ∧ P := by
  intro h
  have hq : Q := h.right
  have hp : P := h.left
  exact ⟨hq, hp⟩
```

### 3.2. Calculation Chains (`calc`)

- First step: `<lhs> <rel> <intermediate> := <proof>`
- Continuation steps: `_ <rel> <next> := <proof>`
- Always use `:=` (not `:`). The relation `<rel>` must have a `Trans` instance (e.g. `=`, `≤`, `<`, `⊆`, `↔`).

```lean
import Mathlib.Algebra.Ring.Basic

variable (a b c : Nat)

theorem calc_example (h1 : a = b) (h2 : b ≤ c) : a + 1 ≤ c + 1 := by
  calc
    a + 1 = b + 1 := by rw [h1]
    _     ≤ c + 1 := by omega
```

### 3.3. Structured Destructuring (`obtain`, `rcases`)

Avoid multi-step primitive `cases` that create messy variable names (`h_1`, `h_2`).

- **`obtain`**: Destructures conjunctions and existential quantifiers with explicit names.
  ```lean
  theorem obtain_example (h : ∃ x, p x ∧ q x) : ∃ x, q x := by
    obtain ⟨x, _, hq⟩ := h
    exact ⟨x, hq⟩
  ```
- **`rcases`**: Dispatches disjunctions ($P \lor Q$) into pattern arms.
  ```lean
  theorem rcases_example (P Q R : Prop) (h : (P ∧ Q) ∨ R) : P ∨ R := by
    rcases h with ⟨hp, _⟩ | hr
    · left; exact hp
    · right; exact hr
  ```

### 3.4. Identifier Escaping with Guillemets (`«...»`)

In Lean 4, identifiers normally consist of alphanumeric characters and underscores, and cannot start with digits, contain hyphens (`-`), or collide with language keywords. Any arbitrary character sequence can be treated as a valid atomic identifier by enclosing it in French quotation marks (guillemets: `«` and `»`):

- **Hyphenated Module Paths and Imports**:
  When a file system directory or module name contains hyphens (e.g. `my-submodule`), you must escape that component in Lean source files:
  ```lean
  import MathProof.Data.«my-submodule».Basic
  ```
  Without `«...»`, the parser interprets `skills - test` as subtraction, triggering an `unexpected token '-'` or `expected identifier` error.
- **Escaping Reserved Keywords**:
  To use reserved keywords or operator-like strings as names of definitions, variables, or structure fields:
  ```lean
  def «def» : Nat := 42
  def «type» (α : Type) : Type := α
  ```
- **Typing Guillemets in Editors**:
  In VS Code or editors with the Lean 4 extension, type `\<<` for `«` and `\>>` for `»`.

---

## 4. Indentation & Scoping Rules

Lean 4 enforces an **offside rule** based on indentation columns.

### 4.1. Baseline Column in `by` Blocks

The starting column of the first tactic after `by` defines the baseline. All sibling tactics must start at this exact column.

```lean
theorem indent_rule (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  have h1 : p := hp  -- Baseline column = 2
  have h2 : q := hq  -- Must be column 2
  exact ⟨h1, h2⟩     -- Must be column 2
```

### 4.2. Focus Dots (`·`) for Subgoals

When branching into multiple subgoals:

1. Place `·` (`\cdot`) at the same indentation level as the parent command.
2. Indent the enclosed tactics by at least **2 spaces** deeper than `·`.
3. The enclosed block must completely close the subgoal.

```lean
theorem focus_example (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  constructor
  · -- Subgoal 1: ⊢ p
    exact hp
  · -- Subgoal 2: ⊢ q
    exact hq
```

### 4.3. The Nested `have ... := by` Trap

When writing `have ... := by` across multiple lines, the tactic inside `by` **must be indented deeper** than the `have` keyword. If it aligns with or is shallower than `have`, Lean 4 interprets the `by` block as empty and fails with `unexpected token 'have'; expected command`.

```lean
-- Correct
theorem nested_have_correct (p : Prop) (hp : p) : p := by
  have h : p := by
    exact hp   -- Indented deeper than `have`
  exact h
```

---

## 5. Reference Documentation

For detailed specifications and troubleshooting guides, consult the reference files:

- [Lean 3 to Lean 4 Migration Guide](./references/lean3_to_lean4.md): In-depth table of deprecated constructs and error fix patterns.
- [Indentation and Scope Rules](./references/indentation_and_scopes.md): Precise rules of the offside parser, baseline column calculations, and nested macro scoping.
- [Proof Syntax Patterns](./references/proof_syntax_patterns.md): Complete patterns for Term mode, Tactic mode, calculation chains (`calc`), and structural destructuring.
