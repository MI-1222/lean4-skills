# Unknown Identifier Troubleshooting Guide

The error `unknown identifier '<name>'` occurs when the Lean parser or elaborator encounters an unresolvable name that is neither in the current scope nor the imported modules.

---

## 1. Anatomy of the Error

```text
unknown identifier 'add_comm'
```

Lean 4 does not place every lemma into the root namespace. Most lemmas live inside specific namespaces corresponding to the type or algebraic structure (e.g. `Nat.add_comm`, `Real.sqrt_pos`).

---

## 2. Common Scenarios & Solutions

### 2.1 Namespace Prefix Missing

- **Symptom**: Calling `add_comm` directly fails.
- **Fix**:
  - Add the namespace prefix: `Nat.add_comm` or `Int.add_comm`.
  - Or open the namespace at the top of the file:
    ```lean
    open Nat
    ```

---

### 2.2 Missing Imports

A lemma is present in Mathlib, but the specific module has not been imported.

- **Symptom**: Common theorems from topology, linear algebra, or measure theory are missing.
- **Fix**:
  - For rapid development/prototyping, temporarily use:
    ```lean
    import Mathlib
    ```
  - For clean modular builds, look up the module path (e.g., `Mathlib.Data.Real.Basic`, `Mathlib.Topology.ContinuousOn`).

---

### 2.3 Lean 3 to Lean 4 Renaming Conventions

Lean 4 adopted standardized naming conventions (RFC on naming conventions):

- **Types and Typeclasses**: `UpperCamelCase` (e.g., `MetricSpace`, `CommRing`).
- **Functions, Definitions, Theorems**:
  - Functions: `lowerCamelCase` or `snake_case` (e.g., `functor.map`, `list.reverse`).
  - Mathematical theorems: `snake_case` using dot notation on the principal type (e.g., `Continuous.comp`, `Nat.succ_le_succ`).

Common renames:
| Lean 3 Name | Lean 4 / Mathlib 4 Canonical Name |
| :--- | :--- |
| `add_comm` | `add_comm` (type-qualified: `Nat.add_comm`, etc.) |
| `iff.intro` | `Iff.intro` |
| `le_trans` | `le_trans` or `Preorder.le_trans` |
| `decide` | `decide` (now a term or tactic) |
| `rw [<- h]` | `rw [← h]` |

---

### 2.4 Discovering Identifiers in Mathlib

When uncertain of an identifier name:

1. **Interactive search tactics**: In place of `exact my_identifier`, run:
   ```lean
   exact?
   ```
   or:
   ```lean
   apply?
   ```
2. **Loogle / Mathlib Search Skill**: Use the `lean4-mathlib-search` skill with `scripts/search_loogle.py` to query by type signature (e.g., `?a + ?b = ?b + ?a`).
