# `simp` Discipline and Hygiene in Lean 4

The simplifier (`simp`) is one of Lean 4's most powerful tactics. However, undisciplined use of `simp` is the leading cause of fragile proofs, performance degradation, and upstream/downstream compilation breakage.

---

## 1. The Golden Rule: No Non-Terminal `simp`

### What is a Non-Terminal `simp`?

A non-terminal `simp` is a naked invocation of `simp` in the middle of a proof that does not close the goal, followed by subsequent tactics:

```lean
-- ❌ DANGEROUS: Non-terminal simp
theorem bad_example (n : ℕ) (h : n + 0 = m) : n = m := by
  simp           -- Leaves goal: n = m
  exact h        -- Depends on the exact normal form produced by `simp`
```

### Why Non-Terminal `simp` is Forbidden

1. **Extreme Fragility**: As Mathlib grows, new `@[simp]` lemmas are continually added. An open `simp` that leaves goal `A` today might leave goal `A'` tomorrow when a new simplification rule fires earlier. Your proof will break without warning.
2. **Obscurity**: A human (and an AI agent) reading the proof cannot tell which lemmas were applied or what the expected intermediate state was.
3. **Performance Overhead**: An open `simp` scans hundreds of simp lemmas in the environment, consuming heartbeats on every compilation.

### The Remedy: Explicit or Terminal Only

- **If `simp` closes the goal**: Using `simp` as the final tactic (`simp` or `simp [h]`) is completely acceptable. If Mathlib gets smarter in the future, it will still close the goal.
- **If `simp` is intermediate**: You **must** restrict the lemma set using `simp only [...]`, use `dsimp`, or rewrite explicitly with `rw` / `simp_rw`.

```lean
-- ✅ ROBUST: Non-terminal using `simp only`
theorem good_example (n : ℕ) (h : n = m) : n + 0 = m := by
  simp only [Nat.add_zero]
  exact h
```

---

## 2. Choosing the Right Simplifier Variant

Lean 4 provides several specialized tools. Select the right tool for the job:

| Tool                   | When to Use                                | Mechanism                                                                                 |
| :--------------------- | :----------------------------------------- | :---------------------------------------------------------------------------------------- |
| `simp only [...]`      | Intermediate simplification in a proof     | Uses strictly the listed lemmas; completely immune to global simp changes                 |
| `simp` (terminal)      | Closing a goal at the end of a branch      | Uses default simp lemmas + local hypotheses                                               |
| `dsimp` / `dsimp only` | Definitional reduction without proof steps | Reduces terms definitionally (e.g., unfolding definitions, projections, β-reduction)      |
| `simp_rw [...]`        | Sequential rewriting under binders         | Chained `simp only` for rewrites inside `∀`, `∃`, or lambda abstractions where `rw` fails |
| `simp [-lemma_name]`   | Suppressing a misbehaving global simp rule | Temporarily disables a specific simp lemma that produces the wrong normal form            |

---

## 3. How to Convert an Open `simp` to `simp only`

When you have drafted a proof using an open `simp`, never leave it in the codebase. Convert it to `simp only`:

### Technique 1: Using `simp?`

Change `simp` to `simp?` (or `simp? [extra_lemma]`):

```lean
by
  simp?
```

Lean will output a "Try this:" suggestion in the infoview/diagnostics:

```lean
-- Try this: simp only [Nat.add_zero, MulZeroClass.mul_zero]
```

Replace `simp?` with the proposed `simp only [...]` call.

### Technique 2: Minimizing the Lemma List

Often `simp?` lists 10 lemmas when only 2 were actually necessary. Test removing lemmas from the `simp only [...]` brackets until you find the minimal set that advances the proof.

### Technique 3: Automated CLI Extraction Workflow for AI Agents

For autonomous coding agents operating via headless CLI without an interactive VS Code Infoview, follow this 3-step automated extraction pipeline:

1. **Inject `simp?` Temporarily**:
   Replace the open `simp` in the source file with `simp?`.
2. **Capture the `Try this:` Info Diagnostic**:
   Query compiler diagnostics using either `check_syntax.py` (from `lean4-syntax`) or `lean_goal.py` (from `lean4-interactive-proof`):

   ```bash
   # Method A: Via check_syntax.py (fast compilation & diagnostic collection)
   python3 <skills-path>/lean4-syntax/scripts/check_syntax.py <file-path>
   # Look for: [INFO   ] L<line>:C<col> (lean-compiler) Try this: simp only [...]

   # Method B: Via lean_goal.py (LSP-based diagnostic extraction)
   python3 <skills-path>/lean4-interactive-proof/scripts/lean_goal.py <file-path> --line <line-num>
   # Inspect the "diagnostics" array in the JSON response for "message": "Try this: simp only [...]"

   # Method C: Via parse_diagnostics.py + lake env lean
   lake env lean <file-path> 2>&1 | python3 <skills-path>/lean4-cli/scripts/parse_diagnostics.py
   ```

3. **Automate Replacement**:
   - Extract the suggested string after `Try this: `.
   - **Modern Lean Note (4.35+)**: Compiler output may prepend tactic action metadata tags (e.g. `Try this: [apply] simp only [...]`). Always strip `\[[a-zA-Z]+\]\s*` using regex:
     ```python
     # Stripping ^\[[a-zA-Z]+\]\s* ensures metadata tags like [apply] are removed
     # without corrupting valid Lean brackets (e.g. simp only [lemma])
     clean_simp = re.sub(r"^\s*\[[a-zA-Z]+\]\s*", "", raw_suggestion.split("Try this:", 1)[-1].strip())
     ```
   - Use `replace_file_content` to substitute `simp?` with the extracted `clean_simp` (e.g. `simp only [Nat.add_zero, MulZeroClass.mul_zero]`).
   - Re-validate with `check_syntax.py` to ensure the goal closes cleanly without residual warnings.

---

## 4. `@[simp]` Lemma Hygiene (Authoring New Lemmas)

When defining new lemmas in your project, do not blindly attach `@[simp]`. Follow these strict criteria:

### Checklist for `@[simp]` Lemmas

1. **Is the rewrite canonical and directional?**
   - Good: `x + 0 = x` (always simplifies).
   - Bad: `x + y = y + x` (symmetry creates an infinite loop).
2. **Is the Left-Hand Side (LHS) in normal form?**
   - If other existing simp lemmas can simplify your proposed LHS, the simplifier will rewrite the subterm first and your lemma will never fire.
   - _Example_: Stating `@[simp] lemma foo : f (x + 0) = g x` is bad because `x + 0` is rewritten to `x` before `foo` matches. State `f x = g x` instead.
3. **Does the Right-Hand Side (RHS) avoid re-creating the LHS?**
   - Never introduce rules where the LHS can be reconstructed downstream, triggering non-terminating simplification loops.
4. **Prefer Scoped or Local Simp**:
   - If a rewrite is only useful within a single file or mathematical domain, use `attribute [local simp] my_lemma` inside the section rather than exporting it globally.

---

## 5. Interaction Between `simp` and Calculation Chains (`calc`)

When structuring algebraic derivations or analytical inequalities, `simp` is frequently used to simplify subterms before entering a `calc` block. Maintain the following discipline:

### Rule 1: Always Align `calc` LHS with the Actual Goal State After `simp`

- Never write the first line of a `calc` chain based on what you _hoped_ `simp` would produce or what the goal was _prior_ to `simp`.
- If `simp` (or `filter_upwards with ω; simp [...]`) rewrites the expression into a canonical representation (e.g., `(m:ℝ)⁻¹` instead of `1/(m:ℝ)`), start the `calc` chain directly from that canonical representation.
- Attempting to force the pre-simplification representation triggers `invalid 'calc' step` type mismatches.

### Rule 2: One Upfront Normalization Pass

- Normalize terms upfront with an explicit `simp only [...]` pass, and then rely on domain-specific decision procedures (`gcongr`, `linarith`, `ring`, `omega`, `positivity`) inside the `calc` steps.
- Avoid calling open `simp` within intermediate steps of a `calc` chain, as it obscures which subterm is being transformed and easily degrades elaboration performance.

### Rule 3: Recovery Recipes for Syntactic `calc` Mismatches

If an `invalid 'calc' step` error occurs due to representation differences between `simp`'s output and your intended `calc` starting point (e.g., division `/` vs reciprocal `* ·⁻¹`, or monus `-`):

1. **Definitional Alignment via `change`**:
   ```lean
   change (m : ℝ)⁻¹ * ∑ k : Fin m, f k ≤ ε
   calc
     (m : ℝ)⁻¹ * ∑ k : Fin m, f k ≤ ... := by gcongr
   ```
2. **Goal Anchoring via `show ... from calc`**:
   ```lean
   show (m : ℝ)⁻¹ * |x| ≤ ε from
     calc
       (m : ℝ)⁻¹ * |x| ≤ ... := by gcongr
   ```
3. **Pre-normalization via `dsimp only`**:
   Definitional rewrites like `dsimp only [div_eq_mul_inv]` adjust syntax prior to `calc` without accumulating proof terms or heartbeats.
   (See full details in [documentation_and_style.md](documentation_and_style.md#41-recovery-recipes-for-invalid-calc-step-syntactic--definitional-mismatches)).
