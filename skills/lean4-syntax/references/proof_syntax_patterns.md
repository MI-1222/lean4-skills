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

### Syntax Specifications:

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
