# Junk Values and Partial Functions in Mathlib

This guide explains Mathlib's total function design, how undefined mathematical expressions are assigned default "junk values", and how to properly supply necessary side conditions when applying lemmas.

---

## 1. Why Mathlib Uses Total Functions

In Lean 4's Type Theory, every function $f : A \to B$ must be **total**: it must return a valid term of type $B$ for every element in the domain $A$.

In classical mathematics, many familiar operations are partial:

- Division $x / y$ is undefined when $y = 0$.
- Differentiation $\frac{df}{dx}$ is undefined when $f$ is not differentiable at $x$.
- Infinite summation $\sum_{n=0}^{\infty} a_n$ is undefined when the series diverges.
- Supremum $\sup S$ is undefined when $S = \emptyset$ or when $S$ is unbounded above.

Mathlib makes these functions total by assigning a default **junk value** (typically `0`) outside their natural mathematical domains, avoiding the syntactic overhead of dependent domain proofs on every function application.

---

## 2. Common Operations and Their Junk Values

| Mathematical Concept           | Mathlib Definition         | Domain of Validity                          | Value Outside Domain (Junk Value)    |
| :----------------------------- | :------------------------- | :------------------------------------------ | :----------------------------------- |
| **Real / Field Division**      | `x / y`                    | $y \neq 0$                                  | $x / 0 = 0$                          |
| **Natural Subtraction**        | `a - b` (`a, b : ℕ`)       | $b \le a$                                   | $a - b = 0$ whenever $a < b$         |
| **Single-variable Derivative** | `deriv f x`                | `DifferentiableAt ℝ f x`                    | `0` (or $0$-linear map for `fderiv`) |
| **Fréchet Derivative**         | `fderiv 𝕜 f x`             | `DifferentiableAt 𝕜 f x`                    | `0` (the zero continuous linear map) |
| **Infinite Series Sum**        | `tsum f` ($\sum' x, f(x)$) | `Summable f`                                | `0`                                  |
| **Real Supremum**              | `sSup s`                   | $s \neq \emptyset \land \text{BddAbove } s$ | `0`                                  |

---

## 3. The Trap of Junk Values for Proving Agents

Junk values can mislead language models in two distinct ways:

### Trap 1: Assuming a False Identity Outside the Domain

Because $x / 0 = 0$ holds definitionally, an agent might inadvertently try to prove $x / 0 = y / 0$ as $0 = 0$, which is mathematically nonsensical and usually represents an incorrect proof branch.

### Trap 2: Missing Hypotheses When Applying Theorems

Theorems that describe expected algebraic properties (such as $(x \cdot y) / y = x$ or $\frac{d}{dx}(f + g) = f' + g'$) do **not** hold unconditionally in Mathlib. They require hypotheses ensuring that the operation stays within its valid mathematical domain.

If you attempt to rewrite using `mul_div_cancel` without having `y ≠ 0` in your context, the rewrite or `apply` will fail.

---

## 4. Subscript-Zero (`₀`) Conventions for Groups/Fields with Zero

Mathlib distinguishes between operations on groups (where every element has an inverse) and division rings or fields (where zero has no inverse) using the subscript `₀` (U+2080):

| Lemma without `₀` (Pure Group) | Lemma with `₀` (Group / Field with Zero) | Required Hypothesis |
| :----------------------------- | :--------------------------------------- | :------------------ |
| `mul_inv_cancel x`             | `mul_inv_cancel₀ (h : x ≠ 0)`            | `x ≠ 0`             |
| `div_self x`                   | `div_self (h : x ≠ 0)`                   | `x ≠ 0`             |
| `mul_div_cancel_right x y`     | `mul_div_cancel_right₀ x (h : y ≠ 0)`    | `y ≠ 0`             |

Whenever dividing or taking inverses in `ℝ`, `ℂ`, or a general `Field`, always check for the `₀` suffix and ensure your local context contains the non-zero proof.

---

## 5. Best Practices: Establishing Side Conditions Early

Before applying differentiation, summation, or algebraic cancellation lemmas, extract or prove the required domain conditions as distinct `have` statements:

### Example 1: Division Cancellation

```lean
import Mathlib.Basic.Real.Basic

theorem cancel_div_example (x y : ℝ) (hy : y ≠ 0) :
    (x * y) / y = x := by
  -- Requires `hy : y ≠ 0` for `mul_div_cancel_right₀`
  exact mul_div_cancel_right₀ x hy
```

### Example 2: Derivative of a Sum

```lean
import Mathlib.Analysis.Calculus.Deriv.Basic

variable (f g : ℝ → ℝ) (x : ℝ)

theorem deriv_add_example (hf : DifferentiableAt ℝ f x) (hg : DifferentiableAt ℝ g x) :
    deriv (fun t => f t + g t) x = deriv f x + deriv g x := by
  -- Without `hf` and `hg`, `deriv (f + g)` defaults to `0`, making this identity invalid
  exact deriv_add hf hg
```

### Example 3: Infinite Series Linearity

```lean
import Mathlib.Topology.Algebra.InfiniteSum.Basic

variable {α : Type*} (f g : α → ℝ)

theorem tsum_add_example (hf : Summable f) (hg : Summable g) :
    (∑' i, (f i + g i)) = (∑' i, f i) + (∑' i, g i) := by
  -- If either series diverges, tsum defaults to 0, which would break equality
  exact hf.tsum_add hg -- or: exact Summable.tsum_add hf hg
```
