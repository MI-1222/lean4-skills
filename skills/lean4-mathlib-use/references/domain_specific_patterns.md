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

- **Automatic discharge**: Call `measurability`. It runs `aesop` with the `Measurable` rule set. For function goals (`Measurable`, `AEMeasurable`, `StronglyMeasurable`, `AEStronglyMeasurable`), it relies on `fun_prop`.
- **Function composition**: Use `fun_prop (disch := measurability)`.
- **Registering helper lemmas**: The attribute depends on what the lemma states.

| The helper lemma is about        | Tag it with        | What the other attribute does                                                                 |
| :------------------------------- | :----------------- | :-------------------------------------------------------------------------------------------- |
| A function (`Measurable f`, ...) | `@[fun_prop]`      | `@[measurability]` also registers it with `fun_prop`, but warns ``Use `@[fun_prop]` instead`` |
| A set (`MeasurableSet s`)        | `@[measurability]` | `@[fun_prop]` is an error: ``unrecognized function property `MeasurableSet s` ``              |

```lean
import Mathlib.MeasureTheory.Constructions.BorelSpace.Real
import Mathlib.Tactic.FunProp
import Mathlib.Tactic.Measurability

namespace Demo

noncomputable def step (x : ℝ) : ℝ := if 0 ≤ x then 1 else 0

@[fun_prop]
theorem measurable_step : Measurable step :=
  Measurable.ite measurableSet_Ici measurable_const measurable_const

def posSet : Set ℝ := {x | 0 < x}

@[measurability]
theorem measurableSet_posSet : MeasurableSet posSet := measurableSet_Ioi

example (f : ℝ → ℝ) (hf : Measurable f) : Measurable (fun x ↦ step (f x) + 1) := by
  fun_prop

example : MeasurableSet posSetᶜ := by measurability

end Demo
```

Checked on Mathlib `v4.33.1` and `v4.35.0`.

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

---

## 6. Automating Facts About Project Definitions

When the same side goal about a project definition (positivity, continuity, measurability, a project predicate) is proved by hand in many places, register the fact once with a tactic that already searches for that kind of goal. Callers then name the tactic instead of the lemma, and the same registration serves compound expressions.

### 6.1. Choose the Mechanism

| Repeated work                                                                                      | Mechanism                                                 | What you write       |
| :------------------------------------------------------------------------------------------------- | :-------------------------------------------------------- | :------------------- |
| `Continuous`, `Differentiable`, `Measurable` and other function properties of a project definition | `@[fun_prop]` (§6.2)                                      | A lemma              |
| A project predicate on functions                                                                   | `@[fun_prop]` on the predicate and on its lemmas (§6.2)   | A definition, lemmas |
| `MeasurableSet` of a project set                                                                   | `@[measurability]` (§2.3)                                 | A lemma              |
| `0 < e`, `0 ≤ e` or `e ≠ 0` for a project invariant                                                | `@[positivity]` extension (§6.3)                          | A short metaprogram  |
| A goal only a custom procedure can close                                                           | `elab`, comparing types before it assigns the goal (§6.4) | A metaprogram        |
| A fixed sequence of tactics                                                                        | `macro` (§6.5)                                            | A syntax expansion   |

A few uses do not justify a new mechanism: `positivity [φ.ord_pos]` or `have := φ.ord_pos` supplies the fact in place.

### 6.2. `fun_prop`: Function Properties

```lean
import Mathlib.MeasureTheory.Constructions.BorelSpace.Real
import Mathlib.Tactic.FunProp
import Mathlib.Tactic.Measurability

namespace Demo

noncomputable def clip (x : ℝ) : ℝ := max x 0

@[fun_prop]
theorem continuous_clip : Continuous clip := by
  unfold clip
  fun_prop

-- one lemma covers compositions, and `Measurable` follows from `Continuous`
example : Continuous (fun x : ℝ ↦ clip (x ^ 2) + clip x) := by fun_prop
example : Measurable (fun x : ℝ ↦ clip (x ^ 2)) := by fun_prop
example : Measurable (fun x : ℝ ↦ clip (x ^ 2)) := by measurability

/-- A project predicate: `f` does not increase distances. -/
@[fun_prop]
def IsShort (f : ℝ → ℝ) : Prop := ∀ x y, |f x - f y| ≤ |x - y|

@[fun_prop]
theorem isShort_id : IsShort (fun x ↦ x) := fun _ _ ↦ le_rfl

@[fun_prop]
theorem isShort_comp {f g : ℝ → ℝ} (hf : IsShort f) (hg : IsShort g) :
    IsShort (fun x ↦ f (g x)) :=
  fun x y ↦ (hf _ _).trans (hg x y)

@[fun_prop]
theorem isShort_neg : IsShort (fun x : ℝ ↦ -x) := fun x y ↦ by
  rw [neg_sub_neg, abs_sub_comm]

example (f : ℝ → ℝ) (hf : IsShort f) : IsShort (fun x ↦ -(f (-x))) := by fun_prop

end Demo
```

- Without `continuous_clip`, `fun_prop` fails and reports ``No theorems found for `Demo.clip` ``, which names the function that still needs a lemma.
- For a project predicate, tag the definition, then a lemma for `fun x ↦ x`, one for composition and one for each operation.
- Tagging a lemma whose conclusion is not a function property is an error (`unrecognized function property`).

### 6.3. `positivity` Extensions

```lean
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.GCongr
import Mathlib.Tactic.FieldSimp
import Mathlib.Basic.Real.Basic -- `Mathlib.Data.Real.Basic` on Mathlib v4.33.1 and older

namespace Demo

structure Frame where
  ord : ℕ
  ord_ne_zero : ord ≠ 0

theorem Frame.ord_pos (φ : Frame) : 0 < φ.ord := Nat.pos_of_ne_zero φ.ord_ne_zero

end Demo

namespace Mathlib.Meta.Positivity

open Lean Meta Qq

/-- The `positivity` extension for `Demo.Frame.ord`. -/
@[positivity Demo.Frame.ord _]
def evalDemoFrameOrd : PositivityExt where eval {u α} _zα pα? e :=
  match pα? with
  | none => throwError "no order"
  | some _ => do
    match u, α, e with
    | 0, ~q(ℕ), ~q(Demo.Frame.ord $φ) =>
      assertInstancesCommute
      return .positive q(Demo.Frame.ord_pos $φ)
    | _, _, _ => throwError "not Demo.Frame.ord"

end Mathlib.Meta.Positivity

section
variable (φ : Demo.Frame) (x y : ℝ)

-- each of these fails without the extension
example : (0 : ℝ) < φ.ord / 2 := by positivity
example : (φ.ord : ℝ) ≠ 0 := by positivity
example (h : x < y) : x * φ.ord < y * φ.ord := by gcongr
example : x / φ.ord * φ.ord = x := by field_simp

end
```

The extension states one fact about `ord`. `positivity` combines it with casts and arithmetic, and the last two examples show that side goals of `gcongr` and `field_simp` use it too.

- **Match `pα?` outside `do`**: As above, make `match pα?` the body and start `do` inside the branch. With `match pα?` inside a `do` block, the returned `Strictness` value does not type check.
- **Return proofs with `q(...)`**: `Qq` checks the proposition when the extension compiles, so returning `q(Nat.zero_le $n)` as `.positive` is an error there. `.unsafeMk` removes this check: `positivity` then reports success for a wrong proof, and only the kernel rejects the declaration.
- **Check instances**: `assertInstancesCommute` verifies that the instances agree when the extension runs, while `assumeInstancesCommute` assumes it.
- **Reducible wrappers only**: An `abbrev` for `φ.ord` is covered, but a `def` for it is not and needs its own extension or lemma.
- **Import it**: The extension applies only in modules that import it. Put it in the module that defines the invariant, or in one that every user imports.
- **`module` files**: Use `public meta import Mathlib.Tactic.Positivity.Core` and declare the extension with `meta def`. A plain `def` is rejected (``must be marked as `meta` ``).
- **Versions**: The signature above compiles on Mathlib `v4.33.1` and `v4.35.0`. If it does not type check on another version, compare it with `PositivityExt` in `Mathlib/Tactic/Positivity/Core.lean`.

### 6.4. Custom Tactics: Compare Types Before Assigning the Goal

Calling `MVarId.assign` is not the problem: `positivity` itself closes its goal with `goal.assign p`, where `Qq` has already fixed the type of `p`. `MVarId.assign` stores a value without checking its type (its docstring says so), so the code that runs before it has to guarantee the type.

| How the tactic closes the goal `g`                                                                     | Rejects a wrong term itself?                                                                                          |
| :----------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------- |
| `closeMainGoalUsing` with `elabTermEnsuringType` (as `exact` does)                                     | Yes                                                                                                                   |
| `isDefEq (← inferType pf) (← g.getType)`, then `g.assign pf`, with `pf` from `mkAppM`, `mkEqRefl`, ... | Yes                                                                                                                   |
| The same, with `pf` assembled by `mkApp` / `mkConst`                                                   | Only with `Meta.check pf` first, because `inferType` does not check arguments                                         |
| `g.assign v` alone                                                                                     | No                                                                                                                    |
| `g.checkedAssign v` alone                                                                              | No (it runs an occurs check, not a type check)                                                                        |
| `closeMainGoal tacName v` alone                                                                        | No (it calls `checkedAssign`)                                                                                         |
| `closeMainGoalUsing` with a callback such as `elabTerm e none`                                         | No: the callback ignores the goal type                                                                                |
| `isDefEq (.mvar g) v`                                                                                  | Do not use: even for a correct `v`, the main goal stays unassigned (`false` for a data goal, `true` for a proof goal) |

```lean
import Lean

open Lean Elab Tactic Meta

namespace Demo

-- ❌ assigns the goal without comparing types
elab "kexact " e:term : tactic => withMainContext do
  let g ← getMainGoal
  let v ← Term.elabTermAndSynthesize e none
  g.assign (← instantiateMVars v)

-- ✅ takes a term: elaborate it against the goal type
elab "my_exact " e:term : tactic =>
  closeMainGoalUsing `my_exact fun type _ => elabTermEnsuringType e type

-- ✅ builds a proof: compare the types, then assign
elab "close_refl" : tactic => withMainContext do
  let g ← getMainGoal
  let some (_, lhs, _) := (← g.getType).eq? | throwTacticEx `close_refl g "not an equality"
  let pf ← mkEqRefl lhs
  unless ← isDefEq (← inferType pf) (← g.getType) do
    throwTacticEx `close_refl g "the two sides are not definitionally equal"
  g.assign pf

-- negative test: the tactic itself must reject a wrong term
example (p q : Prop) (hp : p) (hq : q) : q := by
  fail_if_success my_exact hp
  my_exact hq

example : 2 + 2 = 4 := by close_refl

-- ❌ `first` takes the wrong branch, and the kernel then rejects `pick`
theorem pick (p q : Prop) (hp : p) (hq : q) : q := by
  first
    | kexact hp
    | kexact hq

end Demo
```

What an unchecked tactic such as `kexact` costs:

- **Late errors**: The kernel still checks every declaration, so the wrong term is not accepted as a proof. The error is a `(kernel)` type mismatch, reported for the declaration instead of at the tactic call.
- **No backtracking**: `first` and `try` see success, so a later branch that would work is never tried.
- **Silent acceptance**: A command that never reaches the kernel reports nothing: `#check (by kexact True.intro : False)` prints `True.intro : True`.
- **No expected type**: Terms that need it, such as `⟨trivial, trivial⟩`, fail to elaborate.

Give every custom tactic a negative test with `fail_if_success`, as above. A tactic like `kexact` is sometimes written to leave an expensive definitional equality check to the kernel; fix the type design instead (`lean4-proof-repair` → `timeout_and_heartbeats.md` §2.6). To audit existing tactics, see `lean4-cli` → `soundness_and_axiom_audit.md` §4 and §5. `scan_risky_constructs.py` reports each `.assign`, `.checkedAssign`, `closeMainGoal` and `closeMainGoalUsing`, and the uses of custom syntax built on them. Checked code such as `my_exact` and `close_refl` is reported too, so read each hit.

### 6.5. Macros Are Checked Like Their Expansion

A `macro` produces syntax that is then elaborated like handwritten code, so it is exactly as safe as what it expands to. `local` and `scoped` limit where the name is visible, not what it checks.

```lean
import Lean

open Lean Elab Tactic Meta

namespace Demo

elab "kexact " e:term : tactic => withMainContext do
  let g ← getMainGoal
  let v ← Term.elabTermAndSynthesize e none
  g.assign (← instantiateMVars v)

-- ✅ expands to `exact`: a wrong term is rejected at the call
local macro "close_checked " e:term : tactic => `(tactic| exact $e)

-- ❌ expands to `kexact`: as unchecked as `kexact`, although the macro is `local`
local macro "close_unchecked " e:term : tactic => `(tactic| kexact $e)

example : True := by close_checked True.intro

example : True := by
  fail_if_success close_checked (1 : Nat)
  close_unchecked True.intro

end Demo
```

- A `local macro` ends with its section or file. If several files need the same macro, define it once in a shared module as a `scoped macro` instead of copying it.
- `macro_rules` can also change what existing syntax such as `decide` expands to. When the expansion contains a construct that `scan_risky_constructs.py` traces, the script reports those uses.

### 6.6. Checked and Unchecked Automation in One Code Base

A formalization of about 175,000 modules (Lean `v4.33.1`) contains both:

- An 18-line file registers the order of a structure with `positivity`. A file that imports it proves `0 < (φ.ord : ℝ) / 2` and `(φ.ord : ℝ) ≠ 0` by `positivity`; without that import, the same goals fail.
- Two custom tactics assign the goal without comparing types (§6.4), and `local macro`s in several files wrap one of them (§6.5). With either tactic, a wrong term passed the elaborator and only the kernel rejected it.
