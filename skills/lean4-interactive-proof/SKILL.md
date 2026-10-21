---
name: lean4-interactive-proof
description: Interactively prove theorems in Lean 4 by inspecting tactic states (proof goals) and compiler diagnostics step-by-step using LSP. Use whenever writing, completing, debugging, or verifying formal mathematical proofs in Lean 4 or Mathlib, inspecting intermediate proof goals, inserting `done` to expose remaining subgoals, or verifying whether a tactic successfully advanced the proof state.
compatibility: Target Lean 4.14.0+ (Verified on Lean v4.35.0 and contemporary Mathlib). Requires Python 3.10+ for scripts/lean_goal.py.
metadata:
  target-lean-version: '>=4.14.0'
  tested-lean-version: 'v4.35.0'
  tested-mathlib-version: 'v4.35.0'
  version: '1.3.0'
---

# Lean 4 Interactive Proof

This skill provides an interactive, tactic-by-tactic workflow for formal theorem proving in Lean 4. By querying the Lean 4 Language Server (LSP) in real-time, AI agents can inspect active proof goals (hypotheses and targets), observe goal state transformations, and catch compiler diagnostics immediately after each tactic application.

---

## 0. Environment & Version Compatibility

| Component        | Target / Supported          | Verified / Tested Version             | Notes                                                |
| :--------------- | :-------------------------- | :------------------------------------ | :--------------------------------------------------- |
| **Lean 4 / LSP** | `^4.14.0` (4.14.0+)         | `v4.35.0` (Release, commit `eb6cafb`) | Verified via `lake serve` / `lean --server` JSON-RPC |
| **Mathlib**      | Compatible with target Lean | Contemporary with Lean `v4.35.0`      | Provides proof state inspection on Mathlib theories  |
| **Python**       | `>=3.10`                    | `3.14.x`                              | Required for `scripts/lean_goal.py`                  |

### Version-Specific LSP & Tactic Notes

- **LSP JSON-RPC**: `scripts/lean_goal.py` interfaces with standard Lean 4 LSP protocol (`textDocument/plainGoal`).
- **Goal Completion**: Use `done` or focus dots `·` to ensure subgoals are fully discharged and prevent goal state desynchronization.
- **Incremental Diagnostics**: Modern Lean 4 reports position-indexed elaboration errors immediately upon file mutation.

---

## 1. Core Philosophy: One Step at a Time

Writing formal proofs in Lean 4 differs fundamentally from general software programming:

- **Strict type checking**: Minor discrepancies in types or implicit coercions fail the entire proof.
- **Tactic state feedback**: Every tactic changes the remaining goals. Generating full proofs blindly without observing intermediate states leads to hallucinations and infinite loops.
- **Immediate validation**: Apply exactly one tactic, inspect the resulting goal state and compiler diagnostics, and decide the next step based on the verified state. Never accumulate unverified tactics.

---

## 2. Inspecting Proof Goals (`lean_goal.py`)

The skill bundles `scripts/lean_goal.py`, a standalone, zero-dependency Python script using only the Python standard library to communicate with `lean --server` or `lake serve`.

### CLI Usage

```bash
python3 <skill-path>/scripts/lean_goal.py <lean_file> --line <line_number> [--col <col_number>] [--timeout <seconds>]
```

- `<lean_file>`: Path to the `.lean` source file.
- `--line` (`-l`): **1-indexed** line number (e.g., the line where a tactic was just applied).
- `--col` (`-c`): **1-indexed** column number. Optional; defaults to the end of the line (excluding newline), which is usually the desired position after writing a tactic.
- `--timeout` (`-t`): Elaboration timeout in seconds (default: `8.0`).

### Output Schema (JSON)

````json
{
  "success": true,
  "line": 12,
  "column": 18,
  "rendered": "```lean\nx y : Nat\nh : x = y\n⊢ x + 0 = y\n```",
  "goals": ["x y : Nat\nh : x = y\n⊢ x + 0 = y"],
  "is_done": false,
  "has_sorry": false,
  "diagnostics": [
    {
      "line": 12,
      "column": 5,
      "severity": "Error",
      "message": "tactic 'rewrite' failed..."
    }
  ],
  "error": null
}
````

- `rendered`: Markdown-formatted string representing the active proof goals, hypotheses, and target.
- `goals`: Array of individual subgoal strings. Empty when all goals are discharged.
- `is_done`: Boolean flag indicating whether the proof of the _target declaration_ is complete (`true` only when goals are solved, no local compiler errors exist, and no local `sorry` remains).
- `scope`: Target declaration range `{"start_line": int, "end_line": int}` used to isolate diagnostics.
- `has_local_errors`: Boolean flag indicating whether compiler errors exist inside the target declaration.
- `has_local_sorry`: Boolean flag indicating whether `sorry` is active inside the target declaration.
- `has_file_errors`: Boolean flag indicating whether any compiler errors exist in the whole file.
- `has_file_sorry`: Boolean flag indicating whether any `sorry` exists in the whole file.
- `has_sorry`: Convenience alias for `has_local_sorry`.
- `has_errors`: Convenience alias for `has_local_errors`.
- `diagnostics`: List of compiler diagnostics with an `is_local: bool` tag indicating whether each diagnostic belongs to the target declaration scope.
- `success`: Boolean indicating whether the LSP query completed successfully.

---

## 3. The Interactive Proving Workflow

Always follow this 5-step loop when constructing or repairing a proof:

```mermaid
graph TD
    A["Step 1: Check Baseline Goal (`lean_goal.py`)"] --> B["Step 2: Formulate Single Tactic"]
    B --> C["Step 3: Edit File & Re-run `lean_goal.py`"]
    C --> D{"Diagnostics or Goal?"}
    D -- "Error in diagnostics" --> E["Step 4a: Rollback or Fix Tactic"]
    E --> B
    D -- "Valid goal transformation" --> F{"Is Done? (`is_done: true`)"}
    F -- "No, remaining goals" --> B
    F -- "Yes, proof completed" --> G["Step 5: Clean Up & Final Verify"]
```

### Step 1: Query Baseline Goal

Inspect the goal immediately after `:= by` (or at the current point of the incomplete proof):

```bash
python3 scripts/lean_goal.py MathProof.lean --line 10
```

Analyze the returned `rendered` text:

- What are the current hypotheses (above `⊢`)?
- What is the exact target type (after `⊢`)?

#### Critical Pitfall: Querying Lines Containing `sorry`

In Lean 4, `sorry` is a macro tactic that artificially discharges the active goal. Consequently:

- If you query the end of a line that already contains `sorry` (e.g. `have h : P := by sorry`), `plainGoal` reports **`rendered: "no goals"`** because `sorry` already closed the goal at that exact position.
- `lean_goal.py` detects `sorry` (in diagnostics or target line content) and sets **`is_done: false`** and **`has_sorry: true`**, preventing false positives.

**How to Inspect the True Unsolved Goal**:

1. **Remove `sorry`**: Temporarily delete or comment out `sorry`, leaving a blank line with proper indentation, then query that line.
2. **Query before `sorry`**: Query the column directly preceding `sorry` (`--col <N>`).
3. **Query an empty indented line**: Place the query on a fresh, indented line immediately following `by`.

### Step 2: Formulate Candidate Tactic

Choose the most direct tactic for the active goal:

- **Definitional equality**: `rfl`
- **Simplification / arithmetic**: `simp`, `ring`, `omega` (Lean 4.7+ Core), `linarith`
- **Hypothesis introduction**: `intro x h`
- **Rewriting / Substitution**: `rw [h]`, `subst h`
- **Splitting cases**: `cases n`, `rcases ...` (Lean 4.7+ Core), `obtain ...`
- **Exact match**: `exact h`

### Step 3: Apply Tactic and Immediately Query

Add the tactic to the file, and run `lean_goal.py` on the modified line.

- Check `diagnostics`: If any `"severity": "Error"` appears, do not proceed to subsequent lines. Fix or replace the failing tactic immediately.
- Check `rendered`: Note how the goal and hypotheses transformed.
- **Harvest `Try this:` Suggestions**:
  When applying exploratory tactics (`simp?`, `exact?`, `apply?`, `rw?`, `grind?`), inspect the `"diagnostics"` array in the JSON returned by `lean_goal.py`. Look for informational entries containing `"Try this: <replacement>"`.
  **Note on Modern Lean (4.35+)**: Compiler messages may include metadata action tags like `Try this: [apply] exact <lemma>` or `Try this: [apply] simp only [...]`.
  Always sanitize the suggested replacement by stripping optional `[tag]` prefixes using `re.search(r"Try this:\s*(?:\[[a-zA-Z]+\]\s*)?([^\n]+)", msg)` before substituting the replacement code back into the file.

### Step 4: Handle Remaining Goals with `done`

When multiple subgoals might be created (e.g., after `induction` or `constructor`):

1. Insert `done` temporarily on the next line.
2. Run `lean_goal.py`.
3. If Lean reports an unsolved goal error on `done`, it prints exactly what subgoals remain.
4. Structure the subgoals using indentation or bullet points (`·`).

### Step 5: Verification & Cleanup

Once `is_done` returns `true` (or `rendered` displays `no goals` / `goals accomplished`):

1. Remove any temporary debugging tactics (e.g., temporary `done`).
2. Run a clean check over the whole proof: verify `diagnostics` has no errors and no `sorry` remaining.
3. Clean up redundancies (e.g., combine multiple consecutive rewrites `rw [h1]; rw [h2]` into `rw [h1, h2]`).

---

## 4. Diagnostics & Error Priority

When `diagnostics` contains messages, prioritize fixing them in this order:

1. **Syntax errors**: Missing brackets, invalid keywords, or indentation mismatches. Higher-level type errors are invalid until syntax is fixed.
2. **Type mismatch**: Argument type does not match parameter type. Explicitly supply type hints or examine implicit coercions.
3. **Tactic failures**: The tactic failed to apply (e.g., `rw` could not find pattern, or `linarith` found no contradiction).
4. **Unsolved goals**: Goal is incomplete. Use `done` or inspect `rendered`.
5. **Linter warnings**: Unused variables, non-terminal `simp`, or naming conventions.

---

## 5. Practical Examples

### Example: Proving Addition Symmetry with Induction

Given target file `AddComm.lean`:

```lean
theorem add_zero_eq (n : Nat) : n + 0 = n := by
  sorry
```

1. Query goal at line 1 (end of line `by`):

   ```bash
   python3 scripts/lean_goal.py AddComm.lean --line 1
   ```

   Output:

   ```lean
   n : Nat
   ⊢ n + 0 = n
   ```

2. Replace `sorry` with `rfl`:

   ```lean
   theorem add_zero_eq (n : Nat) : n + 0 = n := by
     rfl
   ```

3. Query goal at line 2:
   ```bash
   python3 scripts/lean_goal.py AddComm.lean --line 2
   ```
   Output:
   ```json
   {
     "is_done": true,
     "rendered": "no goals",
     "diagnostics": []
   }
   ```
   Proof is verified.

---

## 6. Lake Integration & Environment Handling

- If the Lean file belongs to a Lake package (with `lakefile.lean` or `lakefile.toml`), `lean_goal.py` automatically detects the project root and launches `lake serve`. This ensures all Mathlib modules and dependencies are properly resolved.
- For standalone single files outside any Lake project, `lean_goal.py` automatically falls back to `lean --server`.
- Unicode mathematical characters ($\forall, \exists, \le, \mathbb{N}$) are properly handled via UTF-16 code unit calculation.
