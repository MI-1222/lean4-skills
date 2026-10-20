# Heartbeat Exhaustion & Timeout Guide

The error `(deterministic) timeout at '...', maximum number of heartbeats (200000) has been reached` occurs when elaboration, unification, tactic execution, or typeclass synthesis exceeds the deterministic evaluation budget.

---

## 1. Root Causes

Heartbeat exhaustion is almost always caused by:

1. **Unbounded `simp` searches**: An open `simp` searching hundreds of lemmas, or a cyclic simp rewrite loop.
2. **Heavy automation tactics without scope**: `aesop`, `linarith`, or `omega` running on large hypotheses sets.
3. **Deep typeclass synthesis loops**: Conflicting or transitive typeclass instances.
4. **Monolithic proof blocks**: Long proof scripts with accumulated metavariables and huge contexts.

---

## 2. Prescriptions

### 2.1 Minimize `simp` to `simp only`

Unrestricted `simp` evaluates the entire simp lemma set across Mathlib.

- **Diagnostics**: Replace `simp` with `simp?` or `squeeze_simp` to discover the minimal set of lemmas actually used.
- **Fix**: Replace `simp` with `simp only [lemma1, lemma2, ...]`.
- **Use `dsimp`**: If simplifying definitionally equal terms, `dsimp` does not generate proof terms and is orders of magnitude faster:
  ```lean
  dsimp only [my_definition]
  ```

---

### 2.2 Restrict Automation Context (`only`)

Tactics like `linarith` inspect every inequality in the context. In large proofs, this scales combinatorially.

- **Fix**: Pass only the relevant hypotheses:
  ```diff
  - linarith
  + linarith only [h1, h2]
  ```
- For `omega`: If `omega` times out, ensure variables are quantified over `Nat` or `Int` without non-linear operations (like `x * y` where both are variables).

---

### 2.3 Decompose Monolithic Proofs with `have` or Sublemmas

A proof containing 30+ tactic steps accumulates unresolved metavariables and large context graphs that bog down the elaborator.

- Extract intermediate milestones into independent `have` statements:
  ```lean
  have step1 : TargetProperty := by
    -- isolated sub-proof
  ```
- Or extract into a private helper lemma `private lemma helper_step ...`.

---

### 2.4 Control `maxHeartbeats`

If a proof is mathematically valid and near completion, but genuinely computationally intensive (e.g. large finite case exhaustions or heavy polynomial reductions):

- **Localized option**:
  ```lean
  set_option maxHeartbeats 400000 in
  theorem heavy_proof : ... := by ...
  ```
- **Warning**: Do not rely on high heartbeats as a substitute for fixing `simp` loops. If increasing heartbeats to `1000000` still fails, an infinite loop is occurring.

---

## 3. Loop Debugging Checklist

If heartbeats are exceeded immediately:

1. Does your `simp` attribute a lemma that rewrites `a + b` to `b + a` without guard conditions? (Commutativity loop)
2. Run `set_option trace.Meta.Tactic.simp true` to see which lemma is cycling.
3. Check `set_option trace.Meta.synthInstance true` if the timeout occurs during typeclass resolution.
