# Indentation and Scope Rules in Lean 4

Lean 4 employs a strict parser-level **offside rule** similar to Python and Haskell. A 1-space misalignment can turn a new tactic into an argument of the previous tactic, or prematurely terminate a tactic block.

---

## 1. The Offside Rule & Baseline Columns

In a `by` block, the **baseline column** is determined by the starting column of the first tactic appearing after `by`.

```lean
theorem example_alignment (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  have h1 : p := hp   -- Baseline column = 2 (2 spaces from left margin)
  have h2 : q := hq   -- Must start at column 2
  exact ⟨h1, h2⟩      -- Must start at column 2
```

### Consequences of Misalignment:

- **Deeper indentation (> baseline)**: The parser interprets the line as an argument continuation of the preceding line.
- **Shallower indentation (< baseline)**: The parser terminates the current tactic block immediately.

```lean
-- Broken alignment:
theorem broken_indent (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  have h1 : p := hp
   have h2 : q := hq  -- ERROR: Column 3 instead of 2; parsed as argument continuation of h1!
  exact ⟨h1, h2⟩
```

---

## 2. Subgoal Scoping with Focus Dots (`·`)

When a tactic (such as `constructor`, `cases`, `rcases`, or `apply`) generates multiple subgoals, Mathlib 4 standard style requires isolating each branch with a focus dot `·` (Unicode `\cdot`, `U+00B7`).

### Rules for Focus Dots:

1. The bullet `·` must be placed at the **same indentation column** as the parent tactic level.
2. All tactics inside the bullet scope must be indented by **at least 2 spaces** relative to `·`.
3. The bullet scope **must completely solve (close)** the focused subgoal. Exiting the bullet while leaving unsolved goals triggers an immediate compile error.

```lean
theorem focus_dots_example (p q r : Prop) (hp : p) (hq : q) (hr : r) : (p ∧ q) ∧ r := by
  constructor
  · -- Subgoal 1: ⊢ p ∧ q
    constructor
    · exact hp  -- Nested focus for ⊢ p
    · exact hq  -- Nested focus for ⊢ q
  · -- Subgoal 2: ⊢ r
    exact hr
```

---

## 3. Nested `have` / `let` Scopes with `by`

The most common point of syntactic failure in agent-generated proofs is nesting a `by` block inside a `have` or `let` statement.

### The Problem:

When writing `have h : P := by`, if the subsequent tactic line is not indented deeper than the `have` keyword, the parser treats the `by` block as empty and closes it immediately. It then encounters the next tactic as an unexpected top-level token (`unexpected token 'have'; expected command`).

### Correct Pattern:

```lean
theorem have_nesting_correct (p : Prop) (hp : p) : p := by
  have h : p := by
    -- Indented at least 2 spaces deeper than 'have'
    exact hp
  exact h
```

### Single-Line Shorthand:

If the proof inside `have` is short, place `by` and the tactic on the same line or use Term mode:

```lean
theorem have_short (p : Prop) (hp : p) : p := by
  have h : p := by exact hp
  -- Or even better (Term mode):
  have h' : p := hp
  exact h'
```

---

## 4. `match` and `calc` Indentation

### `match` / `nomatch`

Pattern arms must align vertically and be indented beneath the `match`:

```lean
def nat_is_zero (n : Nat) : Bool :=
  match n with
  | 0 => true
  | _ + 1 => false
```

### `calc` Blocks

In `calc`, each relation step should align neatly:

```lean
theorem calc_indent_rule (a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c := by
  calc
    a = b := h1
    _ = c := h2
```

All continuation lines start with underscore `_` matching the position of the initial left-hand side.
