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

| Tactic           | Target Domain & Problem Class                        | Strengths                                                                       | Limitations                                                                              |
| :--------------- | :--------------------------------------------------- | :------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------- |
| **`omega`**      | Presburger arithmetic on `ℕ`, `ℤ`                    | Linear inequalities, addition, constant multiplication, integer division/modulo | Fails on variable-by-variable products ($a \cdot b$), powers, roots, or opaque functions |
| **`linarith`**   | Linear arithmetic on `ℚ`, `ℝ` (ordered rings/fields) | Linear combinations of inequalities, contradictions                             | Purely linear; cannot reason about nonlinear terms directly                              |
| **`ring`**       | Commutative rings/semirings                          | Polynomial identities, algebraic simplification ($(a+b)^2 = a^2 + 2ab + b^2$)   | Equalities only; ignores inequalities and order relations                                |
| **`nlinarith`**  | Nonlinear inequalities on `ℚ`, `ℝ`                   | Heuristic nonlinear reasoning (e.g., squares are non-negative $x^2 \ge 0$)      | Heuristic and slower; incomplete for arbitrary polynomials                               |
| **`positivity`** | Non-negativity, positivity, non-zero tests           | Automatically proves `0 ≤ x`, `0 < x`, `x ≠ 0` from types and structures        | Verifies sign properties only; does not solve arbitrary inequalities                     |
| **`gcongr`**     | Generalized congruence                               | Solves relations like $f(a) \le f(b)$ via monotonicity                          | Requires registered monotonicity lemmas (`@[gcongr]`)                                    |
| **`tauto`**      | Propositional logic                                  | Tautologies involving `∧`, `∨`, `¬`, `→`, `↔`                                   | Propositional level only; does not unfold domain definitions                             |

---

#### Critical Boundaries & Pitfalls of `omega`

While `omega` is the premier decision procedure for natural and integer arithmetic, be aware of its strict theoretical boundaries:

1. **Nonlinear Terms Are Opaque**:
   - `omega` cannot solve variable multiplication ($a \cdot b$), exponentials ($2^n$), or square roots.
   - _Failure Example_: `theorem foo (n : ℕ) : n ≤ n * n` fails under `omega` alone because $n \cdot n$ is treated as an uninterpreted black box.
   - _Fix_: Establish algebraic properties using lemmas or `nlinarith` / `positivity`, or perform case analysis (`cases n`).

2. **Truncated Subtraction (Monus on `ℕ`)**:
   - In `ℕ`, subtraction truncates at zero: $3 - 5 = 0$.
   - Identities like $(a - b) + b = a$ require an explicit side-condition $b \le a$ (`Nat.sub_add_cancel`).
   - When `omega` struggles with expressions containing `a - b`, supply the necessary boundary condition `have h : b ≤ a := ...` or rewrite with `Nat.sub_add_cancel` before calling `omega`.

3. **Effective Multi-Tactic Combination Patterns**:
   - **Polynomial expansion + Linear bound**: Use `ring` to expand or normalize equations, then feed the result into `linarith` or `omega`:
     ```lean
     have h_id : (x + 1)^2 = x^2 + 2 * x + 1 := by ring
     ```
   - **Positivity + Nonlinear inequalities**: Use `positivity` to discharge non-negativity side conditions when taking square roots or clearing denominators:
     ```lean
     have h_pos : 0 ≤ a * b := by positivity
     ```
   - **Monotonicity + Arithmetic**: Use `gcongr` to strip away monotone function applications, leaving clean arithmetic goals for `omega`:
     ```lean
     -- Target: a + c ≤ b + d
     -- After gcongr: reduces to a ≤ b and c ≤ d, which omega solves
     ```

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
