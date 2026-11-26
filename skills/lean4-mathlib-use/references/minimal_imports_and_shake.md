# Minimal Imports and Dependency Management in Mathlib

This guide explains how to optimize module dependencies, eliminate compile-time lag caused by monolithic imports, and systematically prune unused dependencies using tooling like `lake shake`.

---

## 1. The Trade-Off of `import Mathlib`

`import Mathlib` loads all of Mathlib into every Lean process that elaborates the file. That has a real cost per process, but it does not make builds rebuild more, and it has benefits of its own. Decide per file, not by reflex.

### Measured Cost per Process

One small file proving `0 < x ^ 2 + 1` over `ℝ` with `positivity`, checked with `lake env lean` (Lean `v4.33.1`, Mathlib `v4.33.1`):

| Header                                                                 | Modules in the import closure | Imported constants | Peak memory (RSS) |
| :--------------------------------------------------------------------- | ----------------------------: | -----------------: | :---------------- |
| `import Mathlib`                                                       |                        10,498 |            771,129 | 4.0–5.7 GB        |
| `import Mathlib.Data.Real.Basic`<br>`import Mathlib.Tactic.Positivity` |                         2,382 |            234,479 | 1.5 GB            |

- **Every fresh process pays the load.** Lean maps the `.olean` files of the whole closure into memory when it starts: `lake env lean` on a scratch file, a language-server restart, and each module that a build compiles. Load time grows with the closure as well.
- **RSS includes the mapped `.olean` files.** The OS can share those pages between processes, so parallel processes need less than a multiple of this figure. On a machine short of memory, the full import still pushes other data out of the cache first.
- **Search tactics see everything.** `exact?`, `apply?`, `simp?` and instance search run over about three times as many constants. They find more, and they take longer.
- **Lake's per-module bookkeeping grows with the closure.** Lake writes a `.setup.json` per module that lists its whole import closure. In one formalization of about 175,000 modules, where 136,004 files began with `import Mathlib`, those files averaged about 6 MB, around a terabyte in total, and had to be deleted during the build.

### What `import Mathlib` Does Not Cost, and What It Gives

- **No extra rebuilds.** Within one Mathlib pin, Mathlib does not change, so `import Mathlib` never causes a module to be recompiled. Rebuild cost depends on the project's own import graph, not on how Mathlib is imported.
- **The same environment in every file.** Every file sees the same instances, `simp` lemmas, notation and tactics. A proof moved from one file to another behaves the same, and no time goes into finding the import that provides a missing instance or tactic.

### Recommendation

| Situation                                               | Recommendation                                                                                                                                                        |
| :------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Code meant for Mathlib, or a library others will import | Targeted imports, pruned with `lake shake` (§4)                                                                                                                       |
| Scratch files and quick checks with `lake env lean`     | Targeted imports when the needed modules are known; otherwise `import Mathlib` and accept the load time                                                               |
| Exploration in a warm language server                   | `import Mathlib` is fine; the load happens once per session                                                                                                           |
| A large downstream project                              | Either is workable. With `import Mathlib`, plan for its memory per build process and for Lake's bookkeeping files; with targeted imports, plan for import maintenance |

---

## 2. Domain-Specific Submodule Selection

To maintain high compilation speed and clean dependencies, target the smallest submodules that provide the necessary types and tactics for your specific mathematical domain.

Mathlib modules follow a hierarchical structure:

- `.Defs`: Core type definitions and fundamental axioms (minimal dependencies).
- `.Basic`: Elementary properties, basic lemmas, and standard API for the definitions.
- Specialised modules (e.g., `.Continuous`, `.Hom`, `.Constructions`): Advanced theories built on `.Basic`.

### Recommended Minimal Submodules by Domain

| Mathematical Domain                        | Recommended Submodules                                                                               | Key Concepts & Solvers Provided                                          |
| :----------------------------------------- | :--------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------- |
| **Elementary Algebra (Groups, Rings)**     | `Mathlib.Algebra.Group.Defs`<br>`Mathlib.Algebra.Group.Basic`<br>`Mathlib.Algebra.Ring.Basic`        | Semigroups, monoids, groups, rings, basic algebraic operations           |
| **Order & Lattice Theory**                 | `Mathlib.Order.Bounds.Basic`<br>`Mathlib.Order.Monotone.Basic`<br>`Mathlib.Order.Lattice`            | Partial orders, bounds (`sSup`, `sInf`), monotone maps, lattices         |
| **Real & Complex Numbers**                 | `Mathlib.Basic.Real.Basic`<br>`Mathlib.Basic.Complex.Basic`                                          | Complete ordered field structure of `ℝ`, complex arithmetic              |
| **Elementary Calculus / Analysis**         | `Mathlib.Analysis.Calculus.Deriv.Basic`<br>`Mathlib.Analysis.SpecialFunctions.Pow.Real`              | Single-variable derivatives (`deriv`), real powers, exp, log             |
| **Topology**                               | `Mathlib.Topology.Basic`<br>`Mathlib.Topology.Constructions`<br>`Mathlib.Topology.MetricSpace.Basic` | Open sets, neighborhoods, continuity, metric spaces                      |
| **Linear Arithmetic & Inequality Tactics** | `Mathlib.Tactic.Linarith`<br>`Mathlib.Tactic.Ring`<br>`Mathlib.Tactic.Positivity`                    | `linarith`, `nlinarith`, `ring`, `positivity` tactics                    |
| **Integer / Natural Arithmetic**           | `Mathlib.Data.Nat.Basic` (no import needed for `omega`)                                              | `omega` tactic (Lean 4.7+ Core) for Presburger arithmetic on `ℕ` and `ℤ` |

> [!NOTE]
> **Module names change between Mathlib versions.** On 2026-08-27, Mathlib moved `Mathlib.Data.Real.Basic` and `Mathlib.Data.Complex.Basic` to `Mathlib.Basic.Real.Basic` and `Mathlib.Basic.Complex.Basic`. In Mathlib `v4.35.0`, the old names still exist as deprecated modules (`deprecated_module`, available since Lean `v4.31.0`), and importing one warns: `'Mathlib.Data.Real.Basic' has been deprecated: please replace this import by import Mathlib.Basic.Real.Basic`. Mathlib `v4.33.1` has only the old names. Before copying a module name from any guide, check that the file exists in the Mathlib your project pins (`.lake/packages/mathlib/Mathlib/...`).

---

## 3. Upstream Binary Cache Acquisition (`lake exe cache get`)

Never allow Lean to recompile Mathlib dependencies locally from source. Before starting any proof verification or dependency editing:

```bash
# Ensure precompiled .olean artifacts are downloaded and synchronized
lake exe cache get
```

Skipping this step forces Lean to build Mathlib from source, which can take anywhere from 30 minutes to over an hour.

---

## 4. Pruning Unused Imports with `lake shake`

`lake shake` is a tool built into Lake that reports and removes unused imports. It analyzes the compiled `.olean` files: an import counts as needed when a declaration of the file refers to one of its constants, in the type or the body, or when elaboration recorded a use of it, such as a macro or a piece of syntax. From the source files it reads only the header, with its `import` lines and `shake:` annotations. Run `lake build` first; shake refuses to run while the `.olean` files of the default targets are out of date.

### Running `shake`

`lake shake` is a built-in Lake command since Lean `v4.28.0` (lean4#11921). On older toolchains, shake was a separate script and was run as `lake exe shake`.

1. **Audit Unused Imports**:

   ```bash
   lake shake
   ```

   Without arguments, shake starts from the root modules of the default targets: the `roots` of each library and the root of each executable. It reports only files that those roots import, directly or indirectly, and whose module names are under the top-level name of a root. It therefore does not report:
   - a file that the `globs` of a library match but that no root imports,
   - a library that is not a default target and that no root imports,
   - an imported file under another top-level name.

   To check such files, pass their module names, e.g. `lake shake MyProject.Extra`. If a default target is a library with `globs` and no root module, the run without arguments stops with ``object file ... of module `<Library>` does not exist``, with or without `module` headers; pass module names there too.

2. **Automatically Fix and Prune**:
   ```bash
   lake shake --fix
   ```
   This rewrites the import headers of the reported files. It can remove an import that a file needs (limitation 2 below).

### Limitations & Constraints of `lake shake`

Keep these constraints in mind when using `lake shake`:

1. **Every Loaded File Needs the `module` Header**:
   - `lake shake` works only with the module system. It loads the target modules and everything they import, and if any of these files lacks the `module` header, it aborts with:
     ```text
     error: `lake shake` only works with `module`s currently
     ```
   - File and directory names do not cause this error. With headers, `lake shake --fix` pruned an import in a file under a hyphenated directory (`«my-dir»`); without headers, it aborted whether or not the names had hyphens. `allowNonModules = true` does not help: this Lake option only silences the warning about a file without the header that imports a package or library with `requiresModuleSystem` set.
   - **Workaround**: In a project that mixes both kinds of files, pass only modules that have the header, e.g. `lake shake MyProject.Algebra.Basic`. A file with the header cannot import one without it, so everything these modules import qualifies too. For the other files, prune imports by hand, or move them to the module system first. Adding the `module` line alone is not enough: declarations and imports become private unless marked `public`, so files that rely on them stop building.
   - Checked on Lean `v4.33.1`, `v4.35.0` and `v4.36.0`.

2. **Some Needed Imports Are Removed**:
   - A use that leaves nothing in the compiled file can be missed. An `example` adds no declaration, so the constants it refers to are not seen. Results of `lake shake --fix` on one small case of each kind:

     | The file needs the import only for                                                     | Result                                      |
     | :------------------------------------------------------------------------------------- | :------------------------------------------ |
     | A macro, `macro_rules`, `elab` tactic or notation used in a theorem or a definition    | Kept                                        |
     | An instance, a coercion or an added `attribute [simp]` used in a theorem or definition | Kept                                        |
     | A `rfl` lemma for `dsimp`, or a simproc, used in a theorem                             | Kept                                        |
     | A macro used in an `example`                                                           | Kept                                        |
     | A constant, an instance or an added `attribute [simp]` used in an `example`            | Removed, build fails                        |
     | A constant used in `#check`, `#eval` or `#guard`                                       | Removed, build fails                        |
     | A namespace named by `open`, or an option named by `set_option`                        | Removed, build fails                        |
     | A linter that the import registers                                                     | Removed, build succeeds without its warning |

   - **Keep such an import** by annotating it: `import MyProject.Linters -- shake: keep`. The annotated import survived `--fix` in every removed case above.
   - **Rule**: Run `lake build` immediately after `lake shake --fix`, and read the removed imports in the diff. A successful build does not prove that nothing was lost: without its linter, a build only stops warning.
   - Checked on Lean `v4.33.1`, `v4.35.0` and `v4.36.0`.

---

## 5. Exemplary Import Pattern

### Monolithic Import

```lean
-- Loads all of Mathlib (10,498 modules) into every process that checks this file (§1)
import Mathlib

theorem square_nonneg_real (x : ℝ) : 0 ≤ x^2 := by
  exact sq_nonneg x
```

### Targeted Imports

```lean
-- Loads only the real numbers, basic ring order axioms, and necessary tactics
import Mathlib.Basic.Real.Basic
import Mathlib.Algebra.Order.Ring.Defs
import Mathlib.Tactic.Linarith

theorem real_square_add_one_pos (x : ℝ) : 0 < x^2 + 1 := by
  have h : 0 ≤ x^2 := sq_nonneg x
  linarith
```
