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

## 4. Local Instance Injection: Plain `have` (Lean 4.14+) vs `haveI` / `letI`

When working with quotient structures, field extensions, localized rings, or conditional metric spaces, the global typeclass synthesizer might fail to discover an instance that holds conditionally in the local context.

### Modern Lean 4 & Mathlib Rule: Prefer Plain `have` (Lean 4.14+)

In modern Lean 4 (4.14+), a plain `have : InstanceType := proof` **automatically registers** the instance in the local typeclass cache!
The legacy `haveI` tactic (deprecated since Lean 4.14) only inlines the value and is flagged by Mathlib's `haveI`/`letI` style linter.

| Tactic / Pattern             | Usage & Characteristics                                                                                      |
| :--------------------------- | :----------------------------------------------------------------------------------------------------------- |
| `have : InstanceType := pf`  | **Standard in Lean 4.14+/Mathlib.** Registers the instance into the local typeclass cache cleanly.           |
| `letI : InstanceType := pf`  | Injects a definitionally transparent instance into the context when definitional equality must be preserved. |
| `haveI : InstanceType := pf` | _Legacy._ Avoid in Mathlib code (deprecated since Lean 4.14); flagged by linter.                             |

### Example: Supplying a Local Group Instance

```lean
import Mathlib.Algebra.Group.Basic

variable {G : Type*}

-- When a subgroup or custom structure provides an instance conditionally:
theorem subgroup_element_mul_inv (H : Subgroup G) (x : H) :
    x * x⁻¹ = 1 := by
  -- In modern Lean 4, plain have registers the instance into typeclass search:
  have : Group H := Subgroup.toGroup H
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

---

## 6. Avoiding Instance Pollution (Sub-σ-algebras, Orders, Metrics)

### The Problem

When multiple instances of the same typeclass exist in the same scope (e.g., sub-σ-algebras `MeasurableSpace Ω`, multiple metrics `MetricSpace α`, or alternative orderings `Preorder β`), Lean's elaborator preferentially selects the **most recently bound local constant** rather than the ambient instance.

This leads to cryptic errors like:

```text
type mismatch
  synthesized: mSub, inferred: inst✝
```

or 500k+ heartbeat timeout explosions.

### Prevention & Recovery Patterns

#### Pattern 1: Name and Pin the Ambient Instance

Name the ambient instance in the declaration signature:

```lean
theorem my_theorem (Ω β : Type*) [m0 : MeasurableSpace Ω] [MeasurableSpace β]
    (Z : Ω → β) (hZ : Measurable Z) : ... := by
```

If the signature is fixed (e.g., from an upstream project or library specification), capture the ambient instance on the very first line before creating any local sub-structures:

```lean
  let m0 : MeasurableSpace Ω := ‹MeasurableSpace Ω›
```

_(The `‹…›` French quote syntax captures the currently active local instance)._

#### Pattern 2: Use Explicit `@` Application for Ambient Facts

When referencing lemmas that rely on the ambient structure, explicitly pass the pinned ambient instance:

```lean
  -- Explicitly anchor to ambient m0:
  have h_meas : @Measurable Ω β m0 _ Z := hZ
```

#### Pattern 3: Avoid Local Class-Typed Bindings When Possible

Instead of declaring `let mSub : MeasurableSpace Ω := ...` early in the proof (which immediately shadows the ambient instance), inline the expression or introduce it only after all ambient facts have been elaborated.

#### Pattern 4: Exclude Unwanted Section Variables via `omit` (Lean 4.11+)

When an ambient section declares a typeclass variable that a specific lemma or theorem does not require (which would otherwise pollute search or induce looping):

```lean
-- Exclude MeasurableSpace Ω for this specific lemma:
omit [MeasurableSpace Ω] in
theorem independent_lemma (n : ℕ) : n + 0 = n := by
  rfl
```
