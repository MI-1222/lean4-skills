# Unsolved Goals Troubleshooting Guide

The error `unsolved goals` indicates that tactic execution terminated (or a focused block exited) while one or more proof goals remained unproven.

---

## 1. Anatomy & Diagnostic Strategy

```text
unsolved goals
case right
p q : Prop
hp : p
⊢ q
```

When Lean signals unsolved goals, the immediate objective is to find **where** the unaccounted goal branched and what assumptions are missing.

---

## 2. Prescriptions & Techniques

### 2.1 Enforce Subgoal Isolation with Focus Dots (`·`)

Never leave multiple open goals flowing into subsequent tactic lines. Unstructured tactics can accidentally close an unintended goal, leaving the earlier goal stranded at the end.

- **Rule**: Whenever a tactic produces multiple goals (e.g. `constructor`, `induction`, `cases`, `refine ⟨?_, ?_⟩`), indent and isolate every branch using focus dots `·` (`\.`):

```lean
example (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  constructor
  · exact hp
  · exact hq
```

If a branch fails to close its goal before the next dot, Lean flags an error immediately on the dot, pinning down the exact location of the missing step.

---

### 2.2 Pinpoint with `done` (Temporary Debug Probe)

Insert `done` temporarily at any point in the proof to assert that all goals should be closed by that stage:

```lean
theorem my_thm : ... := by
  step1
  step2
  done  -- Lean will display all remaining open goals at this exact line
```

If goals remain, Lean reports `unsolved goals` right at `done`, showing the precise local context and goal target.

> [!WARNING]
> **Mathlib Linter Conflict (`'done' does nothing`)**:
> In modern Mathlib, leaving `done` in completed code where all goals have already been resolved triggers the unused tactic linter:
>
> ```text
> warning: Unused tactic linter: 'done' does nothing.
> ```
>
> Always treat `done` strictly as an **ephemeral debug probe**: once you have inspected the open subgoals and structured your branches, delete or comment out `done`.

---

### 2.3 Close Bulk / Side Conditions with `all_goals`

Tactics like `apply` or `rw` may spawn technical side conditions (e.g., non-negativity `0 ≤ x` or index bounds `i < n`).
Instead of handling them manually in sequence, handle boilerplate goals in bulk:

```lean
example : ... := by
  apply complex_lemma
  all_goals
    try positivity
    try assumption
```

---

### 2.4 Unresolved Metavariables

Sometimes the goal is closed, but Lean reports `unsolved goals` with metavariables like `⊢ ?m.412`.

- **Cause**: A lemma was applied that introduced an existential or implicit parameter that was never instantiated.
- **Fix**: Replace `apply lemma` with `refine lemma ...` and supply the missing term explicitly, or instantiate the variable with `let` or `have`.

---

## 3. Workflow Summary

1. Check line numbers: Does the error point to the end of a `·` block or the end of the `by` block?
2. If at the end of the proof, backtrack to the last tactic that split the goal (`constructor`, `cases`, `induction`).
3. Wrap each branch in `·` with +2 spaces of indentation.
4. If a goal seems empty or trivial, try `assumption`, `rfl`, or `trivial`.
5. Remove temporary `done` probes before final verification to avoid Mathlib's unused tactic linter warnings.
