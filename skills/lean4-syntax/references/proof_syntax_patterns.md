# Proof Syntax Patterns in Lean 4

Lean 4 supports two complementary styles of proving mathematical statements: **Term mode** (directly constructing the proof object) and **Tactic mode** (interactively stepping through goal transformations via `by ...`).

---

## 1. Term Mode vs. Tactic Mode

### Principle of Minimal Tactic Overhead

A common anti-pattern among LLMs is writing `:= by exact <term>` or `:= by apply <lemma>` for one-line trivialities. Initiating tactic mode creates metavariables and runs elaboration machinery unnecessarily.

- **Use Term Mode** for direct lemma applications, lambda abstractions (`fun ... => ...`), and tuple/constructor packaging.
- **Use Tactic Mode** for multi-step derivations, goal rewriting (`rw`, `simp`), induction, and automated decision procedures (`omega`, `ring`, `linarith`).

```lean
-- Clean Term Mode (No metavariable overhead)
theorem my_imp_self (P : Prop) : P → P :=
  fun h => h

-- Redundant Tactic Mode (Avoid if term is trivial)
theorem my_imp_self_redundant (P : Prop) : P → P := by
  exact fun h => h

-- Appropriate Hybrid: Tactic mode for state transitions, Term mode for local components
theorem and_comm_proof (P Q : Prop) : P ∧ Q → Q ∧ P := by
  intro h
  have hq : Q := h.right
  have hp : P := h.left
  exact ⟨hq, hp⟩
```

---

## 2. Calculation Chains (`calc`)

The `calc` construct formats chains of equalities, inequalities, or equivalences step-by-step.

### 2.1. Syntax Specifications

1. The first line establishes the start: `<lhs> <rel> <intermediate> := <proof>`
2. All continuation lines use `_` as a placeholder for the preceding right-hand side: `_ <rel> <next> := <proof>`
3. The relation `<rel>` must satisfy the `Trans` typeclass in the environment (e.g., `=`, `≤`, `<`, `⊆`, `↔`).
4. Proofs can be Term mode terms or mini-tactic blocks prefixed with `by`.

```lean
import Mathlib.Algebra.Ring.Basic

variable (a b c : Nat)

theorem calc_example (h1 : a = b) (h2 : b ≤ c) : a + 1 ≤ c + 1 := by
  calc
    a + 1 = b + 1 := by rw [h1]
    _     ≤ c + 1 := by omega
```

### 2.2. Critical Interaction: `simp` Before `calc`

A common failure mode is running a simplifier tactic (e.g., `simp`, `dsimp`, or `filter_upwards with ω; simp [...]`) immediately before opening a `calc` block, and writing the first `calc` line based on what the goal was **before** `simp` ran, or what you **hoped** it became.

**The Golden Rule:** Start the `calc` chain from the **actual goal state produced by `simp`**, never the pre-simplification expression.

```lean
-- ❌ ERROR: calc chain starts with pre-simp expression
filter_upwards with ω; simp [Real.norm_eq_abs]
-- If simp already transformed |(1/(m:ℝ)) * ∑...| into (m:ℝ)⁻¹ * |∑...|
calc |(1/(m:ℝ)) * ∑ k : Fin m, f k|
    = |(m:ℝ)⁻¹ * ∑ k : Fin m, f k| := by rw [one_div]
  _ = ...
-- ERROR: invalid 'calc' step, left-hand side is (m:ℝ)⁻¹ * |∑ ...| but is expected to be |(1/(m:ℝ)) * ∑ ...|

-- ✅ CORRECT: Inspect goal after simp, start calc with the already-simplified form
filter_upwards with ω; simp [Real.norm_eq_abs]
calc (m:ℝ)⁻¹ * |∑ k : Fin m, f k|
    _ ≤ (m:ℝ)⁻¹ * ∑ k : Fin m, |f k| := by
      gcongr; exact Finset.abs_sum_le_sum_abs _ _
  _ ≤ ...
```

### 2.3. Respect Canonical Normal Forms (Don't Fight `simp`)

Mathlib's simplifier rewrites expressions into canonical normal forms:

- `(m : ℝ)⁻¹` rather than `1 / (m : ℝ)`
- `a * b⁻¹` rather than `a / b` (in group/field contexts)
- `|x|` (`Real.norm_eq_abs`) rather than `‖x‖` when working with reals under scalar absolute values

**Guidelines:**

1. **Check the actual goal with LSP/interactive tools**: If `simp` changed the representation, accept the canonical form in the `calc` chain rather than introducing manual reversal steps (`rw [← one_div]`).
2. **One simplification pass**: Let `simp only [...]` normalize terms upfront, then perform mathematical estimation/reasoning in `calc` using specialized tools (`gcongr`, `linarith`, `positivity`, `ring`). Do not invoke non-terminal `simp` inside individual `calc` steps.

---

## 3. Structured Destructuring (`obtain`, `rcases`)

Primitive `cases` tactics often auto-generate confusing names like `h_1`, leading to collisions. Use `obtain` and `rcases` to explicitly bind names and enforce types.

### `obtain`: Conjunction and Existence Decomposition

Use `obtain ⟨vars, ...⟩ : type := term` to enforce clean type signatures during destructuring.

```lean
import Mathlib.Data.Set.Basic

variable {α : Type} (p q : α → Prop)

-- Decomposing existential and conjunction simultaneously
theorem obtain_example (h : ∃ x, p x ∧ q x) : ∃ x, q x := by
  obtain ⟨x, _, hq⟩ := h
  exact ⟨x, hq⟩
```

### `rcases`: Pattern Matching on Disjunctions

Use `rcases term with ⟨hp, _⟩ | hr` to split disjunctions ($P \lor Q$) into clear branches.

```lean
theorem rcases_example (P Q R : Prop) (h : (P ∧ Q) ∨ R) : P ∨ R := by
  rcases h with ⟨hp, _⟩ | hr
  · left
    exact hp
  · right
    exact hr
```

---

## 4. Logical Constructors & Structural Proofs

| Proposition            | Term Mode Constructor     | Tactic Mode Equivalent                           |
| :--------------------- | :------------------------ | :----------------------------------------------- |
| **$P \land Q$**        | `⟨hp, hq⟩`                | `constructor` then solve both subgoals           |
| **$P \lor Q$**         | `Or.inl hp` / `Or.inr hq` | `left; exact hp` or `right; exact hq`            |
| **$\exists x, P(x)$**  | `⟨x, hpx⟩`                | `use x` or `refine ⟨x, ?_⟩`                      |
| **$P \iff Q$**         | `⟨h_mp, h_mpr⟩`           | `constructor` (produces `⊢ P → Q` and `⊢ Q → P`) |
| **Falsehood ($\bot$)** | `h.elim` / `nomatch h`    | `contradiction` or `exfalso`                     |

---

## 5. Mathlib Code Conventions: Lambdas, Line Width, and `show`

When formalizing proofs adhering to Mathlib conventions:

### 5.1. 100-Character Line Limit

- Mathlib standardizes on **100 characters** per line.
- Do not artificially wrap lines at 80 characters. If an expression fits cleanly under 100 characters, keep it on a single line.

### 5.2. Mathematical Lambdas (`↦` vs `=>`)

- For ordinary mathematical functions, maps, and abstractions, write `fun x ↦ ...` (`\mapsto` or `\map`).
- Reserve `=>` strictly for pattern matching (`match ... with`), `do` syntax, or metaprogramming.

```lean
-- ✅ IDIOMATIC MATHLIB
def add_one : ℕ → ℕ := fun n ↦ n + 1

-- ❌ AVOID
def add_one_old : ℕ → ℕ := fun n => n + 1
```

### 5.3. `show` Syntax Discipline

- Use `show P by tac` when providing a tactic proof block.
- Use `show P from term` only when providing a direct proof term.
- Never write `show P from by tac` (`from` before `by` is redundant).

### 5.4. Typeclass Instance Registration in Proofs

- Use standard anonymous `have : Class α := ⟨proof⟩` in proofs to supply local instances.
- Avoid legacy `haveI`—it only inlines the value and is flagged by Mathlib's `haveI`/`letI` style linter. Use `letI` only when definitional equality must be preserved.
