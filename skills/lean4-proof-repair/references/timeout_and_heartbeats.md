# Heartbeat Exhaustion & Timeout Guide

The error `(deterministic) timeout at '...', maximum number of heartbeats (200000) has been reached` occurs when elaboration, unification, tactic execution, or typeclass synthesis exceeds the deterministic evaluation budget.

---

## 1. Root Causes

Heartbeat exhaustion is almost always caused by:

1. **Unbounded `simp` searches**: An open `simp` searching hundreds of lemmas, or a cyclic simp rewrite loop.
2. **Heavy automation tactics without scope**: `aesop`, `linarith`, or `omega` (Lean 4.7+ Core) running on large hypotheses sets.
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

- **Localized option with a reason**: scope the raise to one declaration and explain it in a comment directly after `in` (Mathlib's linters require both):
  ```lean
  set_option maxHeartbeats 400000 in
  -- `fin_cases` on 64 cases followed by `norm_num` in each branch
  theorem heavy_proof : ... := by ...
  ```
- **Size it by measurement**: with Mathlib imported, `#count_heartbeats in theorem heavy_proof ...` reports the usage and suggests a limit of the form `2^k * 200000`. Do not pick the tightest possible value.
- **Warning**: Do not rely on high heartbeats as a substitute for fixing `simp` loops. If increasing heartbeats to `1000000` still fails, an infinite loop is occurring.
- **Never** raise `maxHeartbeats` file-wide (without `in`) or project-wide just to make failures disappear.

---

### 2.5 Identify Which Limit Was Hit

Not every "too much work" error is about `maxHeartbeats`. Read the message before changing an option:

| Message                                                                             | Limit                            | Default  |
| :---------------------------------------------------------------------------------- | :------------------------------- | :------- |
| `(deterministic) timeout at 'isDefEq' / 'whnf' / ..., maximum number of heartbeats` | `maxHeartbeats`                  | `200000` |
| `failed to synthesize ...` + `(deterministic) timeout at 'typeclass'`               | `synthInstance.maxHeartbeats`    | `20000`  |
| Plain `failed to synthesize instance` for an instance that should exist             | possibly `synthInstance.maxSize` | `128`    |
| `maximum recursion depth has been reached`                                          | `maxRecDepth`                    | `512`    |
| Process aborts with a stack overflow                                                | thread stack (`--tstack`)        | —        |

- Typeclass limits are covered in [instance_synthesis.md](instance_synthesis.md) (Scenario 5).
- For deep recursion from large literal terms or long `decide` computations, a scoped `set_option maxRecDepth N in` is the usual fix; for native stack overflows, the build needs `moreLeanArgs = ["--tstack=<Kb>"]` in the lakefile.
- If the error appears under `lake env lean <file>` but not under `lake build`, the project probably raises the limit in its lakefile `leanOptions`, which `lake env lean` ignores. Re-check with `lake lean <file>`.

See `lean4-best-practice` → `performance_and_heartbeats.md` for the full limit catalog, the scoping policy, and where lakefile options apply.

---

### 2.6 Timeouts Between a Structure and Its Converted Copy

**Symptom**: `exact`, `rfl`, `... .refl` or a field-by-field definition that relates something over `x` to the same thing over `x.convert` times out at `isDefEq` or `whnf`, although the two sides should be definitionally equal. Here `x` is a large structure that appears in the types.

**Diagnose**:

```lean
set_option diagnostics true in
theorem converted_eq : ... := by exact ...
```

In the `unfolded declarations` and `unfolded reducible declarations` lists, projections of the structure and the conversion functions have counts in the thousands or more. The elaborator is spending its budget on unfolding the conversion.

**Fix the design, not the limit**:

1. Index the types and instances on the components they use, so that the conversion does not change them.
2. Where the components are only propositionally equal, state the transport over variables, prove it with `subst`, and supply the equation between the components.

Both patterns, with code, are in `lean4-mathlib-use` → `typeclasses_and_structures.md` §8. In the formalization measured there, one such comparison failed with `maxHeartbeats 4000000`, and neither `with_unfolding_all` nor `set_option smartUnfolding false` rescued it at `1000000`. (A conversion function in the same project did need `smartUnfolding false` for one field, so the option can fix an individual type mismatch.)

**Do not add a tactic that skips the elaborator's check** (`MVarId.assign` without `isDefEq`, or a recursive structure copy built on it). If the code base already has one:

- The kernel still checks the declaration. A wrong term is rejected there with `(kernel) declaration type mismatch`, after the elaborator has accepted the proof script.
- Treat each use as design debt. List the uses (`lean4-cli` → `soundness_and_axiom_audit.md` §4 and §5) and remove them as the indices are fixed.

---

## 3. Loop Debugging Checklist

If heartbeats are exceeded immediately:

1. Does your `simp` attribute a lemma that rewrites `a + b` to `b + a` without guard conditions? (Commutativity loop)
2. Run `set_option trace.Meta.Tactic.simp true` to see which lemma is cycling.
3. Check `set_option trace.Meta.synthInstance true` if the timeout occurs during typeclass resolution.
