# Classical Logic and Scoped Notations in Mathlib

This guide explains how to manage classical axioms (Law of Excluded Middle, Choice) in compliance with Mathlib's style linters and how to use scoped notations (`BigOperators`, `Pointwise`) without polluting global namespaces.

---

## 1. Constructive Foundations vs. Classical Mathematics

Lean 4's foundational type system (Calculus of Inductive Constructions) is constructive. In pure Lean:

- Not all propositions have a decidable truth value (`Decidable P`).
- The Law of Excluded Middle ($P \lor \neg P$) and double negation elimination ($\neg\neg P \to P$) are not true by definition; they require classical axioms (`Classical.choice`, `Classical.em`).

In standard mathematical practice across Mathlib, classical reasoning is widely embraced. The instance `Classical.propDecidable` provides a `Decidable P` instance for every proposition $P : \text{Prop}$.

However, declaring classical logic globally destroys computability and violates Mathlib linters.

---

## 2. The `openClassical` Style Linter

Mathlib enforces a strict style linter:

```text
Mathlib.Linter.linter.style.openClassical
```

### The Problem with Global `open Classical`

Placing `open Classical` or `open scoped Classical` at file or section level makes _every_ definition in that scope noncomputable and silences constructive typeclass requirements. It obscures whether an algorithm can actually be executed or extracted.

### Summary of Classical Scoping Strategies

| Declaration Method                                        | Effective Scope                        | Computability Impact                            | Linter Verdict & Recommended Use                                                |
| :-------------------------------------------------------- | :------------------------------------- | :---------------------------------------------- | :------------------------------------------------------------------------------ |
| `open scoped Classical in ...`<br>`open Classical in ...` | Following single declaration           | Confined to that specific definition or theorem | **Preferred**: Fully passes linter. Ideal for standalone classical theorems.    |
| `classical` (tactic)                                      | Current `by` block or focused sub-goal | Restricted strictly to the tactic proof state   | **Preferred**: Use when case splitting (`by_cases`) inside a tactic proof.      |
| `open scoped Classical`<br>(section / file level)         | Entire file or until `end` of section  | Marks all enclosed code noncomputable           | **Forbidden**: Triggers `openClassical` linter warning.                         |
| `noncomputable section`                                   | Entire file or section                 | Disables bytecode generation                    | **Mandatory** when defining mathematical values that invoke `Classical.choice`. |

---

## 3. Idiomatic Patterns for Classical Proving

### Pattern 1: Single-Declaration Scope with `open scoped Classical in`

When a theorem statement or term-mode proof requires classical decidability, prefix the declaration with `open scoped Classical in`:

```lean
-- Passes Mathlib linter cleanly
open scoped Classical in
theorem double_negation_elimination (p : Prop) : ¬¬p → p := by
  intro h
  by_cases hp : p
  · exact hp
  · contradiction
```

### Pattern 2: Tactic-Level Injection with `classical`

Inside a tactic block, never add file-level imports just to run `by_cases`. Invoke the `classical` tactic directly:

```lean
theorem excluded_middle_tactic (p : Prop) : p ∨ ¬p := by
  classical
  by_cases h : p
  · exact Or.inl h
  · exact Or.inr h
```

The `classical` tactic injects local instances of `Decidable` with lowest priority, allowing constructive decisions to take precedence if available while enabling classical reasoning where necessary.

---

## 4. Scoped Notations: `BigOperators` and `Pointwise`

Mathlib provides rich mathematical notations (such as summation $\sum$, product $\prod$, and pointwise set operations) via scoped syntax.

### Why Avoid Open Namespaces for Notations

Opening the entire namespace (e.g., `open Finset` or `open Set`) imports hundreds of lemma names and definitions, causing naming collisions with local variables or helper theorems.

### Using `open scoped`

The `open scoped` command activates custom notation macros without bringing symbol names into the unqualified namespace:

```lean
import Mathlib.Algebra.BigOperators.Group.Finset
import Mathlib.Algebra.Pointwise.Set.Basic

-- Activates ∑ and ∏ notations as well as set-arithmetic operators (s + t, a • s)
open scoped BigOperators Pointwise

variable {α : Type*} [AddCommMonoid α] (s : Finset ℕ) (f : ℕ → α)

example : α := ∑ i ∈ s, f i
```

### Guidelines for Scoped Notations

1. Place `open scoped` declarations right after module `import` statements.
2. Group related scoped notations together (e.g., `open scoped BigOperators Pointwise Topology`).
3. For single definitions, you may also use `open scoped ... in def/theorem`.
