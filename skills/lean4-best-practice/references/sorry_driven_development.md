# Sorry-Driven Development (Top-Down Proving)

Sorry-driven development is the gold standard for formalizing complex mathematical theorems in Lean 4. Rather than proving lemmas bottom-up without knowing if they suffice, top-down proving establishes the logical architecture first and fills in technical gaps incrementally.

---

## 1. Why Bottom-Up Proving Fails for LLMs and Humans

A common failure mode in formal proof engineering is "bottom-up rabbit-holing":

1. The user attempts to prove auxiliary Lemma A, Lemma B, and Lemma C before touching the main theorem.
2. Hours are spent wrestling with technical details of Lemma B.
3. Once proved, it turns out Lemma B makes assumptions incompatible with the main theorem or is completely unnecessary.

**The Top-Down Advantage**:

- Lean treats `sorry` as a valid proof token (an axiom of type `False` under the hood).
- You can state the target theorem, structure its proof skeleton using `have` or sub-theorems proved by `sorry`, and verify that Lean accepts the overarching argument immediately.
- If the global proof structure does not typecheck, you discover the flaw in seconds rather than days.

---

## 2. The 5-Step Top-Down Proving Workflow

```text
[Step 1: State Target Theorem]
               |
               v
[Step 2: Skeleton Proof with `have ... := by sorry`]
               |
               v
[Step 3: Solve the Hardest Case First]
               |
               v
[Step 4: Extract Standalone Helper Lemmas]
               |
               v
[Step 5: Fill Sorries One by One with `done`]
```

### Step 1: State the Target Theorem

Write down the exact theorem statement. Ensure all binder types and typeclasses are correctly specified, and end with `:= by sorry`:

```lean
theorem cauchy_schwarz {V : Type*} [NormedAddCommGroup V] [InnerProductSpace ℝ V]
    (x y : V) : |⟪x, y⟫| ≤ ‖x‖ * ‖y‖ := by
  sorry
```

### Step 2: Build the High-Level Skeleton with `have`

Formulate the mathematical milestones of the proof using `have` steps, giving each a `sorry`:

```lean
theorem cauchy_schwarz {V : Type*} [NormedAddCommGroup V] [InnerProductSpace ℝ V]
    (x y : V) : |⟪x, y⟫| ≤ ‖x‖ * ‖y‖ := by
  by_cases hy : y = 0
  · -- Case y = 0
    sorry
  · -- Case y ≠ 0
    have h_quad : ∀ t : ℝ, 0 ≤ ‖x + t • y‖ ^ 2 := by sorry
    have h_discriminant : ∀ a b c : ℝ, (∀ t, 0 ≤ a * t ^ 2 + b * t + c) → b ^ 2 ≤ 4 * a * c := by sorry
    have h_cs : |⟪x, y⟫| ^ 2 ≤ ‖x‖ ^ 2 * ‖y‖ ^ 2 := by sorry
    sorry
```

Check with `lake env lean` or LSP that the outer logic flows and compiles.

### Step 3: Work on the Hardest Case First

In case analysis or induction, **never start with the trivial base case**.

- Trivial cases (e.g. `n = 0`, `y = 0`, empty set) are deceptive; they almost always succeed.
- If the inductive step or non-zero case fails because of a missing hypothesis, all effort spent polishing the base case is wasted.
- Leave base cases with `sorry`, crack the hardest case first, and only return to the base cases when the core argument is sound.

### Step 4: Extract Standalone Helper Lemmas

If an intermediate `have` block exceeds 10–15 lines, extract it out of the main theorem into an independent private or local helper lemma:

```lean
-- Move helper lemma before main theorem
private lemma quad_nonneg_discriminant (a b c : ℝ) (ha : 0 < a)
    (h : ∀ t : ℝ, 0 ≤ a * t ^ 2 + b * t + c) :
    b ^ 2 ≤ 4 * a * c := by
  sorry

theorem cauchy_schwarz ... := by
  ...
  have h_disc := quad_nonneg_discriminant a b c ha h_nonneg
  ...
```

**Benefits**:

- Drastically reduces cognitive load in the main proof.
- Keeps elaboration time for the main theorem small.
- Allows independent verification and parallel proof development.

### Step 5: Fill Sorries One by One with `done`

When tackling a specific `sorry`:

1. Delete the `sorry`.
2. Add `done` at the end of the tactic block.
3. Lean's diagnostic will pinpoint the exact goal that remains to be solved.
4. Apply one tactic at a time, checking the live goal state with `lean_goal.py` (or LSP).
5. When the goal is closed, remove `done`.

---

## 3. Dealing with Multiple Sorries (TODO Protocol)

When managing a project with numerous sorries:

1. **Catalog**: List every `sorry` with file and line coordinates.
2. **Strict Queue**: Never work on multiple sorries simultaneously in the same file. Pick one, lock focus, and resolve it completely before moving to the next.
3. **Regression Check**: After replacing a `sorry`, immediately run:
   ```bash
   lake env lean path/to/File.lean
   ```
   Confirm that closing the sorry did not alter variable names or types relied upon downstream.
