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

### A Local Limit Replaces the Lakefile Limit

`set_option maxHeartbeats N in` sets the limit to `N`. It does not add to the lakefile value or take the larger of the two. In a project whose lakefile raises the limit, a local setting below the lakefile value therefore **lowers** the limit under `lake build`, while under `lake env lean`, which starts from Lean's default `200000`, the same line **raises** it. Measured with Lean `v4.33.1` and `v4.35.0`, with `maxHeartbeats = 4000000` in `[leanOptions]` and declarations that need about 2,000,000 and 500,000 heartbeats:

| Declaration                                            | `lake build` and `lake lean` | `lake env lean`    |
| :----------------------------------------------------- | :--------------------------- | :----------------- |
| Needs 2,000,000, no local option                       | Builds                       | Fails at `200000`  |
| Needs 2,000,000, `set_option maxHeartbeats 1000000 in` | **Fails at `1000000`**       | Fails at `1000000` |
| Needs 500,000, no local option                         | Builds                       | Fails at `200000`  |
| Needs 500,000, `set_option maxHeartbeats 1000000 in`   | Builds                       | Builds             |

The local option made the first declaration fail under `lake build`, which it passed without the option, and it was the only reason the last declaration built under `lake env lean`. A comment such as "raised for a slow proof" above that line is then wrong for the build that matters.

In the formalization of about 175,000 modules described in §2, the lakefile set `maxHeartbeats = 4000000`, and the sources contained 57,556 `set_option maxHeartbeats` lines. 55,575 of them (97%) set a value between `200000` and `4000000`, most often `set_option maxHeartbeats 1000000 in` (50,384 lines). Each of those lowered the limit under `lake build` and raised it under `lake env lean`. Another 1,738 lines set exactly `4000000` and changed nothing under `lake build`.

**Rules**:

- **Raise a limit in one place only.** Either keep Lean's default in the lakefile and raise per declaration (§2), or raise it for a library in the lakefile and do not set it locally. Mixing the two makes the meaning of every local line depend on the entry point.
- **A local value must exceed the lakefile value** if both are kept. Find local values that lower the limit, here for a lakefile value of `4000000`:

  ```bash
  grep -rnoE 'set_option maxHeartbeats [0-9]+' --include='*.lean' . \
    | awk '$NF < 4000000'
  ```

- **Lower the lakefile value with care.** Removing a lakefile raise turns every declaration that silently relied on it into a timeout. Run `lake build` after the change and give each failure a local raise with a measured value (`#count_heartbeats in`, §2) or a fix.

### Splitting a Project into Several Libraries

A large project gains from several `[[lean_lib]]` blocks instead of one:

- **Per-area limits.** A heavy area gets its own limits, and the rest of the project keeps Lean's defaults.
- **Partial builds.** `lake build Fields` builds the modules of one area and everything they import, from any library. It stays partial only while the imports between libraries run one way (see "Keep the Imports Between Libraries One-Way" below). A challenge library that imports only Mathlib can be built without the development.
- **Explicit defaults.** `defaultTargets` lists what a plain `lake build` builds.

```toml
# lakefile.toml
name = "myproject"
defaultTargets = ["Core", "Fields", "Witnesses", "Main"]

[leanOptions]
autoImplicit = false

[[lean_lib]]
name = "Core"
globs = ["MyProject.Algebra.+", "MyProject.Geometry.+"]

# Number-field instances are deep; raised here once instead of in every file.
[[lean_lib]]
name = "Fields"
globs = ["MyProject.LocalFields.+", "MyProject.GlobalFields.+"]
leanOptions = {synthInstance.maxHeartbeats = 400000}

[[lean_lib]]
name = "Witnesses"
globs = ["MyProject.Witnesses.+"]

[[lean_lib]]
name = "Main"
roots = ["Statements", "Main"]
```

With this lakefile, a module under `MyProject/LocalFields/` reads `synthInstance.maxHeartbeats` as `400000`, and a module under `MyProject/Algebra/` reads Lean's default `20000`. This holds even when both are built only because `Main` imports them.

In one formalization of about 175,000 modules, one area was split into two libraries in this way. Ten of its twelve directories went to one library, and the two field-theory directories, 543 files, went to a second library with `synthInstance.maxHeartbeats = 400000`. Only 3 of those 543 files set the option themselves.

### Which Library's Options a Module Gets

Lake compiles each module with the options of the library whose `globs` or `roots` match it. Measured with Lake from Lean `v4.33.1`:

| Situation                                                          | What Lake did                                                                                              |
| :----------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------- |
| Library `B` imports a module that library `A` owns                 | Compiled it with `A`'s options                                                                             |
| Glob `Foo.A.+`                                                     | Matches the submodules of `Foo.A` only, not `Foo.A` itself (`Foo.A.*` matches both)                        |
| A module that no library matches is imported                       | Not built; the importer fails with `object file ... of module Foo.A does not exist`                        |
| Two libraries `A` and `C` match the same module                    | `lake build A` and `lake build C` compiled it with different options, and alternating rebuilt it each time |
| The same overlapping module, built as an import of a third library | It got the options of whichever of `A` and `C` was declared later in the lakefile                          |

**Rules**:

- **Make the globs disjoint and complete.** Every module belongs to exactly one library. With overlapping globs, the options of a module depend on which target is being built and on the order of the blocks in the lakefile, and two targets keep rebuilding each other's modules.
- **List the directories explicitly** when an area is split. Write `globs = ["Area.X.+", "Area.Y.+"]` for one part and the remaining directories for the other part, not `Area.+` with an exception.
- **Remember the root file.** If a directory has a root module (`Foo/A.lean` next to `Foo/A/`), use `Foo.A.*` or add it to `roots`. With `Foo.A.+` the root file belongs to no library.
- **A library-wide raise is still a raise.** The policy in §2 applies: give the reason in a lakefile comment, as in the example above, and keep the area as small as the cause.

### Keep the Imports Between Libraries One-Way

Lake orders a build module by module, not library by library. Measured with Lake from Lean `v4.33.1`, `v4.35.0` and `v4.36.0`:

| Situation                                                               | What Lake did                                                                                           |
| :---------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------ |
| Libraries `A` and `B` import each other's modules, with no module cycle | `lake build` succeeded without a warning                                                                |
| `lake build A`, where a module of `A` imports a module of `B`           | Built that module of `B` and its imports as well                                                        |
| A module of a path dependency imports a module of the root package      | The workspace build succeeded; only building the dependency on its own failed (`unknown module prefix`) |

These versions have no `lean_lib` setting that restricts what a library may import. Splitting a project into libraries therefore sets no direction, and splitting it into packages sets none for a build of the whole workspace. The direction holds only if something checks it.

In the formalization of about 175,000 modules mentioned in §2, 8 of the 12 libraries in the lakefile formed one cycle: each of them reached every other one through its imports. 14 pairs of libraries imported each other directly, for example:

| Libraries `A` / `B`                                                | Imports of `B` in `A` | Imports of `A` in `B` |
| :----------------------------------------------------------------- | --------------------: | --------------------: |
| `Formalism` / `ReciprocityTheory`                                  |                   348 |                   266 |
| `Lemmata` / `Formalism`                                            |                   634 |                   118 |
| `GroundTheory` / `GroundTheoryFields` (the split for limits above) |                   279 |                    55 |

Computed from the import lines, building the library `Lemmata`, which has 167 modules, takes 836 modules, 649 of them from `Formalism`. Building `GroundTheory` takes 1,217 modules from other libraries, 423 of them from `ReciprocityTheory`. Both builds were still far smaller than the whole project, but the library names did not tell what they would include.

`library_dag.py` from `lean4-cli` reads the libraries from `lakefile.toml` and the `import` lines of their source files, so it needs no build. Write down which other libraries each library may import, with one entry per library. For the lakefile above:

```json
{
  "Core": [],
  "Fields": ["Core"],
  "Witnesses": ["Core", "Fields"],
  "Main": ["Core", "Fields"]
}
```

```bash
python3 <skills-path>/lean4-cli/scripts/library_dag.py . --allow library-dag.json
```

The lists are not transitive: a library imports only what its own entry names. The script rejects a file whose entries form a cycle, and exits with code `1` on any import that is not allowed:

```text
  Core -> Fields: 1 import(s) in 1 module(s)  [NOT ALLOWED]
      ./MyProject/Algebra/Basic.lean imports MyProject.LocalFields.Basic
```

Without `--allow`, it fails only if libraries depend on each other in a cycle.

**Rules**:

- **Decide the order when the libraries are declared.** Write the file with the lakefile, before the first proof file, and run the check in CI. A new library needs an entry, or the check stops with an error. A library split off for its limits (above) needs a place in the order too.
- **Check against the file, not only for cycles.** A first import in the wrong direction creates no cycle while nothing leads back, directly or through other libraries, so the check without `--allow` passes it.
- **Move shared declarations down.** When a lower library needs something from a higher one, move the declaration to the lower library or to a library below both, and update its importers.
- **Do not add an entry just to make the check pass.** A new allowed import changes the design and needs a review, like raising a limit.
- **Remove existing cycles before enforcing the order.** The script keeps no list of tolerated imports. The report of the run without `--allow` counts the imports in each direction, which shows how many each possible order would have to remove.

The script checks the libraries of one package, not imports from dependencies or the modules of `lean_exe` targets. It requires Python 3.11+. For a `lakefile.lean`, translate the configuration with `lake translate-config toml <file>` and pass `--lakefile <file>`.

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
2. Break each milestone into a separate `private lemma`.
3. Verify each helper lemma independently.
   Lean elaborates declarations in separate tasks; modularizing proofs allows the compiler to parallelize work across CPU cores and keeps individual declaration heartbeats under 20,000.

### How Long a Declaration Should Be

A declaration is one command, so its size sets three things at once. Measured with Lean `v4.33.1` and `v4.35.0`:

- **One heartbeat budget.** `maxHeartbeats` counts the whole declaration. A theorem made of eight `have` steps of about 100,000 heartbeats each timed out at the default `200000`, although each step alone was well within it. As eight theorems, each step gets its own budget.
- **One elaboration task.** Since `v4.19.0` ([#7084](https://github.com/leanprover/lean4/pull/7084)), the proofs of different theorems in a file are elaborated in parallel. The proof of one theorem is a single task. Eight theorems of about 300,000 heartbeats each took 3.3–5.9 s of wall time, and one theorem with the same eight steps as `have`s took 14.7–17.8 s, for the same CPU time on 12 cores.
- **One unit of review.** A reader, a reviewer or an agent has to hold the whole proof in mind to check or change it.

Mathlib keeps declarations short. In the Mathlib release used with Lean `v4.35.0`, Lean stored source ranges for 334,143 declarations:

| Length            | Mathlib declarations |
| :---------------- | :------------------- |
| 50 lines or more  | 963 (0.29%)          |
| 100 lines or more | 124 (0.04%)          |
| 200 lines or more | 5                    |

The longest theorem had 258 lines (`isCompact_setOfPred_finiteMeasure_mass_le_compl_isCompact_le`), and the longest declaration of any kind, a metaprogram, had 369 lines.

In the formalization of about 175,000 modules described in §2, a text scan of the sources found about 9,500 declarations over 100 lines, 656 over 200 lines and 10 over 1,000 lines, all 10 in one directory. `#long_decls` confirmed the longest ones: a single theorem of 8,001 lines, followed by theorems of 2,649, 2,432, 1,364 and 1,054 lines.

Use these numbers as limits:

- **Aim for under 50 lines** per declaration. That covers 99.7% of Mathlib.
- **Split anything over 100 lines** along the milestones of the argument (steps 1–3 above), unless there is a reason to keep it whole, such as a case analysis with many short branches. Record that reason in a comment.
- **Enforce a limit in CI.** Start at the length of the current longest declaration, or at 200 lines, and lower it as declarations are split. `#long_decls` from the `lean4-cli` skill (`scripts/long_decls.lean`) reads the stored source ranges, so it also covers declarations in compiled modules. Under `set_option warningAsError true in`, every declaration over the limit is an error and `lean` exits with code 1:

  ```bash
  { echo "import MyProject.Main"; cat <skills-path>/lean4-cli/scripts/long_decls.lean
    echo "set_option warningAsError true in"; echo "#long_decls 200 MyProject"; } \
    | lake env lean --stdin
  ```

  The length counts every line from the first attribute or docstring line to the end of the declaration, including comments and blank lines inside it.
