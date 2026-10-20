# Tactic Failure Troubleshooting Guide

When Lean reports `tactic '<name>' failed`, it means the tactic's heuristic or decision procedure could not close the current goal or transform the tactic state.

---

## 1. Decision Procedure Failures

### 1.1 `linarith` Failed

`linarith` solves linear inequalities over linearly ordered fields/rings (e.g. `ℝ`, `ℚ`).

- **Failure Cause 1: Non-linear terms**. Expressions like `x * y` or `x ^ 2`.
  - _Fix_: Use `nlinarith` which takes non-linear cross products, or prove positivity of factors with `positivity`.
- **Failure Cause 2: Discrete variables (`ℕ` or `ℤ`)**. `linarith` does not know `n > 0 → n ≥ 1` for natural numbers.
  - _Fix_: Use `omega` for natural numbers and integers!
- **Failure Cause 3: Missing inequality hypothesis**.
  - _Fix_: If an inequality is hidden in a structure (e.g. `x ∈ Set.Ioo 0 1`), extract it first via `have := x.2`.

---

### 1.2 `omega` Failed

`omega` is Lean 4's decision procedure for Presburger arithmetic on `Nat` and `Int`.

- **Failure Cause 1: Real numbers or Floats**. `omega` only works on integers and naturals.
  - _Fix_: Use `linarith` for `ℝ` or `ℚ`.
- **Failure Cause 2: Non-linear terms**. Multiplication between two variables (`a * b`).
  - _Fix_: If one term is a constant, `omega` works (`3 * a`). If both are variables, non-linear reasoning is required (`nlinarith`, `ring`, or custom induction).
- **Failure Cause 3: Division or Modulo**.
  - _Fix_: Pre-simplify with `Nat.div_eq`, `omega` or prove bounds before invoking.

---

### 1.3 `ring` / `ring1` Failed

`ring` verifies identities in commutative (semi)rings using polynomial normalization.

- **Failure Cause 1: Inequalities**. `ring` only proves equalities (`=`).
  - _Fix_: Use `linarith` or `rel` / `gcongr` for inequalities (`≤`, `<`).
- **Failure Cause 2: Division**. `ring` does not invert elements.
  - _Fix_: Clear denominators first, or use `field_simp` before `ring`.
- **Failure Cause 3: Hypotheses not substituted**. `ring` normalizes the goal polynomial, but does NOT look at arbitrary local hypotheses like `h : a + b = c`.
  - _Fix_: Rewrite with local equations first (`rw [h]`), or use `linear_combination h`.

---

### 1.4 `gcongr` Failed

`gcongr` (generalized congruence) proves inequalities/equalities by peeling off matching monotonic functions.

- **Failure Cause 1: Function monotonicity not registered**.
  - _Fix_: Verify that Mathlib has `@Monotone` or `@StrictMono` lemmas for the operator.
- **Failure Cause 2: Non-matching head symbols**.
  - _Fix_: Ensure left and right sides share the exact same structural template.

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

## 3. Tactic Selection Cheatsheet

| Target Problem                                      | Primary Tactic | Fallback / Prerequisite    |
| :-------------------------------------------------- | :------------- | :------------------------- |
| Polynomial equality (`a * (b + c) = a * b + a * c`) | `ring`         | `field_simp` (if division) |
| Linear inequality on `ℕ` / `ℤ`                      | `omega`        | `zify` then `linarith`     |
| Linear inequality on `ℝ` / `ℚ`                      | `linarith`     | `nlinarith` (non-linear)   |
| Positivity / non-negativity (`0 < x ^ 2 + 1`)       | `positivity`   | `norm_num`                 |
| Deep structured equality with matching shape        | `gcongr`       | `congr!`                   |
| Direct numerical calculation (`2 + 2 = 4`)          | `norm_num`     | `decide`                   |
| General logical search                              | `aesop`        | `tauto`, `clarify`         |
