# Tactic Failure Troubleshooting Guide

When Lean reports `tactic '<name>' failed`, it means the tactic's heuristic or decision procedure could not close the current goal or transform the tactic state.

---

## 1. Decision Procedure Failures

### Tactic Origin & Import Reference

Before diagnosing decision procedure failures, verify whether the tactic is built into Core Lean or requires a Mathlib import:

| Tactic                        | Origin          | Required Import                                    | Domain                                         |
| :---------------------------- | :-------------- | :------------------------------------------------- | :--------------------------------------------- |
| `omega` (Lean 4.7+ Core)      | **Lean 4 Core** | _None (built-in since Lean 4.7.0)_                 | Presburger arithmetic on `Nat` and `Int`       |
| `linarith`                    | **Mathlib**     | `import Mathlib.Tactic.Linarith`                   | Linear arithmetic on ordered fields (`ℝ`, `ℚ`) |
| `nlinarith`                   | **Mathlib**     | `import Mathlib.Tactic.Nlinarith`                  | Non-linear inequalities via cross products     |
| `positivity`                  | **Mathlib**     | `import Mathlib.Tactic.Positivity`                 | Proving terms are non-negative or positive     |
| `ring` / `ring1`              | **Mathlib**     | `import Mathlib.Tactic.Ring`                       | Equalities in commutative (semi)rings          |
| `gcongr`                      | **Mathlib**     | `import Mathlib.Tactic.GCongr`                     | Monotonic function congruences                 |
| `bv_decide` (Lean 4.12+ Core) | **Lean 4 Core** | _None (built-in since Lean 4.12.0)_                | SAT decision on `BitVec` and `Bool` arithmetic |
| `grind` (Lean 4.16+ / 4.20+)  | **Lean 4 Core** | _None (preview in Lean 4.16.0, stabilized v4.20+)_ | SMT-style mixed constraints and E-matching     |

---

### 1.1 `linarith` Failed _(Mathlib: `import Mathlib.Tactic.Linarith`)_

`linarith` solves linear inequalities over linearly ordered fields/rings (e.g. `ℝ`, `ℚ`).

- **Failure Cause 1: Non-linear terms**. Expressions like `x * y` or `x ^ 2`.
  - _Fix_: Use `nlinarith` which takes non-linear cross products, or prove positivity of factors with `positivity`.
- **Failure Cause 2: Discrete or truncating operations on `ℕ`**. `linarith` treats terms over linearly ordered fields (where subtraction can be negative), failing on natural number identities with truncating subtraction like `a ≤ b → b - a + a = b` or modulo `%`.
  - _Fix_: Use `omega` for natural numbers and integers involving Presburger arithmetic and truncated operations!
- **Failure Cause 3: Missing inequality hypothesis**.
  - _Fix_: If an inequality is hidden in a structure (e.g. `x ∈ Set.Ioo 0 1`), extract it first via `have := x.2`.

---

### 1.2 `omega` Failed _(Lean 4.7+ Core: No Imports Needed)_

`omega` is Lean 4's built-in decision procedure for Presburger arithmetic on `Nat` and `Int`.

> **Note**: `omega` is standard in Lean 4 Core (since 4.7.0). **Do NOT add `import Mathlib.Tactic.Omega`**; it is fully available in pure Lean files without Mathlib dependencies.

- **Failure Cause 1: Real numbers or Floats**. `omega` only works on integers and naturals.
  - _Fix_: Use `linarith` for `ℝ` or `ℚ` (requires `import Mathlib.Tactic.Linarith`).
- **Failure Cause 2: Non-linear terms**. Multiplication between two variables (`a * b`).
  - _Fix_: If one term is a constant, `omega` works (`3 * a`). If both are variables, non-linear reasoning is required (`nlinarith`, `ring`, or custom induction).
- **Failure Cause 3: Division or Modulo**.
  - _Fix_: Pre-simplify with `Nat.div_eq`, `omega` or prove bounds before invoking.

---

### 1.3 `ring` / `ring1` Failed _(Mathlib: `import Mathlib.Tactic.Ring`)_

`ring` verifies identities in commutative (semi)rings using polynomial normalization.

- **Failure Cause 1: Inequalities**. `ring` only proves equalities (`=`).
  - _Fix_: Use `linarith` or `rel` / `gcongr` for inequalities (`≤`, `<`).
- **Failure Cause 2: Division**. `ring` does not invert elements.
  - _Fix_: Clear denominators first, or use `field_simp` before `ring`.
- **Failure Cause 3: Hypotheses not substituted**. `ring` normalizes the goal polynomial, but does NOT look at arbitrary local hypotheses like `h : a + b = c`.
  - _Fix_: Rewrite with local equations first (`rw [h]`), or use `linear_combination h`.

---

### 1.4 `gcongr` Failed _(Mathlib: `import Mathlib.Tactic.GCongr`)_

`gcongr` (generalized congruence) proves inequalities/equalities by peeling off matching monotonic functions.

- **Failure Cause 1: Function monotonicity not registered**.
  - _Fix_: Verify that Mathlib has `@Monotone` or `@StrictMono` lemmas for the operator.
- **Failure Cause 2: Non-matching head symbols**.
  - _Fix_: Ensure left and right sides share the exact same structural template.

---

### 1.5 `grind` Failed _(Lean 4.16+ / 4.20+ Core: No Imports Needed)_

`grind` coordinates congruence closure, E-matching, case-splitting, and arithmetic sub-solvers for mixed-constraint goals.

- **Failure Cause 1: Combinatorial search explosion (Heartbeats / Timeout)**. Unbounded case splitting across branches.
  - _Fix_: Bound or disable splitting with `grind (splits := 0)` to check if simple deduction suffices.
  - Suppress excessive case splits: `grind -splitIte -splitMatch`.
- **Failure Cause 2: Pure single-domain reasoning**. When a goal is strictly linear arithmetic or pure polynomial normalization, `grind`'s general heuristics are slower and may miss specialized proofs.
  - _Fix_: Use `omega` for `ℕ`/`ℤ`, `linarith` for `ℝ`/`ℚ`, or `ring` for commutative rings.
- **Failure Cause 3: Unsimplified context**.
  - _Fix_: Run `simp only [...]` or `simp at *` before `grind`. Use `grind?` to inspect and extract suggested parameters.
- **Failure Cause 4: Abstract Mathlib domains (Analysis, Measure Theory, Topology, etc.)**. Higher-level Mathlib structures often lack custom E-matching attribute registration (`@[grind]`), causing `grind` to loop or fail on goals requiring domain-specific mathematical facts.
  - _Fix_: Do not treat `grind` as an all-purpose solver in abstract Mathlib domains. Revert to domain-specific decision procedures (`omega`, `linarith`, `ring`, `gcongr`) and targeted domain lemmas discovered with `loogle` or `exact?`.

---

## 2. Structural & Proof Search Failures

### 2.1 `exact h` Failed

- **Fix**: Check `type mismatch`. If arguments are missing, switch from `exact` to `refine`:
  ```lean
  refine h ?_ ?_
  ```
  This creates subgoals for the missing arguments instead of crashing.

---

### 2.2 `apply h` Failed

- **Why**: `apply` unifies the conclusion of `h` with the current goal and creates new goals for all hypotheses of `h`.
- If unification fails due to dependent typing or implicit variables:
  - Try `apply @h`
  - Try `refine h _`
  - Check with `apply?` to see if Mathlib has an adapted variant.

---

### 2.3 `aesop` Failed

`aesop` (Automated Extensible Search for Obvious Proofs) searches a rule tree.

- **Fix**:
  - Add missing lemmas locally: `aesop (add safe my_lemma)`.
  - Simplify before calling aesop: `simp; aesop`.
  - If it loops or times out, inspect the rule set with `aesop?`.

---

### 2.4 `constructor` Ambiguity / Warnings (Lean 4.35+)

In Lean 4.35+, `constructor` warns when several constructors match the target type (e.g. `warning: several constructors match, choosing ...`).

- **Fix**: Avoid naked `constructor` when ambiguity exists; use explicit `refine ⟨?_, ?_⟩`, `left`, `right`, or apply the named constructor directly (e.g., `apply And.intro`).

---

### 2.5 `rwa` Failed or Redundant (Lean 4.35+)

- **Cause 1: Goal not closed by rewritten premise**. In Lean 4.35+, `rwa [h]` only succeeds if the rewritten assumption actually closes the goal.
  - _Fix_: If other assumptions are needed to close the goal, separate into `rw [h]; assumption` or `rw [h] <;> assumption`.
- **Cause 2: `linter.unnecessaryRwa` triggered**. If `rw` alone closes the goal without needing `assumption`, Lean 4.35+ flags `rwa` as unnecessary.
  - _Fix_: Replace `rwa` with plain `rw`.

---

## 3. Tactic Selection Cheatsheet

| Target Problem                                      | Primary Tactic                | Fallback / Prerequisite               |
| :-------------------------------------------------- | :---------------------------- | :------------------------------------ |
| Polynomial equality (`a * (b + c) = a * b + a * c`) | `ring`                        | `field_simp` (if division)            |
| Linear inequality on `ℕ` / `ℤ`                      | `omega` (Lean 4.7+ Core)      | `zify` then `linarith`                |
| Linear inequality on `ℝ` / `ℚ`                      | `linarith`                    | `nlinarith` (non-linear)              |
| Bit-Vector / Boolean arithmetic                     | `bv_decide` (Lean 4.12+ Core) | `decide`                              |
| Positivity / non-negativity (`0 < x ^ 2 + 1`)       | `positivity`                  | `norm_num`                            |
| Deep structured equality with matching shape        | `gcongr`                      | `congr!`                              |
| Direct numerical calculation (`2 + 2 = 4`)          | `norm_num`                    | `decide`                              |
| Mixed constraints / cross-domain SMT reasoning      | `grind` (Lean 4.16+ / 4.20+)  | `grind (splits := 0)` / `simp; grind` |
| General logical search                              | `aesop`                       | `tauto`, `clarify`                    |
