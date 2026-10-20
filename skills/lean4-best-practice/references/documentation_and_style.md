# Lean 4 Documentation, Style & Formatting Standards

Writing Lean 4 proofs is not just about satisfying the type checker; formal proofs are mathematical literature meant to be read, maintained, and extended by humans. Following standardized style and documentation conventions is essential for inclusion in Mathlib and long-term project health.

---

## 1. File Header & Module Layout

Lean 4 supports two module header styles: the **Classic Style** (standard across existing Mathlib and legacy projects) and the **Modern Module System** (introduced in Lean 4.16+). Understanding both is essential for navigating existing codebases and adopting modern visibility features.

---

### 1.1 Classic Header Layout (Standard Mathlib & Existing Codebases)

The vast majority of existing Lean 4 repositories and Mathlib files use the traditional import style without the `module` keyword. All imported modules are accessible, and declarations are managed via `open`, `export`, or `private`:

```lean
/-
Copyright (c) 2026 Author Name. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Author Name
-/
import Mathlib.Basic.Real.Basic
import Mathlib.Topology.Basic
import Mathlib.Tactic.Linarith

/-!
# Title of the Module

A high-level description of the mathematical content formalized in this file.
Explain the mathematical concepts, prerequisites, and main contributions.

## Main Definitions

- `MyModule.Def1`: Description of definition.

## Main Theorems

- `MyModule.thm1`: The primary mathematical result.

## Notation

- `⟪x, y⟫`: Inner product notation introduced in this module.

## References

- [Hardy1952] G. H. Hardy, J. E. Littlewood, and G. Pólya, *Inequalities*.
-/

-- Module declarations start here
```

---

### 1.2 Modern Module System Layout (Lean 4.16+)

Starting in Lean 4.16+, Lean introduced a dedicated module system with explicit visibility controls (`module`, `public import`, `public section`). This enables finer encapsulation and reduced transitive dependency leakage:

```lean
/-
Copyright (c) 2026 Author Name. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Author Name
-/
module

public import Mathlib.Basic.Real.Basic
public import Mathlib.Topology.Basic

import Mathlib.Tactic.Linarith

/-!
# Title of the Module

A high-level description of the mathematical content formalized in this file.
-/

public section

-- Public declarations exported to downstream consumers start here

end
```

#### Key Differences in Modern Syntax:

- **`module`**: Explicitly marks the file as a module using the new module system.
- **`public import`**: Re-exports the imported module to any downstream file that imports this module. Use this for libraries whose types or classes appear in your public theorem/definition signatures.
- **`import` (Private Import)**: Keeps the dependency internal to this module. Downstream files importing this module will not automatically inherit this import. Use this for tactics (e.g., `Mathlib.Tactic.Linarith`) or implementation-only helpers.
- **`public section`**: Marks all declarations within the section as public by default.

---

### 1.3 Usage & Migration Guidance: Which Style to Use?

| Context                         | Recommended Style | Rationale                                                                                                                      |
| :------------------------------ | :---------------- | :----------------------------------------------------------------------------------------------------------------------------- |
| **Contributing to Mathlib**     | **Classic Style** | Mathlib currently adheres to the classic header format across its library. Always follow the surrounding codebase conventions. |
| **Existing Community Projects** | **Classic Style** | Unless the project explicitly configured modern module syntax, maintain consistency with the existing headers.                 |
| **New Projects (Lean 4.16+)**   | **Modern Style**  | Take advantage of `public import` vs. `import` to minimize transitive imports and improve modular compilation boundaries.      |

---

### 1.4 Universal Rules for All Headers

Regardless of whether you use the Classic or Modern syntax:

1. **Module Docstring Placement**: The module docstring `/-! ... -/` **must strictly come after all import statements** (or `public import`). Placing a module docstring before imports will trigger an `invalid 'import' command` compile error.
2. **Alphabetical Ordering**: Alphabetize `import` statements within each section to maintain clean git diffs and prevent duplication.
3. **Targeted Imports**: Avoid `import Mathlib` at the top of production files; specify only the minimal submodules required.

---

## 2. Docstrings for Declarations

Every public definition, theorem, and major auxiliary lemma must have a docstring:

```lean
/-- The Cauchy-Schwarz inequality for real inner product spaces:
the absolute value of the inner product of two vectors `x` and `y` is bounded
by the product of their norms. -/
theorem cauchy_schwarz (x y : V) : |⟪x, y⟫| ≤ ‖x‖ * ‖y‖ := by
  ...
```

### Docstring Formatting Guidelines

- Use `/-- ... -/` (note the double hyphen).
- Write full, grammatically sound English sentences.
- Enclose Lean identifiers, types, and variables in backticks: `` `x` ``, `` `Nat.add_comm` ``.
- Summarize the mathematical theorem so that docs generated by `lake build MyLean:docs` or Verso are immediately clear without reading the formal code.

---

## 3. Formatting and Layout Rules

### Rule 1: 100-Character Line Limit

No line should exceed 100 characters.

```lean
-- ✅ GOOD: Broken at natural parameter boundary
theorem long_theorem_statement {α : Type*} [MetricSpace α] [CompactSpace α]
    (f : α → ℝ) (hf : Continuous f) :
    ∃ x, ∀ y, f y ≤ f x := by
  sorry
```

### Rule 2: Tactic Block Indentation & The `by` Keyword

- Always place `by` at the end of the previous line (after `:=`).
- Never put `by` on its own line.
- Indent tactic blocks by 2 spaces.

```lean
-- ✅ GOOD
theorem example_good : 1 + 1 = 2 := by
  rfl

-- ❌ BAD: by on its own line
theorem example_bad : 1 + 1 = 2 :=
  by
  rfl
```

### Rule 3: Strict Focus Dots (`·`) for Subgoals

Whenever a tactic creates multiple subgoals (`cases`, `induction`, `constructor`, `by_cases`), isolate every branch with a focus dot `·`:

```lean
-- ✅ GOOD
by
  by_cases h : x = 0
  · -- Case x = 0
    subst h
    simp
  · -- Case x ≠ 0
    exact h_other h
```

Never write sequential tactics without `·` across multiple branches; doing so obscures which tactic targets which goal.

---

## 4. Calculational Proofs with `calc`

For algebraic transformations, inequalities, or rewrite chains longer than 2 steps, use `calc`. It transforms opaque tactics into transparent mathematical deductions:

```lean
-- ✅ EXCELLENT READABILITY
calc
  (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by ring
  _ ≤ a ^ 2 + (a ^ 2 + b ^ 2) + b ^ 2     := by linarith [two_mul_le_add_sq a b]
  _ = 2 * (a ^ 2 + b ^ 2)                 := by ring
```

### `calc` Formatting & State Alignment Checklist

- **Align with Actual Goal after Simplification**: Never guess the first line of a `calc` chain. If `simp` or `filter_upwards` ran prior to `calc`, start the LHS with the **exact expression present in the goal**, not the pre-simp formula.
- **Respect Canonical Forms**: Work with Mathlib normal forms (e.g., `(m : ℝ)⁻¹` instead of `1 / (m : ℝ)`); do not fight the simplifier with manual reversals.
- Align the relation symbols (`=`, `≤`, `<`, `≥`, `>`).
- Use `_` for continuation terms on the left.
- Provide a concise justification for every line using `:= by ...` or a direct proof term.

---

## 5. Prefer Term Mode for Trivial Proofs

Do not use tactic mode when a clean term-mode expression is more direct:

```lean
-- ✅ ELEGANT: Term mode
theorem add_comm_three (a b c : ℕ) : a + b + c = c + (b + a) :=
  by rw [add_comm a b, add_comm (b + a) c]  -- Tactic mode is fine if rewriting

-- ❌ CLUNKY: Wrapping a single term in `by exact`
theorem trivial_proof (h : P) : P := by
  exact h

-- ✅ CLEAN: Direct term mode
theorem trivial_proof (h : P) : P := h
```
