# Mathematical Structures and Typeclass Hierarchy in Mathlib

This guide explains how to interact with Mathlib's algebraic, topological, and order hierarchies, avoid common typeclass elaboration pitfalls, and explicitly guide instance synthesis.

---

## 1. Multiple Inheritance and "Invisible Dependencies"

Mathlib's abstract mathematics relies on Lean 4's typeclass system using structural extension (`extends`):

- Algebraic structures (e.g., `Semigroup` $\to$ `Monoid` $\to$ `Group` $\to$ `CommGroup` $\to$ `Ring` $\to$ `CommRing` $\to$ `Field`).
- Topological & geometric structures (e.g., `TopologicalSpace` $\to$ `UniformSpace` $\to$ `MetricSpace` $\to$ `NormedAddCommGroup`).

Research on Mathlib's internal dependency graphs reveals that **74.2% of all dependency edges are "invisible" (synthesized edges)**—generated implicitly by the elaborator through typeclass synthesis, operator resolution (`HAdd`, `HMul`), numeric literal conversion (`OfNat`), and coercions (`Coe`).

While this provides standard mathematical notation, it creates massive search spaces for typeclass resolution when clues are ambiguous, occasionally leading to `maximum synth pending depth reached` or `maxHeartbeats exceeded`.

---

## 2. Mandatory Discipline: Disable `autoImplicit`

In standard Lean 4, unquoted lowercase identifiers (e.g., `x`, `n`, `g`) in declarations are automatically generalized as implicit universal variables if `autoImplicit` is left on.

In mathematical formalization, this frequently introduces accidental free variables that break typeclass resolution or create subtly invalid lemma statements:

```lean
-- Set at the top of every Mathlib formalization file or section:
set_option autoImplicit false
```

With `autoImplicit false`, any undeclared variable produces an immediate compiler error, forcing explicit typing and preventing typeclass confusion.

---

## 3. Explicit Type Annotations to Pin Search Anchors

When expressions contain polymorphic constants, the elaborator must search multiple candidate instance paths simultaneously. Pinning expressions with explicit type annotations eliminates backtracking.

### Numeric Literals and Zero/One

- Writing `0` or `1` without context forces Lean to guess whether it is `Nat`, `Int`, `Real`, or a generic monoid identity.
- **Best Practice**: Use `(0 : ℝ)` or annotate binders `(x : ℝ)`.

### Coercions and Embeddings

- When embedding natural numbers or integers into real or complex numbers, Lean uses coercion operators ($\uparrow$).
- If the target type is ambiguous, write `((n : ℝ))` or `(n : ℝ)` explicitly to prevent failed instance synthesis.

```lean
-- Ambiguous:
example (n : ℕ) : (n : ℝ) ≥ 0 := by ...

-- Distinct and firmly anchored:
example (n : ℕ) : 0 ≤ (n : ℝ) := by
  exact Nat.cast_nonneg n
```

---

## 4. Local Instance Injection with `haveI` and `letI`

When working with quotient structures, field extensions, localized rings, or conditional metric spaces, the global typeclass synthesizer might fail to discover an instance that holds conditionally in the local context.

Instead of fighting the synthesizer, inject the instance directly into the local hypothesis context using `haveI` or `letI`:

| Tactic                          | Usage & Characteristics                                                                                                        |
| :------------------------------ | :----------------------------------------------------------------------------------------------------------------------------- |
| `haveI : InstanceType := proof` | Injects an instance into the local typeclass cache without retaining the term in the value context (erased after elaboration). |
| `letI : InstanceType := proof`  | Injects a definitionally transparent instance into the context (preserves definitional equality).                              |

### Example: Supplying a Local Group Instance

```lean
import Mathlib.Algebra.Group.Basic

variable {G : Type*}

-- When a subgroup or custom structure provides an instance conditionally:
theorem subgroup_element_mul_inv (H : Subgroup G) (x : H) :
    x * x⁻¹ = 1 := by
  -- In case automatic instance resolution fails for the subtype H:
  haveI : Group H := Subgroup.toGroup H
  exact mul_inv_cancel x
```

---

## 5. Avoiding Instance Resolution Loops

Instance synthesis loops typically occur when:

1. Two typeclasses define reciprocal conversion instances without a clear decrease in structure complexity.
2. A lemma expects a general algebraic structure, but a concrete type's bundled fields fail unification.

### Diagnostic Techniques

- Inspect instance synthesis paths:
  ```lean
  set_option trace.Meta.synthInstance true in
  #check ...
  ```
- If heartbeats expire during instance synthesis, verify that:
  - All type parameters have explicit class constraints (e.g., `[CommRing R]` rather than just `(R : Type*)`).
  - No conflicting duplicate instances exist in the active `open` namespaces.
