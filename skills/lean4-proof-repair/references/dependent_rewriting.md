# Dependent Rewriting & Motive Errors Guide

The error `tactic 'rewrite' failed, motive is not type correct` is one of the most frustrating errors in Lean 4. It arises when applying `rw` to replace a term inside a dependent type where other terms or hypotheses depend on the variable being replaced.

---

## 1. Why the Error Happens

Under the hood, `rw [h]` attempts to eliminate an equality `h : a = b` using `Eq.rec` with a generated predicate ("motive") `P : α → Prop` such that `P a` is the current goal and `P b` is the target goal.

However, if:

1. Another variable in the local context has a type depending on `a` (e.g., `v : Fin a`), OR
2. The goal has subterms whose types depend on `a`,

Lean cannot form a valid simple motive without also replacing `a` inside those dependent types. When it fails to do so uniformly, it reports:

```text
tactic 'rewrite' failed, motive is not type correct
  fun (_a : α) => ...
```

---

## 2. Prescriptions & Alternative Tactics

### Strategy 1: Use `subst` for Variable Equalities

If the equality is of the form `x = e` or `e = x` where `x` is a variable in the local context:

- `rw` will almost always fail if `x` appears in other hypotheses.
- `subst x` (or `subst h`) safely substitutes `x` everywhere in the context and the goal simultaneously, clearing `x` and `h`.

```diff
  example (n m : ℕ) (h : n = m) (v : Fin n) : Fin m := by
-   rw [h] at v
+   subst h
    exact v
```

---

### Strategy 2: Revert Dependent Hypotheses Before Rewriting

If `h_dep` depends on the term being rewritten, revert `h_dep` into the goal before `rw`, then introduce it back:

```diff
  example (n m : ℕ) (h : n = m) (v : Fin n) (P : Fin m → Prop) : P (cast (by rw [h]) v) := by
-   rw [h]
+   revert v
+   rw [h]
+   intro v
```

By reverting `v`, the goal becomes `∀ v : Fin n, ...`, allowing `rw` to replace `n` in both the quantifier and the body simultaneously.

---

### Strategy 3: Use `simp_rw` or `simp only`

The `simp` engine traverses the term structure differently from `rw`. It uses congruence lemmas (`congr`) rather than raw `Eq.rec`, making it far more robust with dependent types.

- If `rw [h]` fails with a motive error, try:
  ```lean
  simp_rw [h]
  ```
  or:
  ```lean
  simp only [h]
  ```

---

### Strategy 4: Use `congr` or `congr!` for Subterm Rewriting

When the equality affects only an argument of a function, use congruence tactics to drill down into the subterm without rewriting the whole expression:

- `congr` / `congr!`: Strips matching function constructors and isolates arguments as separate goals.
- `gcongr`: Powerful generalized congruence tactic in Mathlib for equalities and inequalities.

```lean
example (f : ℕ → ℕ) (a b : ℕ) (h : a = b) : f a = f b := by
  -- Instead of rw [h]:
  congr 1
```

---

### Strategy 5: Heterogeneous Equality (`HEq`) and `heq_of_eq`

In cases where terms have types that are equal but not definitionally identical (such as vectors of length `n` vs. length `m` where `n = m`), Lean uses heterogeneous equality `a == b` (`HEq a b`).

- Use `obtain rfl := h` to perform substitution during pattern matching.
- Use `congr!` which automatically generates heterogeneous equality goals when necessary.

---

## 3. Decision Matrix for Rewriting Failures

| Goal Situation                            | Best Tactic                                         | Fallback        |
| :---------------------------------------- | :-------------------------------------------------- | :-------------- |
| `h : x = e` where `x` is a local variable | `subst x` or `obtain rfl := h`                      | `simp only [h]` |
| Other hypotheses in context depend on `x` | `revert dependent_hyp; rw [h]; intro dependent_hyp` | `subst h`       |
| Goal contains dependent arguments         | `simp_rw [h]`                                       | `congr!`        |
| Non-dependent functions, deep subterm     | `nth_rw 1 [h]`                                      | `change` + `rw` |
