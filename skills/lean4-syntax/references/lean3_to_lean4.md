# Lean 3 to Lean 4 Syntax Migration & Anti-Pattern Guide

Because LLM training corpora still contain large amounts of obsolete Lean 3 code, coding agents frequently hallucinate deprecated Lean 3 syntax. Lean 4 is a fundamentally redesigned language and parser; mixing Lean 3 constructs will cause fatal parsing or elaboration errors.

---

## 1. Syntax Comparison Table

| Category                    | Lean 3 Deprecated / Invalid      | Lean 4 Canonical Syntax                               | Elaboration Failure & Rationale                                                                                          |
| :-------------------------- | :------------------------------- | :---------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------- |
| **Proof Mode Initiation**   | `begin ... end`                  | `by ...`                                              | `begin` is not a keyword in Lean 4; it is parsed as an undefined identifier, triggering an immediate elaboration error.  |
| **Line Separators**         | Trailing comma `,` after tactics | **Newline** or semicolon `;`                          | Commas are reserved for arguments and tuple constructors. Placing a comma at line end causes syntax errors.              |
| **Declaration Type**        | `lemma` (isolated usage)         | `theorem`                                             | While Mathlib defines `lemma` as an alias, `theorem` is the standard Lean 4 core command.                                |
| **Rewrite Direction**       | `rw [<- h]` (ASCII arrow)        | `rw [← h]` (Unicode `\l` or `\left`)                  | ASCII `<-` conflicts with monad bind syntax and is rejected by the tactic parser.                                        |
| **Calculation Steps**       | `calc a = b : proof`             | `calc a = b := proof` (Lean 4.0.0+)                   | Lean 4 uses the assignment symbol `:=` instead of the typing colon `:` to link steps to proofs.                          |
| **Conjunction Splitting**   | `split` (for $P \land Q$)        | `constructor` or `refine ⟨?_, ?_⟩`                    | **Most common trap**. In Lean 4, `split` decomposes conditionals (`if-then-else` and `match`); it fails on conjunctions. |
| **Type Declarations**       | `inductive Foo :=`               | `inductive Foo where` (Lean 4.14+)                    | The assignment `:=` syntax for `inductive`, `structure`, and `class` is deprecated since Lean 4.14 in favor of `where`.  |
| **Opaque Constants**        | `constant c : α`                 | `opaque c : α` (Lean 4.0.0-m5+)                       | The `constant` command was renamed to `opaque`.                                                                          |
| **Library Lemma Search**    | `library_search`                 | `exact?` or `apply?` (Lean 4.7+ Core)                 | Lean 3's `library_search` was replaced by `exact?` and `apply?` in Lean 4 Core.                                          |
| **Induction Clauses**       | `induction n with n ih`          | `induction n with \| zero => ... \| succ n ih => ...` | Lean 4 unifies induction with pattern matching; explicit branch constructors are required, or bind via `intro`.          |
| **Hypothesis Introduction** | `intro h,` or `intros x y,`      | `intro h` or `intro x y`                              | Never append trailing commas to tactic arguments. Lean 4.20+ accepts `_` for inaccessible names.                         |
| **Subgoal Scoping**         | Braces `{ tactic1, tactic2 }`    | Focus dot `· tactic1` (`\.`)                          | Braces exist in some macros, but Mathlib 4 standard requires the bullet point `·` with 2-space indentation.              |
| **Local Proof (Have)**      | `have h : P, from proof`         | `have h : P := proof`                                 | The `from` keyword has been retired in favor of universal `:=`.                                                          |
| **Local Typeclasses**       | `haveI : C := pf` / `letI`       | Anonymous `have : C := pf` (Lean 4.14+)               | `haveI` is deprecated in Lean 4.14+; anonymous `have` automatically registers into instance synthesis.                   |
| **Kernel Decision**         | `decide!`                        | `decide +kernel` (Lean 4.15+)                         | `decide!` was removed in Lean 4.15 in favor of `decide +kernel`.                                                         |
| **Multi Rewrite & Close**   | `rwa [h] at *`                   | `rw [h] at * <;> assumption` (Lean 4.35+)             | Multi-target `rwa at *` and `rwa at h₁ h₂` are deprecated in Lean 4.35+; use explicit chaining with `<;> assumption`.    |

---

## 2. Frequent Compilation Error Messages & Mechanical Fixes

### Error 1: `unexpected token ','; expected ...`

- **Root Cause**: Trailing comma at the end of a tactic line or between binders.
- **Fix**: Remove the trailing comma completely; rely on a newline or semicolon.

```lean
-- Bad (Lean 3)
theorem bad_comma (p : Prop) (hp : p) : p := by
  intro h,
  exact h,

-- Good (Lean 4)
theorem good_comma (p : Prop) (hp : p) : p := by
  intro h
  exact h
```

### Error 2: `unexpected token 'have'; expected command`

- **Root Cause**: Indentation collapse. In a nested `have ... := by`, if the tactic inside `by` is not indented deeper than the `have` keyword, Lean 4 assumes the `by` block is empty and treats `have` as an illegal top-level command.
- **Fix**: Indent the tactic following `:= by` by at least 2 spaces deeper than `have`.

```lean
-- Bad (Lean 3 style / offside error)
theorem bad_have (p : Prop) (hp : p) : p := by
  have h : p := by
  exact hp
  exact h

-- Good (Lean 4)
theorem good_have (p : Prop) (hp : p) : p := by
  have h : p := by
    exact hp
  exact h
```

### Error 3: `tactic 'split' failed, ...`

- **Root Cause**: Using `split` to split a target $P \land Q$ or structural goal.
- **Fix**: Use `constructor` to split the goal into two subgoals, or use `refine ⟨?_, ?_⟩`.

```lean
-- Bad (Lean 3)
theorem bad_split (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  split
  · exact hp
  · exact hq

-- Good (Lean 4)
theorem good_split (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  constructor
  · exact hp
  · exact hq
```

### Error 4: `expected '=>'` or `unexpected token 'with'`

- **Root Cause**: Lean 3 style `induction n with n ih`.
- **Fix**: Use `induction ... with | zero => ... | succ n ih => ...` or omit the names and bind with `intro`.

```lean
-- Bad (Lean 3)
theorem bad_ind (n : Nat) : n + 0 = n := by
  induction n with n ih

-- Good (Lean 4)
theorem good_ind (n : Nat) : n + 0 = n := by
  induction n with
  | zero => rfl
  | succ n ih => rw [Nat.add_zero]
```

### Error 5: `unexpected token ':='; expected ':'` (or vice-versa)

- **Root Cause**: Confusion between `calc` step syntax and type annotation syntax.
- **Fix**: In `calc`, write `a = b := proof` (not `: proof`). In `have`, write `have h : Type := proof`.
