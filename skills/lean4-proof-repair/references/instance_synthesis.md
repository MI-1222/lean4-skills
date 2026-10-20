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

### Scenario 3: Local Temporary Instance (`haveI` / `letI`)

When an instance is constructed dynamically within a proof rather than globally available.

- **Symptom**: An instance was proven via `have h : Fintype s := ...`, but downstream tactics still complain that `Fintype s` cannot be synthesized.
- **Why**: Standard `have` puts the hypothesis into the local context as an ordinary variable, not into the typeclass cache.
- **Prescription**:
  - Use `haveI` (have instance) or `letI` (let instance) to register it into typeclass resolution:
    ```diff
    - have h : Fintype s := by ...
    + haveI : Fintype s := by ...
    ```
  - Alternatively, use `have := ...; exact ...` with explicit parameter passing.

---

### Scenario 4: Type Inference Ambiguity

Lean knows an instance exists for a canonical type, but type inference hasn't determined the carrier type yet.

- **Symptom**: `failed to synthesize instance Add ?m.1234`.
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

## 3. Quick Reference

| Problem                            | Immediate Action                                          |
| :--------------------------------- | :-------------------------------------------------------- |
| Missing `Decidable`                | Add `open scoped Classical` or tactic `classical`         |
| Missing structure on parameter `α` | Add `[Structure α]` to binder signature                   |
| Instance exists in proof as `have` | Replace `have` with `haveI` or `letI`                     |
| Ambiguous metavariable `?m`        | Add explicit type ascription `(x : TargetType)`           |
| Synthesis loop                     | Check conflicting imports; provide explicit instance term |
