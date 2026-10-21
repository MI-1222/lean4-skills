# Domain-Specific Proof Patterns in Mathlib

Mathlib covers vast mathematical domains, each having specialized abstractions, standard lemmas, and targeted automation tactics. This guide collects verified, high-frequency proof patterns across analysis, measure theory, geometry, algebra, and number theory.

---

## 1. Quick Tactic Selection Matrix by Domain

Before writing manual step-by-step rewrites, check if your goal falls into one of Mathlib's automated decision procedures:

| Domain / Goal Nature                                                              | Recommended Tactic                      | Secondary / Fallback                | Avoid                                           |
| :-------------------------------------------------------------------------------- | :-------------------------------------- | :---------------------------------- | :---------------------------------------------- |
| **Integer / Natural Linear Arithmetic** ($+$, $-$, $\le$, $<$, $\cdot$ by const)  | `omega` (Lean 4.7+ Core)                | `decide`                            | Manual induction on `n`                         |
| **Real / Rational Linear Arithmetic** ($+$, $-$, $\le$, $<$, linear combinations) | `linarith`                              | `nlinarith`                         | `omega` (cannot handle $\mathbb{R}/\mathbb{Q}$) |
| **Nonlinear Real Arithmetic** ($x^2 \ge 0$, squares, products)                    | `nlinarith`, `positivity`               | `polyrith`                          | Naked `linarith`                                |
| **Pure Algebraic Equalities** (CommRing, Field)                                   | `ring`                                  | `field_simp; ring`                  | `simp`                                          |
| **Fraction Clearing & Division**                                                  | `field_simp`                            | `ring`                              | Manual `mul_inv_cancel₀`                        |
| **Congruence in Inequalities** ($f(a) \le f(b)$, sums, integrals)                 | `gcongr`                                | `rel [...]`                         | Manual `Finset.sum_le_sum`                      |
| **Strict Positivity / Nonnegativity** ($0 < x$, $0 \le \mu(s)$)                   | `positivity`                            | `norm_num`                          | Manual case analysis                            |
| **Pure Continuity Proofs**                                                        | `continuity`, `fun_prop`                | `continuous_def`                    | Manual $\varepsilon$-$\delta$                   |
| **Borel / Space Measurability**                                                   | `measurability`                         | `fun_prop (disch := measurability)` | Manual `measurable_pi_apply` chains             |
| **Angle Arithmetic** ($\mathbb{R}/\mathbb{Z}$ quotient)                           | `linarith` on `Real.Angle`              | `ring`                              | Manual modulus unwrapping                       |
| **Bit-Vector & Boolean Arithmetic** (`BitVec`, `Bool`, bitwise ops)               | `bv_decide` (Lean 4.12+ Core)           | `decide`                            | Manual bitwise induction                        |
| **Mixed Cross-Domain Constraints** (Equalities + inequalities + cases)            | `grind` / `grind?` (Lean 4.16+ / 4.20+) | `aesop`                             | Unbounded `simp`                                |

> [!NOTE]
> `grind` is designed for finite case-splitting, congruence closure, and mixed elementary constraints. In advanced Mathlib structures (measure theory, manifolds, topology, etc.), dedicated decision procedures (`omega`, `linarith`, `ring`, `gcongr`) and domain lemmas remain the primary tools due to lack of E-matching annotations.

---

## 2. Measure Theory & Probability Patterns

### 2.1. Proving Integrability: The Bounded-Measurable-Finite Rule

**Golden Rule:** `bounded + measurable + finite measure = integrable`.
Use `Integrable.of_bound` combined with `ae_of_all` to avoid expanding definitions:

```lean
import Mathlib.MeasureTheory.Integral.IntegrableOn

open MeasureTheory

lemma integrable_of_bounded_measurable
    {X : Type*} [MeasurableSpace X] {μ : Measure X} [IsFiniteMeasure μ]
    {f : X → ℝ} (h_meas : Measurable f) (h_bound : ∃ C, ∀ x, ‖f x‖ ≤ C) :
    Integrable f μ := by
  obtain ⟨C, hC⟩ := h_bound
  exact Integrable.of_bound h_meas.aestronglyMeasurable C (ae_of_all _ hC)
```

- **Indicator Functions**: If $f$ is integrable, its restriction to a measurable set $A$ is integrable via `hf.indicator hA`.
- **Almost Everywhere Bound**: If the bound holds almost everywhere (`∀ᵐ x ∂μ, ‖f x‖ ≤ C`), use `AEMeasurable` instead of `Measurable`.

### 2.2. Almost Everywhere (`ae`) Reasoning

1. **Lifting Universal to AE**: Use `ae_of_all` to satisfy an almost-everywhere hypothesis from an unconditional property:
   ```lean
   have h_all : ∀ x, 0 ≤ f x := fun x ↦ ...
   have h_ae : ∀ᵐ x ∂μ, 0 ≤ f x := ae_of_all μ h_all
   ```
2. **Combining Multiple AE Hypotheses**: Use `filter_upwards` with hypothesis list:
   ```lean
   -- Given h1 : ∀ᵐ x ∂μ, f x ≤ g x and h2 : ∀ᵐ x ∂μ, g x ≤ h x
   filter_upwards [h1, h2] with x h1x h2x
   exact le_trans h1x h2x
   ```
3. **AE Equality Substitution**: Use `.congr` and `.trans`:
   ```lean
   -- Transitivity: f =ᵐ[μ] g → g =ᵐ[μ] h → f =ᵐ[μ] h
   have h_trans := h1.trans h2
   -- Integrability transfer: Integrable f μ → f =ᵐ[μ] g → Integrable g μ
   have h_int_g := hf.congr h_eq
   ```

### 2.3. Automating Measurability Proofs

Avoid manual induction over $\sigma$-algebras or coordinate projections:

- **Automatic discharge**: Call `measurability`.
- **Registering helper lemmas**: Tag project-local helper lemmas with `@[measurability]` (or `@[measurability, fun_prop]`) so `measurability` and `fun_prop` can find them:
  ```lean
  @[measurability]
  lemma measurable_myOp {α β : Type*} [MeasurableSpace α] [MeasurableSpace β]
      (f : α → β) (hf : Measurable f) : Measurable (fun x ↦ ...) := by
    measurability
  ```
- **Function composition**: Use `fun_prop (disch := measurability)`.

### 2.4. Uniqueness of Conditional Expectation

To prove $\mu[f \mid m] = g$ almost everywhere, invoke `ae_eq_condExp_of_forall_setIntegral_eq`:

1. Prove $g$ is $m$-measurable (`Measurable[m] g`).
2. Prove $g$ is integrable (`Integrable g μ`).
3. Prove that for every $m$-measurable set $s$, $\int_s g \, \partial\mu = \int_s f \, \partial\mu$.

---

## 3. Analysis & Topology Patterns

### 3.1. Continuity: Automated vs. Definitional

- **Structural Compositions**: Call `continuity` or `fun_prop`.
- **Topological Preimages**: If proving from open sets, rewrite with `continuous_def`:
  ```lean
  lemma continuous_from_preimages {X Y : Type*} [TopologicalSpace X] [TopologicalSpace Y]
      {f : X → Y} (h : ∀ U, IsOpen U → IsOpen (f ⁻¹' U)) : Continuous f := by
    rw [continuous_def]
    exact h
  ```

### 3.2. Compactness and Extreme Values

To extract extrema on compact sets:

- Use `IsCompact.exists_isMinOn` or `IsCompact.exists_isMaxOn` given `hK : IsCompact K`, `hne : K.Nonempty`, and continuity:
  ```lean
  example {K : Set ℝ} (hK : IsCompact K) (hne : K.Nonempty) (f : ℝ → ℝ) (hf : Continuous f) :
      ∃ x ∈ K, ∀ y ∈ K, f x ≤ f y :=
    IsCompact.exists_isMinOn hK hne hf
  ```

### 3.3. Limits via Filters

Mathlib frames limits in terms of filters (`Tendsto f l₁ l₂`).

- For sequences indexed by $\mathbb{N}$: `Tendsto u atTop (𝓝 L)`
- For metric $\varepsilon$-$\delta$ unwrapping: Rewrite with `Metric.tendsto_atTop`:
  ```lean
  lemma limit_metric_def {u : ℕ → ℝ} {L : ℝ} :
      Tendsto u atTop (𝓝 L) ↔ ∀ ε > 0, ∀ᶠ n in atTop, ‖u n - L‖ < ε := by
    rw [Metric.tendsto_atTop]
  ```

---

## 4. Geometry & Affine Spaces

### 4.1. Betweenness via Line Map Parameters

Rather than writing 50+ lines decomposing segments manually:

- Use `Sbtw.sbtw_lineMap_iff` to prove strict betweenness:
  `Sbtw ℝ A (AffineMap.lineMap A B s) B ↔ A ≠ B ∧ s ∈ Set.Ioo 0 1`
- Extract collinear angles directly: `Sbtw.angle₁₂₃_eq_pi` gives $\angle A H B = \pi$.

### 4.2. Converting Segment Membership to Betweenness

- Use `mem_segment_iff_wbtw` to convert $x \in \text{segment } \mathbb{R} \, A \, B$ to weak betweenness `Wbtw ℝ A x B` in a single step.

### 4.3. Triangle Angle Sums and Angle Arithmetic

- `angle_add_angle_add_angle_eq_pi` gives the sum of angles of a triangle at a given vertex.
- `Real.Angle` is defined as a quotient $\mathbb{R} / (2\pi\mathbb{Z})$. Do not unwrap modular representatives manually; use `linarith` and `ring` directly on `Real.Angle` equations.

---

## 5. Algebra & Number Theory Patterns

### 5.1. Linear and Ring Equivalence Chains

- Use `ring` for polynomial identities ($a^2 - b^2 = (a - b)(a + b)$).
- Use `field_simp` before `ring` when clearing denominators:
  ```lean
  example (a b : ℝ) (ha : a ≠ 0) (hb : b ≠ 0) : (1 / a) + (1 / b) = (a + b) / (a * b) := by
    field_simp
    ring
  ```

### 5.2. Inequality Congruence with `gcongr`

When proving inequalities over composite terms (like sums, integrals, products), `gcongr` automatically matches the monotone structure and generates subgoals for the variable components:

```lean
example (s : Finset ℕ) (f g : ℕ → ℝ) (h : ∀ i ∈ s, f i ≤ g i) :
    ∑ i ∈ s, f i ≤ ∑ i ∈ s, g i := by
  gcongr with i hi
  exact h i hi
```

### 5.3. Handling Divisibility and Parity in Number Theory

- **Parity splitting**: Split via `rcases Nat.even_or_odd n with ⟨k, rfl⟩ | ⟨k, rfl⟩` rather than manual modulus cases.
- **Divisibility proofs**: Use `use` or `⟨k, rfl⟩` for existential witnesses, and simplify divisibility relations with `omega`.
