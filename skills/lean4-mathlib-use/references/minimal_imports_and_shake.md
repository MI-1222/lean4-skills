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
| **Order & Lattice Theory**                 | `Mathlib.Order.Bounds`<br>`Mathlib.Order.Monotone.Basic`<br>`Mathlib.Order.Lattice`                  | Partial orders, bounds (`sSup`, `sInf`), monotone maps, lattices         |
| **Real & Complex Numbers**                 | `Mathlib.Basic.Real.Basic`<br>`Mathlib.Data.Complex.Basic`                                           | Complete ordered field structure of `ℝ`, complex arithmetic              |
| **Elementary Calculus / Analysis**         | `Mathlib.Analysis.Calculus.Deriv.Basic`<br>`Mathlib.Analysis.SpecialFunctions.Pow.Real`              | Single-variable derivatives (`deriv`), real powers, exp, log             |
| **Topology**                               | `Mathlib.Topology.Basic`<br>`Mathlib.Topology.Constructions`<br>`Mathlib.Topology.MetricSpace.Basic` | Open sets, neighborhoods, continuity, metric spaces                      |
| **Linear Arithmetic & Inequality Tactics** | `Mathlib.Tactic.Linarith`<br>`Mathlib.Tactic.Ring`<br>`Mathlib.Tactic.Positivity`                    | `linarith`, `nlinarith`, `ring`, `positivity` tactics                    |
| **Integer / Natural Arithmetic**           | `Mathlib.Tactic.Omega`<br>`Mathlib.Data.Nat.Basic`                                                   | `omega` tactic (Lean 4.7+ Core) for Presburger arithmetic on `ℕ` and `ℤ` |

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

Mathlib provides a dedicated static analysis tool called `shake` to detect and remove unused imports based on syntax tree inspection.

### Running `shake`

`lake shake` is a built-in Lake command since Lean `v4.28.0` (lean4#11921). On older toolchains, shake was a separate script and was run as `lake exe shake`.

1. **Audit Unused Imports**:

   ```bash
   lake shake
   ```

   This command inspects all files in the project and reports unnecessary `import` statements.

2. **Automatically Fix and Prune**:
   ```bash
   lake shake --fix
   ```
   This automatically rewrites the import headers of affected files, pruning redundant dependencies while preserving required modules.

### Limitations & Constraints of `lake shake`

Keep these constraints in mind when using `lake shake`:

1. **Strict Standard Module Requirement**:
   - `lake shake` currently only operates on standard Lean module identifiers (`MyProject.Algebra.Basic`).
   - If your project contains directories or filenames with hyphens (e.g., `«my-subproject»` requiring French quote escaping or permitted via `allowNonModules = true`), `lake shake` will abort with:
     ```text
     error: `lake shake` only works with `module`s currently
     ```
   - **Workaround**: In projects containing escaped or non-module paths, avoid running whole-project `lake shake`. Either restrict targets, normalize directory names to standard Lean module identifiers (PascalCase or snake_case without hyphens), or inspect and prune imports manually.

2. **Tactic and Typeclass Instance Dependencies**:
   - `shake` relies on AST syntax inspection. If an imported module solely provides a behind-the-scenes tactic, macro, or typeclass instance that is not explicitly named in the file, `shake` may mistakenly consider it unused.
   - **Rule**: Always run `lake build` immediately after `lake shake --fix` to confirm that all tactics and typeclass instances remain functional.

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
