# Performance and Heartbeat Optimization in Lean 4

Elaboration timeouts (`(deterministic) maximum number of heartbeats (200000) exceeded`) and slow type-checking are common obstacles in large proofs. This guide covers how to diagnose performance bottlenecks and apply principled optimizations.

---

## 1. What are "Heartbeats"?

In Lean 4, a "heartbeat" is a deterministic measure of computational work (such as allocations and reductions performed by the elaborator and kernel), independent of CPU clock speed.

- The default limit is **200,000 heartbeats** per declaration.
- If a single theorem exceeds 200,000 heartbeats, it indicates an exponential search, an infinite typeclass resolution loop, or massive definitional unfolding.

### The Cardinal Rule: Never Use `maxHeartbeats` as a Final Fix

```lean
-- ❌ PROHIBITED AS A PERMANENT SOLUTION
set_option maxHeartbeats 1000000 in
theorem slow_proof : ... := by ...
```

- Increasing `maxHeartbeats` is acceptable **only as a temporary diagnostic aid** while isolating which step is lagging.
- Bumping heartbeats masks algorithmic inefficiency, increases CI build times, and inevitably times out again when adjacent code changes.

---

## 2. Profiling Slow Proofs

To find the exact line causing the slowdown, enable Lean's built-in profiler:

```lean
set_option trace.profiler true in
theorem my_theorem : ... := by
  step1
  step2
```

Or enable detailed compiler diagnostics:

```lean
set_option diagnostics true in
theorem my_theorem : ... := by
  ...
```

The diagnostics report will display:

- Time spent in elaboration vs type-checking.
- Heartbeats consumed by each tactic invocation.
- Number of typeclass resolution queries and instances synthesized.

---

## 3. The 4 Main Causes of Performance Explosions & Their Remedies

### Cause 1: Open `simp` Scanning Too Many Lemmas

- **Problem**: Calling `simp` without restrictions tests hundreds of rewriting candidates against large expressions.
- **Remedy**: Replace with `simp only [lemma1, lemma2]` or `dsimp only [...]`.

### Cause 2: Deep Definitional Unfolding (WHNF / DefEq Timeouts)

- **Problem**: When comparing complex polymorphic terms (e.g. measures, norms, integrals, category compositions), Lean tries to unfold definitions to verify definitionally equal terms (`isDefEq`). If definitions are transparent, Lean cascades through multiple layers of nested structures.
- **Remedy: The Irreducible Wrapper Pattern**:
  Freeze complex definitions during intermediate lemmas using `@[irreducible]`:

```lean
/-- Frozen alias that elaborator will not unfold during DefEq checks -/
@[irreducible]
def myComplexTermFrozen (x : BigType) : BigType := myComplexTerm x

-- Prove a lemma stating the equality for when unfolding is deliberately needed
lemma myComplexTermFrozen_def (x : BigType) :
    myComplexTermFrozen x = myComplexTerm x := by
  unfold myComplexTermFrozen; rfl
```

Using the frozen definition prevents the elaborator from expanding the internals, dropping heartbeat counts from 500k+ to <10k.

### Cause 3: Typeclass Search Cascades & Missing Type Annotations

- **Problem**: When a term has uninstantiated metavariables or implicit parameters, Lean initiates typeclass synthesis across thousands of potential paths.
- **Remedy**:
  - Add explicit type annotations: `(x : ℝ)` instead of letting Lean guess whether `x` is `ℝ`, `ℂ`, or an arbitrary topological ring.
  - Pin type parameters explicitly in lemma applications: `exact @my_lemma ℝ _ _ x`.

### Cause 4: Overuse of Heavy Automated Tactics (`aesop`, `linarith`)

- **Problem**: Tactics like `aesop` and open `linarith` perform extensive tree searches and collect all hypotheses in the local context.
- **Remedy**:
  - For linear integer/natural arithmetic: use `omega` (vastly faster and complete for Presburger arithmetic).
  - Scope `linarith`: use `linarith only [h1, h2]` to avoid parsing irrelevant local hypotheses.
  - For `aesop`: configure rule sets strictly or replace with targeted `constructor`, `ext`, and `simp only`.

---

## 4. Decomposing Monolithic Theorems

If a theorem remains slow after tactic tuning:

1. Identify natural intermediate milestones in the argument.
2. Break each milestone into a separate `private lemma` or `local lemma`.
3. Verify each helper lemma independently.
   Lean elaborates declarations in separate tasks; modularizing proofs allows the compiler to parallelize work across CPU cores and keeps individual declaration heartbeats under 20,000.
