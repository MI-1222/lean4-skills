# Mathlib Naming Conventions & Reverse Lookup

Mathlib follows strict, predictable naming conventions. Once you understand the underlying grammar, you can deduce the exact name of an existing lemma >80% of the time without running search queries.

---

## 1. Case Conventions by Declaration Type

| Construct                                                  | Case Convention  | Examples                                      |
| :--------------------------------------------------------- | :--------------- | :-------------------------------------------- |
| **Theorems, Lemmas, Proofs** (anything of type `Prop`)     | `snake_case`     | `Nat.add_comm`, `Continuous.comp`, `le_of_lt` |
| **Types, Classes, Structures, Inductives**                 | `UpperCamelCase` | `Nat`, `Group`, `MetricSpace`, `Continuous`   |
| **Functions, Definitions, Data Constructors** (non-`Prop`) | `lowerCamelCase` | `List.map`, `Function.comp`, `Set.univ`       |

_Note on Acronyms_: In lowerCamelCase or snake_case, multi-letter acronyms use lowercase (e.g. `iidProjectiveFamily`, `conditionallyIID_of_exchangeable`).

---

## 2. The Theorem Naming Formula

Most Mathlib theorem names follow a structured formula:

```text
[Namespace].[Subject]_[property/relation]_[qualifier]
```

Or for relational statements:

```text
[Operation]_[property]   or   [Target]_[of_Condition]
```

### Core Components

#### A. Head Symbol Rule

The prefix is typically the primary type or constant involved:

- Operations on `Nat`: `Nat.add_comm`, `Nat.mul_assoc`, `Nat.succ_le_succ`
- Operations on `List`: `List.map_append`, `List.length_concat`
- Properties of `Continuous`: `Continuous.comp`, `Continuous.add`

#### B. Algebraic Properties

Standard suffixes denote algebraic laws:

- `_comm`: Commutativity ($a * b = b * a$)
- `_assoc`: Associativity ($(a * b) * c = a * (b * c)$)
- `_left_distrib` / `_right_distrib`: Distributivity ($a * (b + c) = a * b + a * c$)
- `_zero` / `_one`: Operation with identity element (`add_zero`, `mul_one`)
- `_inv` / `_neg`: Operation with inverse/negation (`mul_inv_cancel`, `add_neg_cancel`)
- `_inj`: Injectivity ($f(a) = f(b) \iff a = b$)

#### C. Implications and Equivalences

- `_of_`: Indicates deduction from a condition ($A \to B$ is named `B_of_A`).
  - _Example_: `le_of_lt` proves $a \le b$ from $a < b$.
  - _Example_: `Continuous.comp_of_continuous`
- `_iff_`: Indicates bidirectional equivalence ($A \iff B$ is named `A_iff_B`).
  - _Example_: `Nat.succ_le_succ_iff`: $n + 1 \le m + 1 \iff n \le m$.
- `_left` / `_right`: Indicates which component of a conjunction, disjunction, or binary relation is selected.
  - _Example_: `And.left`, `mul_pos_of_pos_of_pos`

#### D. Inequalities: Prefer `le` and `lt`

Mathlib strictly standardizes on less-than (`<`) and less-than-or-equal (`≤`):

- Use `le` and `lt`, **never** `ge` or `gt` in primary lemma names.
  - _Example_: `add_le_add` (not `add_ge_add`).
  - _Example_: `lt_of_le_of_lt` proves $a < c$ given $a \le b$ and $b < c$.

---

## 3. Reverse Lookup Algorithm

When you need a lemma for a specific mathematical step, construct the name candidate using this systematic process:

```text
Target statement: a + b = b + a  (for a, b : Nat)
1. Identify primary type/namespace: Nat
2. Identify operation: add
3. Identify property: comm
Candidate Name: Nat.add_comm
```

```text
Target statement: x < y → x ≤ y
1. Target relation: le
2. Premise relation: lt
3. Connector: _of_
Candidate Name: le_of_lt
```

```text
Target statement: Continuous (f ∘ g) given Continuous f and Continuous g
1. Subject: Continuous
2. Operation: comp
Candidate Name: Continuous.comp
```

```text
Target statement: length (l1 ++ l2) = length l1 + length l2
1. Subject: List
2. Outer function: length
3. Inner operation: append
Candidate Name: List.length_append
```

---

## 4. Leveraging Dot Notation for Fluent Proving

Lean 4 supports dot notation (generalized field access). If `h : Continuous f` and `hg : Continuous g`, you do not need to write:

```lean
exact Continuous.comp h hg
```

Instead, invoke the lemma directly as a method on `h`:

```lean
exact h.comp hg
```

### Common Dot Notation Patterns

- Equalities: `h.symm` (symmetry), `h.trans h2` (transitivity)
- Inequalities: `h.le` ($< \to \le$), `h.trans h2`
- Conjunctions: `h.1` / `h.left`, `h.2` / `h.right`
- Implications: `h.mp` ($P \to Q$ from $P \iff Q$), `h.mpr` ($Q \to P$)
- Negations: `h.elim`
