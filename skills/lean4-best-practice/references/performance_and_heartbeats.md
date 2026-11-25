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

1. **Fix the cause first.** Work through §6 (open `simp`, defeq unfolding, instance search, heavy automation, auto-generated lemmas) before touching any limit.
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

| Scope                | How                                                     | When it is acceptable                                                            |
| :------------------- | :------------------------------------------------------ | :------------------------------------------------------------------------------- |
| **One declaration**  | `set_option maxHeartbeats N in` + comment               | Default choice for a justified raise                                             |
| **Rest of the file** | `set_option maxHeartbeats N` (no `in`)                  | Avoid; Mathlib lints against it                                                  |
| **One library**      | `leanOptions` in a `[[lean_lib]]` block of the lakefile | Project-wide settings that differ from Lean's defaults, chosen deliberately (§4) |
| **Whole package**    | `[leanOptions]` / `leanOptions :=` on the package       | Same as above, e.g. Mathlib's `maxSynthPendingDepth := 3`                        |

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

## 4. Setting Options in the Lakefile

Options can be set for a whole library or package:

```toml
# lakefile.toml
[leanOptions]               # applies to the whole package
autoImplicit = false
maxSynthPendingDepth = 3

[[lean_lib]]
name = "HeavyFields"
leanOptions = {synthInstance.maxHeartbeats = 400000}   # this library only
moreLeanArgs = ["--tstack=400000"]                       # command-line flags only
```

```lean
-- lakefile.lean
package myproject where
  leanOptions := #[⟨`autoImplicit, false⟩, ⟨`maxSynthPendingDepth, .ofNat 3⟩]
```

> [!WARNING]
> **Lakefile options do not reach every entry point.** Measured with Lean `v4.33.1`:
>
> | Entry point                         | `leanOptions` applied? | `moreLeanArgs` applied? |
> | :---------------------------------- | :--------------------- | :---------------------- |
> | `lake build`                        | Yes                    | Yes                     |
> | `lake lean <file>`                  | Yes                    | Yes                     |
> | Language server (`lake setup-file`) | Yes                    | Not reported            |
> | `lake env lean <file>`              | **No**                 | **No**                  |
>
> A file that builds with `lake build` can therefore fail under `lake env lean` (and the reverse if the lakefile _lowers_ a limit). In projects with lakefile options, use `lake lean <file>` for the fast file check, or pass the options explicitly: `lake env lean -DmaxSynthPendingDepth=3 <file>`. Set **options** through `leanOptions`, not as `-D` flags in `moreLeanArgs`, so that the language server sees them too.

---

## 5. Profiling Slow Proofs

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

## 6. The Main Causes of Performance Explosions & Their Remedies

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

#### Freezing an Existing Definition Locally

When the definition that unfolds too far belongs to Mathlib or another module, change its reducibility only where it hurts, inside a `section`:

```lean
section
attribute [local irreducible] heavy   -- `seal heavy` has the same effect
-- `heavy` is not unfolded by `isDefEq` here; `unfold heavy` and `simp only [heavy]` still work
theorem uses_heavy : ... := by ...
end
-- outside the section, `heavy` unfolds as before
```

What Lean accepts depends on the definition's current status (verified on Lean `v4.33.1`):

| Change                                                               | Accepted?                                                                                                                                    |
| :------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------- |
| Ordinary `def` → `attribute [local irreducible]` or `seal`           | Yes, also for definitions imported from other modules                                                                                        |
| Imported `def` → `attribute [irreducible]` (global)                  | No: ``failed to set reducibility status, `heavy` has not been defined in this file, consider using the `local` modifier``                    |
| `abbrev` / `@[reducible]` → irreducible (`local`, `seal`, any file)  | No: ``failed to set `[local irreducible]`, `X` is currently `[reducible]`, `[semireducible]` ... expected``. Needs `allowUnsafeReducibility` |
| `@[irreducible] def` → `attribute [local semireducible]` or `unseal` | Yes                                                                                                                                          |

**`abbrev` is reducible on purpose.** Instances and `simp` reach the underlying type through it: with `abbrev Carrier : Type := Nat`, `a + b` for `a b : Carrier` uses `Nat`'s instance. Making `Carrier` irreducible breaks that (`failed to synthesize instance of type class`), which is why Lean demands `set_option allowUnsafeReducibility true`.

- Prefer a frozen wrapper (`@[irreducible] def`, the pattern above) or, for your own code, a `def` with explicit instances instead of an `abbrev`.
- If a local override of an `abbrev` is still the right tool, scope it tightly and say why:

  ```lean
  section
  set_option allowUnsafeReducibility true in
  -- `Per.Acris` unfolds to a large completion; the lemmas below only need its ring structure
  attribute [local irreducible] Per.Acris
  ...
  end
  ```

- Expect review tools to flag the option: `lean4-cli`'s `scan_risky_constructs.py` reports `allowUnsafeReducibility` as `unsafe-code`.

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

### Cause 5: Auto-Generated Lemmas for Heavy Structures and Inductives

- **Problem**: For every `structure` and `inductive`, Lean also generates and checks injectivity lemmas (`Foo.mk.inj`, `Foo.mk.injEq`, proved with `simp`) and `sizeOf` specification lemmas (`Foo.mk.sizeOf_spec`). With many fields whose types are large Mathlib terms (linear maps, modules over completions, matrices), this work can exceed the cost of the declaration itself. It shows up in `set_option profiler true in` as `congr simp thm` and `simp` entries on a command that contains no proof.
- **Remedy**: When the lemmas are not needed, turn their generation off for that one declaration:

  ```lean
  set_option genInjectivity false in
  set_option genSizeOfSpec false in
  -- data bundle with heavy field types; constructor injectivity and `sizeOf` are never used
  structure ConjLift where
    mu   : (AE D)ˣ →* Circle
    coef : (A.MtCSD i A.μ0).V →ₛₗ[σ] cV.W
    ...
  ```

  Measured on a 14-field structure of this kind (Lean `v4.33.1`, profiler, four runs each): the `structure` command took **709–750 ms** with the lemmas and **277–286 ms** without them; `congr simp thm` and `simp` alone accounted for about 340 ms.

- **What stops working** (verified on Lean `v4.33.1` and `v4.35.0`):

  | Option off             | Lost                                                                                                                                                                                      | Still works                                                                  |
  | :--------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------- |
  | `genInjectivity false` | `Foo.mk.inj`, `Foo.mk.injEq`; `simp` no longer splits `Foo.mk a b = Foo.mk c d` (`simp made no progress`)                                                                                 | `injection h`, `cases h`, `congrArg Foo.a h`                                 |
  | `genSizeOfSpec false`  | `Foo.mk.sizeOf_spec`; well-founded recursion measured by `sizeOf` fails, whether automatic (e.g. through a `List Foo` field: `fail to show termination`) or written as `termination_by t` | Structural recursion; `termination_by` with another measure (e.g. `t.depth`) |

- **Rules**: use these options only with `in` on one declaration, with a comment, and only for data bundles that are never compared constructor by constructor or recursed over. Never set them in the lakefile or file-wide.

---

## 7. Decomposing Monolithic Theorems

If a theorem remains slow after tactic tuning:

1. Identify natural intermediate milestones in the argument.
2. Break each milestone into a separate `private lemma` or `local lemma`.
3. Verify each helper lemma independently.
   Lean elaborates declarations in separate tasks; modularizing proofs allows the compiler to parallelize work across CPU cores and keeps individual declaration heartbeats under 20,000.
