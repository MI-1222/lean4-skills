# Proof Simplification and Golfing in Lean 4

"Proof golfing" is the process of refactoring a working, verbose proof into a concise, idiomatic, and maintainable form. A well-golfed proof compiles faster, is easier to read, and is less vulnerable to upstream breakage.

---

## 1. Principles of Responsible Golfing

When simplifying proofs, adhere to this hierarchy of values:

1. **Correctness & Stability**: The proof must not rely on fragile heuristics or non-terminal `simp`.
2. **Readability**: A human mathematician should be able to follow the conceptual milestones. (Never sacrifice readability just to save one line).
3. **Compilation Speed**: Prefer decision procedures that terminate quickly over deep searches.
4. **Brevity**: Eliminate administrative boilerplate and redundant steps.

---

## 2. Common Simplification Patterns

### Pattern 1: Combining Sequential Rewrites

Never write multiple consecutive `rw` statements when a single list suffices:

```lean
-- ❌ VERBOSE
by
  rw [Nat.add_comm a b]
  rw [Nat.add_assoc]
  rw [Nat.mul_comm]

-- ✅ CLEAN
by
  rw [Nat.add_comm a b, Nat.add_assoc, Nat.mul_comm]
```

### Pattern 2: Eliminating Unnecessary Intermediate `have` Blocks

If a `have` hypothesis is immediately consumed in the next line and never referenced again, inline it:

```lean
-- ❌ VERBOSE
have h1 : Continuous (f ∘ g) := Continuous.comp hf hg
exact h1

-- ✅ CLEAN: Inlined with dot notation
exact hf.comp hg
```

### Pattern 3: Replacing Manual Deduction with Decision Procedures

Do not manually apply transitivity, commutativity, and symmetry to solve linear inequalities or algebra; let automation handle it:

```lean
-- ❌ FRAGILE MANUAL PROOF (5 lines)
have h1 : a + 1 ≤ b + 1 := Nat.succ_le_succ hab
have h2 : b + 1 ≤ c := hbc
exact le_trans h1 h2

-- ✅ ROBUST & INSTANT (1 line)
omega
```

#### Decision Tactic Cheat Sheet

- **`omega`**: Presburger arithmetic on `ℕ`, `ℤ` (inequalities, addition, multiplication by constants, modulo).
- **`linarith`**: Linear arithmetic on `ℚ`, `ℝ` (ordered rings/fields).
- **`ring`**: Ring equalities (polynomial identities like $(a+b)^2 = a^2 + 2ab + b^2$ over any commutative ring).
- **`gcongr`**: Generalized congruence for relations (e.g. proving $f(a) \le f(b)$ from $a \le b$ using monotonicity).
- **`tauto`**: Propositional tautologies (conjunctions, disjunctions, negations).

### Pattern 4: Switching from Tactic Mode to Clean Term Mode

Simple existential introductions, conjunctions, or direct lemma applications are often much cleaner in term mode:

```lean
-- ❌ TACTIC OVERHEAD
theorem exists_even : ∃ n : ℕ, n = 2 * 1 := by
  use 2
  rfl

-- ✅ IDIOMATIC TERM MODE
theorem exists_even : ∃ n : ℕ, n = 2 * 1 :=
  ⟨2, rfl⟩
```

For conjunctions:

```lean
-- ❌ VERBOSE
by
  constructor
  · exact hA
  · exact hB

-- ✅ CONCISE
⟨hA, hB⟩
```

---

## 3. The Golfing Danger Zone: What NOT to Do

Avoid these antipatterns during simplification:

1. **The Opaque One-Liner**: Compressing a 30-line complex theorem into an unreadable 100-character lambda term full of nested projections (`h.1.2.1.2`). If a reader cannot identify the mathematical idea, keep intermediate `have` statements with descriptive names.
2. **Replacing Robust Steps with Fragile `aesop`**: Relying on unconstrained `aesop` to close an entire multi-step mathematical theorem makes compilation unpredictable.
3. **Stripping Type Annotations from Ambiguous Terms**: If golfing causes the compiler to spend more heartbeats inferring types, re-introduce explicit type hints `(x : ℝ)`.
