---
name: lean4-mathlib-use
description: >-
  Comprehensive guide for effectively utilizing Mathlib libraries, structures, and conventions in Lean 4. Use whenever managing Mathlib imports (avoiding monolithic `import Mathlib`, selecting domain-specific submodules, running `lake shake`), navigating mathematical structures and typeclass hierarchies (`autoImplicit false`, explicit type annotations, `haveI`/`letI` instance injection, resolving instance loops), handling partial functions with Mathlib's total function design (junk values for `0 / 0`, `deriv`, `tsum`, `sSup`, establishing side conditions like `h : y ≠ 0` or `DifferentiableAt`), managing classical logic and scoping (`open scoped Classical in`, `classical` tactic, avoiding `openClassical` linter errors, `noncomputable section`), or selectively enabling mathematical notations (`open scoped BigOperators Pointwise`).
---

# Lean 4 Mathlib Usage Guide

This skill provides an authoritative guide for AI agents and human practitioners on navigating and leveraging the Mathlib mathematical library efficiently, cleanly, and without compilation bottlenecks.

---

## 1. The Four Pillars of Mathlib Usage

Adhering to these four foundational practices ensures maintainable, performant, and linter-compliant formalizations across Mathlib:

```text
                  +-----------------------------------------------+
                  |        Lean 4 Mathlib Usage Principles        |
                  +-----------------------+-----------------------+
                                          |
        +-------------------+-------------+-------------+--------------------+
        |                   |                           |                    |
        v                   v                           v                    v
 [1. Minimal Imports] [2. Typeclass Guiding]    [3. Junk Value Hygiene] [4. Classical Scoping]
  No `import Mathlib`  `autoImplicit false`      Total function design   `open scoped Classical in`
  Domain submodules    Explicit type anchors     Side conditions early   `classical` tactic
  `lake shake --fix`   `haveI` / `letI` inject   `₀` subscript lemmas    `open scoped` notations
```

1. **Minimal & Targeted Imports**: Never rely on monolithic `import Mathlib`. Select domain-specific modules (`.Defs`, `.Basic`) to minimize elaboration footprint and cache invalidation. Prune redundant imports using `lake shake`.
2. **Typeclass Hierarchy Control**: Guard against invisible dependency explosions and ambiguous synthesis paths. Disable `autoImplicit`, pin numeric literals with explicit type annotations (e.g., `(0 : ℝ)`), and supply missing context with `haveI` / `letI`.
3. **Total Function & Junk Value Discipline**: Recognize that Mathlib assigns default values (junk values) to classically undefined expressions (e.g., $x / 0 = 0$, non-differentiable derivatives = $0$). Formulate side conditions (`y ≠ 0`, `DifferentiableAt`, `Summable`) before attempting rewrites or cancellations (`mul_div_cancel₀`).
4. **Scoped Classical Logic & Notations**: Respect the `openClassical` style linter. Confine classical logic to individual theorems (`open scoped Classical in`) or tactic blocks (`classical`). Use `open scoped` for notations (`BigOperators`, `Pointwise`) to avoid namespace pollution.

---

## 2. Fast Mathlib Authoring Checklist

Before running verification or committing code that uses Mathlib, check against this list:

### Stage A: Module Imports & Toolchain

- [ ] **No Monolithic Imports**: Is the file free of `import Mathlib`? Are imports restricted to minimal submodules (e.g., `Mathlib.Data.Real.Basic`, `Mathlib.Tactic.Linarith`)?
- [ ] **Binary Cache Synchronized**: Has `lake exe cache get` been executed to avoid rebuilding dependencies from source?
- [ ] **Pruned Dependencies**: Has `lake exe shake` (or `lake exe shake --fix`) been run to eliminate unused transitive modules?

### Stage B: Elaboration & Typeclass Settings

- [ ] **`autoImplicit` Disabled**: Is `set_option autoImplicit false` active to prevent accidental free variables?
- [ ] **Anchored Types**: Are numeric constants and expressions with coercions explicitly type-annotated (e.g., `(0 : ℝ)`, `(n : ℝ)`)?
- [ ] **Instance Injection**: If typeclass resolution fails or loops, is `haveI` or `letI` used to supply the missing structure locally?

### Stage C: Hypotheses & Domain Validity

- [ ] **Non-Zero Conditions**: When performing division or inverses in fields, is the non-zero hypothesis (`h : y ≠ 0`) established and the `₀`-subscript lemma used (`mul_inv_cancel₀`)?
- [ ] **Calculus / Analysis Prerequisites**: When differentiating or summing series, are domain proofs (`DifferentiableAt`, `Summable`, `ContinuousAt`) proven before applying algebraic formulas?

### Stage D: Classical Scoping & Notation

- [ ] **Linter-Compliant Classical Logic**: Is classical logic scoped via `open scoped Classical in` (for declarations) or `classical` (in tactics), avoiding global `open Classical`?
- [ ] **Noncomputable Section**: If constructing noncomputable mathematical data with `Classical.choice`, is the section marked `noncomputable section`?
- [ ] **Scoped Notations**: Are notations activated via `open scoped BigOperators Pointwise` rather than global `open` statements?

---

## 3. Progressive Reference Guides

For comprehensive technical explanations, domain-by-domain modules, and code patterns, consult the detailed references:

| Topic                               | Key Techniques & Best Practices                                                                                                    | Reference Guide                                                                         |
| :---------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------- |
| **Minimal Imports & Shake**         | Eliminating `import Mathlib`, domain submodule catalog, `lake exe cache get`, running `lake shake --fix`                           | [minimal_imports_and_shake.md](references/minimal_imports_and_shake.md)                 |
| **Typeclasses & Structures**        | Multiple inheritance, invisible dependencies, `autoImplicit false`, type pinning, `haveI`/`letI` local instances                   | [typeclasses_and_structures.md](references/typeclasses_and_structures.md)               |
| **Junk Values & Partial Functions** | Total functions in type theory, junk values table ($x/0$, `deriv`, `tsum`, `sSup`), subscript-`₀` convention, domain preconditions | [junk_values_and_partial_functions.md](references/junk_values_and_partial_functions.md) |
| **Classical Logic & Scoping**       | `openClassical` style linter, single-declaration scoping, `classical` tactic, `noncomputable section`, `open scoped` notations     | [classical_logic_and_scoping.md](references/classical_logic_and_scoping.md)             |

---

## 4. Synergy with Lean 4 Skills Ecosystem

`lean4-mathlib-use` coordinates with the full suite of specialized Lean 4 skills:

```text
                     [lean4-mathlib-use]
              (Imports, Typeclasses, Classical)
                             |
         +-------------------+-------------------+
         |                                       |
         v                                       v
[lean4-mathlib-search]                 [lean4-best-practice]
  Find exact lemma names                 Proof structure & tactics
  via Loogle & signatures                (`simp` rules, `calc` chains)
         |                                       |
         +-------------------+-------------------+
                             |
                             v
                 [lean4-interactive-proof]
                   Goal exploration with
                   `scripts/lean_goal.py`
                             |
                             v
                    [lean4-proof-repair]
                 Diagnose type mismatches &
                 failed rewrites / timeouts
                             |
                             v
                        [lean4-cli]
                 Fast module checks via
                 `lake env lean` & diagnostics
```

- **Before Searching**: Configure minimal imports with `skills/lean4-mathlib-use` so search tools like `skills/lean4-mathlib-search` operate on focused namespaces.
- **During Proving**: Use `skills/lean4-interactive-proof` to test local state transitions and verify side conditions for partial functions.
- **Applying Best Practices**: Structure proofs according to `skills/lean4-best-practice` (`calc` mode, `have` decomposition) while adhering to `lean4-mathlib-use` import and scoping rules.
- **Handling Errors**: If typeclass synthesis or rewrites fail, diagnose and fix them using `skills/lean4-proof-repair`.
- **Validation**: Run fast checks and full builds using `skills/lean4-cli`.
