---
name: lean4-mathlib-use
description: >-
  Guide to Mathlib's libraries, structures and conventions in Lean 4. Use whenever choosing Mathlib imports (`import Mathlib` versus targeted submodules and the trade-off between them, pruning with `lake shake`), working with typeclass hierarchies (`autoImplicit false`, explicit type annotations, anonymous `have` instances over deprecated `haveI`, ambient instance pinning, `omit [...] in`, instance loops), handling Mathlib's total functions (junk values for `0 / 0`, `deriv`, `tsum`, `sSup`; side conditions such as `y ≠ 0` or `DifferentiableAt`), scoping classical logic (`open scoped Classical in`, `classical`, the `openClassical` linter, `noncomputable section`), enabling notation (`open scoped BigOperators Pointwise`), or applying domain patterns in analysis, measure theory (`Integrable.of_bound`, `ae_of_all`, `filter_upwards`, measurability), geometry (`Sbtw.sbtw_lineMap_iff`, `Real.Angle`) and algebra (`gcongr`, `field_simp`, `positivity`).
compatibility: Target Lean 4.14.0+ and Mathlib v4.14.0+ (Verified on Lean v4.35.0 and contemporary Mathlib).
metadata:
  target-lean-version: '>=4.14.0'
  tested-lean-version: 'v4.35.0'
  tested-mathlib-version: 'v4.35.0'
  version: '1.3.0'
---

# Lean 4 Mathlib Usage Guide

This skill provides an authoritative guide for AI agents and human practitioners on navigating and leveraging the Mathlib mathematical library efficiently, cleanly, and without compilation bottlenecks.

---

## 0. Environment & Version Compatibility

| Component   | Target / Supported  | Verified / Tested Version             | Notes                                                     |
| :---------- | :------------------ | :------------------------------------ | :-------------------------------------------------------- |
| **Lean 4**  | `^4.14.0` (4.14.0+) | `v4.35.0` (Release, commit `eb6cafb`) | Verified against modern Mathlib module structures         |
| **Mathlib** | `v4.14.0`+          | Contemporary with Lean `v4.35.0`      | Uses scoped classical opening and per-file import choices |

### Version-Specific Conventions

- **Import Pruning**: Prune targeted imports via `lake exe shake`.
- **Classical Scoping**: Use `open scoped Classical in` instead of global `open Classical` to satisfy Mathlib linters.
- **Instance Management**: Use plain anonymous `have` (Lean 4.14+) rather than `haveI` (deprecated since Lean 4.14), and `omit [...] in` (Lean 4.11+) to control instance scope.

---

## 1. The Five Pillars of Mathlib Usage

Adhering to these five foundational practices ensures maintainable, performant, and linter-compliant formalizations across Mathlib:

```mermaid
graph TD
    Root["Lean 4 Mathlib Usage Principles"]
    Root --> P1["1. Imports by Purpose<br/>`import Mathlib` vs targeted submodules / `lake shake`"]
    Root --> P2["2. Typeclass Guiding<br/>`autoImplicit false` / Explicit type anchors / Plain `have` (Lean 4.14+) & `omit` (Lean 4.11+)"]
    Root --> P3["3. Junk Value Hygiene<br/>Total function design / Side conditions early / `₀` subscript lemmas"]
    Root --> P4["4. Classical Scoping<br/>`open scoped Classical in` / `classical` tactic / `open scoped` notations"]
    Root --> P5["5. Domain Patterns<br/>Automation triage / `omega` (Lean 4.7+ Core), `linarith`, `gcongr` / Measure theory `ae`"]
```

1. **Imports Chosen by Purpose**: `import Mathlib` costs memory and load time in every process that checks the file (10,498 modules and 4–5.7 GB, against 2,382 modules and 1.5 GB for two targeted imports, on Mathlib `v4.33.1`), but it causes no extra rebuilds and gives every file the same environment. Use targeted submodules (`.Defs`, `.Basic`) for code that goes to Mathlib or that other modules import, and prune them with `lake shake`. `import Mathlib` is acceptable for scratch files and exploration.
2. **Typeclass & Instance Control**: Guard against invisible dependency explosions, ambiguous synthesis paths, and instance pollution. Disable `autoImplicit`, pin numeric literals with explicit type annotations (e.g., `(0 : ℝ)`), register local instances using standard `have : C := ⟨pf⟩` (Lean 4.14+) (avoiding legacy `haveI` (deprecated since Lean 4.14)), pin ambient instances when defining sub-structures, and exclude unwanted section variables with `omit [...] in` (Lean 4.11+).
3. **Total Function & Junk Value Discipline**: Recognize that Mathlib assigns default values (junk values) to classically undefined expressions (e.g., $x / 0 = 0$, non-differentiable derivatives = $0$). Formulate side conditions (`y ≠ 0`, `DifferentiableAt`, `Summable`) before attempting rewrites or cancellations (`mul_div_cancel₀`).
4. **Scoped Classical Logic & Notations**: Respect the `openClassical` style linter. Confine classical logic to individual theorems (`open scoped Classical in`) or tactic blocks (`classical`). Use `open scoped` for notations (`BigOperators`, `Pointwise`) to avoid namespace pollution.
5. **Domain-Specific Patterns & Triage**: Select targeted decision procedures before manual rewrites (`omega` (Lean 4.7+ Core) for $\mathbb{N}/\mathbb{Z}$, `linarith` for $\mathbb{R}/\mathbb{Q}$, `gcongr` for relational congruence, `positivity` for nonnegativity). Apply verified domain conventions (e.g., `Integrable.of_bound` with `ae_of_all`, `filter_upwards` for almost everywhere hypotheses, `measurability` and `fun_prop` for function properties).

---

## 2. Fast Mathlib Authoring Checklist

Before running verification or committing code that uses Mathlib, check against this list:

### Stage A: Module Imports & Toolchain

- [ ] **Imports Fit the File's Purpose**: Does code meant for Mathlib, or for other modules to import, use targeted submodules (e.g., `Mathlib.Basic.Real.Basic`, `Mathlib.Tactic.Linarith`)? Where `import Mathlib` remains, is its per-process cost acceptable (scratch files, exploration, or a project that chose it deliberately)?
- [ ] **Binary Cache Synchronized**: Has `lake exe cache get` been executed to avoid rebuilding dependencies from source?
- [ ] **Pruned Dependencies**: Has `lake shake` (or `lake shake --fix`) been run to eliminate unused transitive modules? _(Note: `lake shake` requires standard module identifier paths and fails on paths with hyphens or non-modules; see [minimal_imports_and_shake.md](references/minimal_imports_and_shake.md))_

### Stage B: Elaboration & Typeclass Settings

- [ ] **`autoImplicit` Disabled**: Is `set_option autoImplicit false` active to prevent accidental free variables?
- [ ] **Anchored Types**: Are numeric constants and expressions with coercions explicitly type-annotated (e.g., `(0 : ℝ)`, `(n : ℝ)`)?
- [ ] **Modern Instance Injection**: If typeclass resolution fails, is standard `have : C := pf` (Lean 4.14+) used (avoiding deprecated `haveI` (deprecated since Lean 4.14) which triggers linter warnings)?
- [ ] **Instance Pollution Guarded**: When working with sub-structures (e.g. `MeasurableSpace`, `MetricSpace`, `Preorder`), is the ambient instance pinned (`[m0 : ...]`) and ambient facts passed via `@`? Are unneeded ambient section variables excluded with `omit [...] in` (Lean 4.11+)?

### Stage C: Hypotheses & Domain Validity

- [ ] **Non-Zero Conditions**: When performing division or inverses in fields, is the non-zero hypothesis (`h : y ≠ 0`) established and the `₀`-subscript lemma used (`mul_inv_cancel₀`)?
- [ ] **Calculus / Analysis Prerequisites**: When differentiating or summing series, are domain proofs (`DifferentiableAt`, `Summable`, `ContinuousAt`) proven before applying algebraic formulas?

### Stage D: Classical Scoping & Notation

- [ ] **Linter-Compliant Classical Logic**: Is classical logic scoped via `open scoped Classical in` (for declarations) or `classical` (in tactics), avoiding global `open Classical`?
- [ ] **Noncomputable Section**: If constructing noncomputable mathematical data with `Classical.choice`, is the section marked `noncomputable section`?
- [ ] **Scoped Notations**: Are notations activated via `open scoped BigOperators Pointwise` rather than global `open` statements?

### Stage E: Domain Patterns & Automation Triage

- [ ] **Right Tactic Selected**: Is `omega` (Lean 4.7+ Core) used for $\mathbb{N}/\mathbb{Z}$, `linarith` for $\mathbb{R}/\mathbb{Q}$, `ring` for polynomials, `positivity` for $>0/\ge 0$, and `gcongr` for sum/integral inequalities?
- [ ] **Measure Theory Conventions**: Is integrability proven via bounded+measurable (`Integrable.of_bound`), `ae` properties combined via `filter_upwards`, and measurability discharged via `measurability` / `fun_prop`?

---

## 3. Progressive Reference Guides

For comprehensive technical explanations, domain-by-domain modules, and code patterns, consult the detailed references:

| Topic                               | Key Techniques & Best Practices                                                                                                                          | Reference Guide                                                                         |
| :---------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------- |
| **Minimal Imports & Shake**         | Eliminating `import Mathlib`, domain submodule catalog, `lake exe cache get`, running `lake shake --fix`                                                 | [minimal_imports_and_shake.md](references/minimal_imports_and_shake.md)                 |
| **Typeclasses & Structures**        | Multiple inheritance, invisible dependencies, `autoImplicit false`, plain `have` (Lean 4.14+), avoiding instance pollution, `omit [...] in` (Lean 4.11+) | [typeclasses_and_structures.md](references/typeclasses_and_structures.md)               |
| **Junk Values & Partial Functions** | Total functions in type theory, junk values table ($x/0$, `deriv`, `tsum`, `sSup`), subscript-`₀` convention, domain preconditions                       | [junk_values_and_partial_functions.md](references/junk_values_and_partial_functions.md) |
| **Classical Logic & Scoping**       | `openClassical` style linter, single-declaration scoping, `classical` tactic, `noncomputable section`, `open scoped` notations                           | [classical_logic_and_scoping.md](references/classical_logic_and_scoping.md)             |
| **Domain-Specific Patterns**        | Analysis, measure theory (`Integrable.of_bound`, `ae_of_all`), geometry betweenness (`Sbtw`), algebra automation (`gcongr`, `ring`)                      | [domain_specific_patterns.md](references/domain_specific_patterns.md)                   |

---

## 4. Synergy with Lean 4 Skills Ecosystem

`lean4-mathlib-use` coordinates with the full suite of specialized Lean 4 skills:

```mermaid
graph TD
    A["lean4-mathlib-use<br/>Imports, Typeclasses, Classical"] --> B["lean4-mathlib-search<br/>Find exact lemma names via Loogle & signatures"]
    A --> C["lean4-best-practice<br/>Proof structure & tactics （`simp` rules, `calc` chains）"]
    B --> D["lean4-interactive-proof<br/>Goal exploration with `scripts/lean_goal.py`"]
    C --> D
    D --> E["lean4-proof-repair<br/>Diagnose type mismatches & failed rewrites / timeouts"]
    E --> F["lean4-cli<br/>Fast module checks via `lake env lean` & diagnostics"]
```

- **Before Searching**: Inline search tactics (`exact?`, `apply?`, `rw?`) only see imported modules, while Loogle and LeanSearch in `lean4-mathlib-search` cover all of Mathlib. Choose the tool with that in mind.
- **During Proving**: Use `lean4-interactive-proof` to test local state transitions and verify side conditions for partial functions.
- **Applying Best Practices**: Structure proofs according to `lean4-best-practice` (`calc` mode, `have` decomposition) while adhering to `lean4-mathlib-use` import and scoping rules.
- **Handling Errors**: If typeclass synthesis or rewrites fail, diagnose and fix them using `lean4-proof-repair`.
- **Validation**: Run fast checks and full builds using `lean4-cli`.
