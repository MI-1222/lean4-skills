# Minimal Imports and Dependency Management in Mathlib

This guide explains how to optimize module dependencies, eliminate compile-time lag caused by monolithic imports, and systematically prune unused dependencies using tooling like `lake shake`.

---

## 1. The Cost of Monolithic `import Mathlib`

Placing `import Mathlib` at the top of a Lean 4 file is the single most common cause of catastrophic elaboration and compile-time delays.

### Why `import Mathlib` Slows Down Proving Agents

1. **Massive Environment Footprint**: Mathlib contains over two million lines of Lean 4 code. Loading the root module loads tens of thousands of theorems, notations, macros, syntax definitions, and typeclass instances into memory simultaneously.
2. **Elaboration Latency & Cache Invalidation**: Lean 4 compiles and elaborates at file granularity. Whenever an agent creates a temporary file or restarts an LSP session, resolving the full Mathlib environment requires substantial memory and warmup time.
3. **High Transitive Redundancy**: Empirical analysis of Mathlib dependency graphs demonstrates that the median utilization rate of declared imports is only ~1.6%, and approximately 17.5% of imports are transitively redundant.
4. **Fragile Downstream Reusability**: Monolithic imports tightly couple your code to everything in Mathlib, making it difficult to extract helper modules or integrate proofs into lighter downstream libraries.

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

### Anti-Pattern: Monolithic Import

```lean
-- Bad: Loads the entirety of Mathlib into memory
import Mathlib

theorem square_nonneg_real (x : ℝ) : 0 ≤ x^2 := by
  exact sq_nonneg x
```

### Best Practice: Targeted Imports

```lean
-- Good: Loads only the real numbers, basic ring order axioms, and necessary tactics
import Mathlib.Basic.Real.Basic
import Mathlib.Algebra.Order.Ring.Defs
import Mathlib.Tactic.Linarith

theorem real_square_add_one_pos (x : ℝ) : 0 < x^2 + 1 := by
  have h : 0 ≤ x^2 := sq_nonneg x
  linarith
```
