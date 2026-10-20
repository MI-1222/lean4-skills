# Instance Synthesis Failure Guide

The error `failed to synthesize instance` indicates that Lean's typeclass resolution system could not find an instance of a required typeclass (e.g., `Decidable`, `Group`, `MetricSpace`, `Fintype`) in the current scope or library.

---

## 1. Anatomy of the Error

```text
failed to synthesize instance
  ClassName TargetType
```

Common instances that fail:

- `Decidable P` (e.g. inside `if P then ... else ...` or `Finset.filter`)
- `Fintype α` or `Finite α`
- Algebraic structures: `AddCommGroup G`, `Ring R`, `Field K`
- Order / Metric structures: `LinearOrder α`, `TopologicalSpace X`

---

## 2. Common Scenarios & Fixes

### Scenario 1: Classical Logic Missing (`Decidable`)

When using classical mathematics (e.g. non-constructive case analysis or set filters), Lean demands proof that a proposition is decidable.

- **Symptom**: `failed to synthesize instance Decidable (x ∈ s)` or `Decidable (x = y)`.
- **Prescription**:
  - Open classical scope at file or namespace level:
    ```lean
    open scoped Classical
    ```
  - Or invoke `classical` tactic locally inside the proof:
    ```lean
    example : ... := by
      classical
      ...
    ```

---

### Scenario 2: Missing Typeclass Assumption in Context

The theorem statement forgot to declare that a type variable satisfies a structure.

- **Symptom**: `failed to synthesize instance Group G` when applying a group lemma.
- **Prescription**:
  - Add the typeclass hypothesis in brackets to the theorem signature or `variable` block:
    ```diff
    - theorem my_thm (G : Type*) (a b : G) : a * b = b * a := by
    + theorem my_thm (G : Type*) [CommGroup G] (a b : G) : a * b = b * a := by
    ```
  - If it applies across multiple theorems in a file:
    ```lean
    variable {G : Type*} [Group G]
    ```

---

### Scenario 3: Local Instance in Proof (Anonymous `have` (Lean 4.14+) vs `haveI`)

When an instance is constructed dynamically within a proof rather than globally available.

- **Symptom**: An instance was proven via `have h : Fintype s := ...`, but downstream tactics still complain that `Fintype s` cannot be synthesized.
- **Why**: In Lean 4, a _named_ hypothesis `have h : Fintype s := ...` is placed into the context as an ordinary hypothesis, not as an active typeclass instance.
- **Prescription**:
  - Use an **anonymous** `have` (`have : Fintype s := ...`) (Lean 4.14+). Anonymous `have` bindings for typeclasses are automatically registered into the local instance cache.
  - Avoid legacy `haveI` (deprecated since Lean 4.14) in Mathlib—it only inlines the value and triggers Mathlib's `haveI`/`letI` linter warning.
  - Use `letI : Fintype s := ...` only if definitional equality of the instance data needs to be preserved.

---

### Scenario 4: Type Inference Ambiguity

Lean knows an instance exists for a canonical type, but type inference hasn't determined the carrier type yet.

- **Symptom**: `failed to synthesize instance Add ?m.1234` or `typeclass instance problem is stuck`.
- **Prescription**:
  - Give an explicit type annotation to the expression: `(0 : ℝ)` instead of `0`.
  - Type-ascribe parameters: `fun (x : ℕ) => ...`.

---

### Scenario 5: Typeclass Resolution Loop / Timeout

- **Symptom**: `maximum synthInstance heartbeats exceeded`.
- **Prescription**:
  - Check for cyclic instance definitions or redundant overlapping instances.
  - Temporarily raise the limit to confirm if it terminates:
    ```lean
    set_option synthInstance.maxHeartbeats 40000
    ```
  - Provide the instance explicitly using term mode or `@` notation:
    ```lean
    @lemma_name _ inst_var ...
    ```

---

### Scenario 6: Instance Pollution & Shadowing (`synthesized: ..., inferred: ...`)

When multiple instances of the same typeclass exist in the same scope (e.g., sub-σ-algebras `MeasurableSpace Ω`, distinct topologies on $X$, or alternative orderings).

- **Symptom**:
  ```text
  type mismatch
    synthesized: mSub, inferred: inst✝
  ```
  or sudden 500k+ heartbeat explosions when applying standard lemmas.
- **Why**: Lean's elaborator prioritizes the most recently bound local constant (`let mSub : MeasurableSpace Ω := ...`), shadowing the ambient instance.
- **Prescription**:
  1. **Name and Pin the Ambient Instance**: Name it in the signature `[m0 : MeasurableSpace Ω]` or capture it on line 1: `let m0 : MeasurableSpace Ω := ‹MeasurableSpace Ω›`.
  2. **Pass Ambient Facts Explicitly with `@`**: Use `@Measurable Ω β m0 _ Z` when invoking ambient properties.
  3. **Strip Unneeded Section Classes with `omit` (Lean 4.11+)**: Use `omit [MeasurableSpace Ω] in` to keep unneeded outer typeclasses from poisoning resolution. (Note: place `omit [...] in` _before_ any `/-- ... -/` docstring to avoid `unexpected token 'omit'` parser errors; see `header_fence_and_docstrings.md`).

---

## 3. Quick Reference

| Problem                                              | Immediate Action                                                                                 |
| :--------------------------------------------------- | :----------------------------------------------------------------------------------------------- |
| Missing `Decidable`                                  | Add `open scoped Classical` or tactic `classical`                                                |
| Missing structure on parameter `α`                   | Add `[Structure α]` to binder signature                                                          |
| Named `have h : Class α` not picked up               | Change to anonymous `have : Class α := ...` (Lean 4.14+) (or `letI` if defeq needed)             |
| Ambiguous metavariable `?m`                          | Add explicit type ascription `(x : TargetType)`                                                  |
| Synthesis loop / timeout                             | Check conflicting imports; provide explicit instance term with `@`                               |
| Instance pollution (`synthesized: m, inferred: ...`) | Pin ambient instance (`[m0 : ...]`), use `@` for ambient lemmas, or `omit [...] in` (Lean 4.11+) |
