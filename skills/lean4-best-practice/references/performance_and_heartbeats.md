# Performance and Heartbeat Optimization in Lean 4

Elaboration timeouts (`(deterministic) timeout at 'whnf', maximum number of heartbeats (200000) has been reached`) and slow type-checking are common obstacles in large proofs. This guide covers the resource limits Lean enforces, a policy for raising them, how to diagnose performance bottlenecks, and principled optimizations.

---

## 1. What are "Heartbeats"?

In Lean 4, a "heartbeat" is a deterministic measure of computational work, independent of CPU clock speed: the option value counts (small) memory allocations **in thousands**.

- The default `maxHeartbeats` limit is **200,000** per command (one declaration is one command).
- `0` means no limit. Never use it outside throwaway experiments.
- If a single theorem exceeds 200,000 heartbeats, it usually indicates an exponential search, a typeclass resolution loop, or massive definitional unfolding.

---

## 2. Policy: Aim for Zero, Scope Narrowly

Raising a limit hides the cause, slows every build, and breaks again when nearby code or Mathlib changes. Mathlib treats it as technical debt: its library code (Mathlib `v4.33.1`, about 8,300 files) contains **no** `set_option maxHeartbeats` overrides at all, and its linters enforce the rules below. Large downstream projects behave very differently; one formalization of about 175,000 files contained over 57,000 `set_option maxHeartbeats` lines. Overrides accumulate quickly once they are allowed without rules.

### The Rules

1. **Fix the cause first.** Work through §5 (open `simp`, defeq unfolding, instance search, heavy automation) before touching any limit.
2. **If a raise is genuinely needed, scope it to one declaration** with `set_option ... in`, and **explain why in a comment** right after `in`:

   ```lean
   set_option maxHeartbeats 400000 in
   -- `fin_cases` on 64 cases followed by `norm_num` in each branch
   theorem heavy_case_check : ... := by ...
   ```

   Mathlib's `setOption` linter warns about `maxHeartbeats` options that are not scoped with `in`, and its `linter.style.maxHeartbeats` linter flags scoped ones that lack an explanatory comment.

3. **Measure instead of guessing.** With Mathlib imported, `#count_heartbeats in` reports what a declaration uses and suggests (via "Try this:") the smallest limit of the form `2^k * 200000` that suffices:

   ```lean
   #count_heartbeats in
   theorem heavy_case_check : ... := by ...
   ```

   Do not set the limit as low as possible: unrelated changes to the `simp` set will push the declaration over a tight limit. Inside a proof, `#count_heartbeats tac` measures a single tactic sequence.

4. **Never raise limits file-wide or project-wide to silence failures.** Wider scopes hide new slow proofs as they appear.

### Scope Ladder

| Scope                | How                                                     | When it is acceptable                                                       |
| :------------------- | :------------------------------------------------------ | :-------------------------------------------------------------------------- |
| **One declaration**  | `set_option maxHeartbeats N in` + comment               | Default choice for a justified raise                                        |
| **Rest of the file** | `set_option maxHeartbeats N` (no `in`)                  | Avoid; Mathlib lints against it                                             |
| **One library**      | `leanOptions` in a `[[lean_lib]]` block of the lakefile | Project-wide settings that differ from Lean's defaults, chosen deliberately |
| **Whole package**    | `[leanOptions]` / `leanOptions :=` on the package       | Same as above, e.g. Mathlib's `maxSynthPendingDepth := 3`                   |

---

## 3. Resource Limits and Their Error Messages

Lean enforces several independent limits. Raising the wrong one does nothing, so identify the limit from the error message first:

| Limit                          | Default           | Scope                                        | Error message when exceeded                                                                                   |
| :----------------------------- | :---------------- | :------------------------------------------- | :------------------------------------------------------------------------------------------------------------ |
| `maxHeartbeats`                | `200000`          | Per command                                  | `(deterministic) timeout at 'isDefEq' / 'whnf' / ..., maximum number of heartbeats (200000) has been reached` |
| `synthInstance.maxHeartbeats`  | `20000`           | Per typeclass resolution problem             | `failed to synthesize ...` followed by `(deterministic) timeout at 'typeclass', maximum number of heartbeats` |
| `synthInstance.maxSize`        | `128`             | Instances used to build one solution         | Plain `failed to synthesize instance of type class` (**the limit is not named**)                              |
| `maxSynthPendingDepth`         | `1`               | Nested typeclass problems during unification | Usually a plain synthesis or unification failure                                                              |
| `maxRecDepth`                  | `512`             | Recursion depth of many Lean procedures      | `maximum recursion depth has been reached`                                                                    |
| Thread stack size (`--tstack`) | OS / Lean default | Native stack of each Lean thread             | The process aborts with a stack overflow                                                                      |

Notes:

- `maxHeartbeats` and `synthInstance.maxHeartbeats` are measured in thousands of allocations; the error message names the option to change (`Note: Use 'set_option synthInstance.maxHeartbeats <num>' ...`).
- A `synthInstance.maxSize` failure looks exactly like a missing instance. If an instance that should exist is "not found" for a deep or highly nested type, check whether this limit is the cause before adding instances.
- `maxSynthPendingDepth` limits how many nested typeclass problems may be spawned while solving unification constraints. Lean's default is `1`; Mathlib builds with `3` (set in its lakefile). A project may also do the same and lower it back to `1` in individual files where the deeper search is slow.
- The thread stack size is a command-line flag, not an option: `lean --tstack=<Kb>`. In a lakefile, pass it with `moreLeanArgs = ["--tstack=400000"]` (about 400 MB per thread). Raise it only when a build aborts with a stack overflow on very deep terms.

---

## 4. Profiling Slow Proofs

To find the exact line causing the slowdown, enable Lean's built-in profiler:

```lean
set_option trace.profiler true in
theorem my_theorem : ... := by
  step1
  step2
```

Or enable detailed compiler diagnostics:

```lean
set_option diagnostics true in
theorem my_theorem : ... := by
  ...
```

The diagnostics report will display:

- Time spent in elaboration vs type-checking.
- Heartbeats consumed by each tactic invocation.
- Number of typeclass resolution queries and instances synthesized.

Remove `trace.*`, `profiler`, and `diagnostics` options after profiling; Mathlib's `setOption` linter rejects `trace`, `pp`, `profiler`, and `debug` options in final code.

---

## 5. The 4 Main Causes of Performance Explosions & Their Remedies

### Cause 1: Open `simp` Scanning Too Many Lemmas

- **Problem**: Calling `simp` without restrictions tests hundreds of rewriting candidates against large expressions.
- **Remedy**: Replace with `simp only [lemma1, lemma2]` or `dsimp only [...]`.

### Cause 2: Deep Definitional Unfolding (WHNF / DefEq Timeouts)

- **Problem**: When comparing complex polymorphic terms (e.g. measures, norms, integrals, category compositions), Lean tries to unfold definitions to verify definitionally equal terms (`isDefEq`). If definitions are transparent, Lean cascades through multiple layers of nested structures.
- **Remedy: The Irreducible Wrapper Pattern**:
  Freeze complex definitions during intermediate lemmas using `@[irreducible]`:

```lean
/-- Frozen alias that elaborator will not unfold during DefEq checks -/
@[irreducible]
def myComplexTermFrozen (x : BigType) : BigType := myComplexTerm x

-- Prove a lemma stating the equality for when unfolding is deliberately needed
lemma myComplexTermFrozen_def (x : BigType) :
    myComplexTermFrozen x = myComplexTerm x := by
  unfold myComplexTermFrozen; rfl
```

Using the frozen definition prevents the elaborator from expanding the internals, dropping heartbeat counts from 500k+ to <10k.

### Cause 3: Typeclass Search Cascades & Missing Type Annotations

- **Problem**: When a term has uninstantiated metavariables or implicit parameters, Lean initiates typeclass synthesis across thousands of potential paths.
- **Remedy**:
  - Add explicit type annotations: `(x : ℝ)` instead of letting Lean guess whether `x` is `ℝ`, `ℂ`, or an arbitrary topological ring.
  - Pin type parameters explicitly in lemma applications: `exact @my_lemma ℝ _ _ x`.

### Cause 4: Overuse of Heavy Automated Tactics (`aesop`, `linarith`)

- **Problem**: Tactics like `aesop` and open `linarith` perform extensive tree searches and collect all hypotheses in the local context.
- **Remedy**:
  - For linear integer/natural arithmetic: use `omega` (Lean 4.7+ Core) (vastly faster and complete for Presburger arithmetic).
  - Scope `linarith`: use `linarith only [h1, h2]` to avoid parsing irrelevant local hypotheses.
  - For `aesop`: configure rule sets strictly or replace with targeted `constructor`, `ext`, and `simp only`.

---

## 6. Decomposing Monolithic Theorems

If a theorem remains slow after tactic tuning:

1. Identify natural intermediate milestones in the argument.
2. Break each milestone into a separate `private lemma` or `local lemma`.
3. Verify each helper lemma independently.
   Lean elaborates declarations in separate tasks; modularizing proofs allows the compiler to parallelize work across CPU cores and keeps individual declaration heartbeats under 20,000.
