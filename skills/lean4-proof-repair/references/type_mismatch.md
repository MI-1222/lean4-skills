# Type Mismatch Repair Guide

In Lean 4, `type mismatch` is the most common compiler and elaborator error. It occurs when a term's inferred type cannot be unified with the expected type under Definitional Equality (DefEq).

---

## 1. Anatomy of the Error

A typical Lean 4 error message looks like:

```text
type mismatch
  term
has type
  ActualType
but is expected to have type
  ExpectedType
```

When diagnosing, ask three questions:

1. Are `ActualType` and `ExpectedType` definitionally equal, but Lean failed to see it without unfolding?
2. Are they different mathematical types that need an explicit coercion (e.g., `Nat` to `Real`)?
3. Is an implicit argument incorrectly instantiated, or are function arguments provided in the wrong order?

---

## 2. Common Causes & Prescriptions

### 2.1 Numeric & Type Coercions (`coe` / `cast`)

Lean 4 uses strict typing. A natural number `n : ℕ` is not definitionally an integer `ℤ` or real `ℝ`.

- **Symptom**: `has type ℕ but is expected to have type ℝ`.
- **Prescription**:
  - Insert coercion arrow `↑n` or explicit type ascription `(n : ℝ)`.
  - Use `norm_cast` or `exact_mod_cast` when proving equations involving casts.
  - Use `push_cast` to push casts through arithmetic operations before simplifying.

#### Example Fix

```diff
- example (n : ℕ) : (n : ℝ) + 0 = n := by
-   exact add_zero n
+ example (n : ℕ) : (n : ℝ) + 0 = n := by
+   exact add_zero (n : ℝ)
```

---

### 2.2 Proposition vs. Boolean (`Prop` vs. `Bool`)

Lean distinguishes between the sort of propositions `Prop` and the datatype `Bool`.

- **Symptom**: `has type Bool but is expected to have type Prop` (or vice-versa), often in `if` conditions or decidability predicates.
- **Prescription**:
  - To turn `b : Bool` into `Prop`, use `b = true` or `(b : Prop)` via coercion.
  - To turn decidable `P : Prop` into `Bool`, use `decide P`.
  - In tactics, replace `simp [if_pos]` with `simp [decide_eq_true]` or open `Classical`.

#### Example Fix

```diff
- example (b : Bool) (h : b) : b = true := by
+ example (b : Bool) (h : b = true) : b = true := by
    exact h
```

---

### 2.3 Definitional Equality Gaps (Unfolding Needed)

Lean may fail to unify terms if a definition has not been unfolded or simplified.

- **Symptom**: `ActualType` and `ExpectedType` appear identical or mathematically equivalent, but elaboration rejects `exact h`.
- **Prescription**:
  - Use `change ExpectedType` to force Lean to check definitional equality.
  - Use `dsimp [my_def]` or `unfold my_def` to expose the underlying structure.
  - If they are only propositionally equal (via a lemma `h_eq : Actual = Expected`), rewrite with `rw [h_eq]` or `simp_rw [h_eq]`.

#### Example Fix

```diff
  def MyType := ℕ
  example (x : MyType) (h : x = 0) : x + 0 = 0 := by
-   exact h
+   change (x : ℕ) + 0 = 0
+   rw [add_zero]
+   exact h
```

---

### 2.4 Implicit Argument Misinference (`@` or Named Arguments)

When applying polymorphic lemmas or lemmas with typeclass parameters, Lean might guess the wrong implicit type or universe.

- **Symptom**: Error mentions unresolved metavariables `?m.123` or complains about expected types containing variables that don't match.
- **Prescription**:
  - Explicitize arguments using `@lemma_name arg1 arg2 ...`.
  - Provide specific named arguments: `apply lemma_name (α := ℝ) (x := y)`.
  - Constrain the type with an explicit type hint: `(h : ExpectedType)`.

#### Example Fix

```diff
- example (h : ∀ {α : Type} (x : α), x = x) : (1 : ℕ) = 1 := by
-   exact h
+ example (h : ∀ {α : Type} (x : α), x = x) : (1 : ℕ) = 1 := by
+   exact @h ℕ 1
```

---

### 2.5 Term Mode vs. Tactic Mode Confusion

- **Symptom**: `expected type P but got by ...` or missing `by` keyword.
- **Prescription**:
  - If a theorem definition ends with `:= proof_term`, ensure it is pure term syntax.
  - If tactics are used, start with `:= by`.
  - Inside a tactic block, if calling a lemma directly, use `exact lemma` rather than bare `lemma`.

---

## 3. Systematic Diagnostic Workflow

When encountering a `type mismatch`:

1. **Compare Head Symbols**: Look at the top-level constructors of `ActualType` and `ExpectedType`.
   - If one is `... = ...` and the other is `... ↔ ...`, use `propext` or `iff_iff_eq`.
   - If one is `Subtype` or `Set` membership and the other is the carrier type, use `.val` or `Subtype.property`.
2. **Check Context**: Use `have : ExpectedType := ActualTerm` to pinpoint whether the mismatch is inside a subterm.
3. **Inspect with PP**: Set `set_option pp.all true` temporarily to reveal hidden implicit arguments, universes, and typeclass instances.
