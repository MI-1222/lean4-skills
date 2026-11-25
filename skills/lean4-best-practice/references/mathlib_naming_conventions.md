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

---

## 5. One Root Namespace and One Module Root per Project

The naming formula tells you where Mathlib keeps a lemma. A project built on Mathlib needs a second guarantee: a name should show at a glance that the declaration belongs to the project, and a single name component should select all of the project's declarations. Put every declaration under one root namespace, and every module under one module root with the same name, usually the package name.

```lean
-- File MyProject/Arithmetic/Quarter.lean, module MyProject.Arithmetic.Quarter
namespace MyProject

/-- Dividing a natural number by four does not increase it. -/
theorem Nat.quarter_le (n : ℕ) : n / 4 ≤ n := Nat.div_le_self n 4

end MyProject

-- Dot notation finds `MyProject.Nat.quarter_le` once the namespace is open.
open MyProject in
example (m : ℕ) : m / 4 ≤ m := m.quarter_le
```

The following behavior was checked on Lean v4.33.1 and v4.35.0:

- **One entry covers the project.** The library suggestion deny list `nameDenyListExt` hides every declaration whose name contains the entry as a component (see the `lean4-mathlib-search` skill), so `"MyProject"` hides the whole project from `+suggestions`. A prefix argument to an audit command, such as `#unused_hypotheses MyProject`, or a search for `MyProject.` also covers everything. Generic roots cannot be denied this way: Mathlib also uses `Rep` and `Rel`, so denying those would hide Mathlib's own lemmas.
- **Mathlib may add the same name later.** A project theorem `Nat.quarter_le`, declared in Mathlib's `Nat` namespace, builds today. If a later Mathlib adds its own `Nat.quarter_le`, the project file fails with `` `Nat.quarter_le` has already been declared ``. If the project file does not import the Mathlib module that declares it, the file still builds, but every module that imports both fails with `import ... failed, environment already contains 'Nat.quarter_le' from ...`, unless the two declarations are identical. `MyProject.Nat.quarter_le` cannot collide this way.
- **Generic module roots collide across packages.** If the project and a dependency both provide a module `Lemmata.Basic`, importing it fails with ``could not disambiguate the module `Lemmata.Basic`; multiple packages provide distinct definitions``. A root named after the package avoids this.
- **Dot notation still works.** Generalized field notation also searches opened namespaces. Inside `namespace MyProject` alone it does not (`` Invalid field `quarter_le`: The environment does not contain `Nat.quarter_le` ``), so add `open MyProject` after `namespace MyProject` in files that use such lemmas with dot notation.
- **A bare name can switch meaning.** Under `open MyProject`, a bare `Nat.quarter_le` means Mathlib's `Nat.quarter_le` if one exists, and `MyProject.Nat.quarter_le` otherwise. Inside `namespace MyProject`, the project's declaration wins. When Mathlib may gain the same name, write the full name `MyProject.Nat.quarter_le`.

In the formalization of about 175,000 modules described in [statement_first_decomposition.md](statement_first_decomposition.md), declarations used 5,957 different root namespaces. In 89,828 of the 116,365 files that open a namespace (77%), the root of the first namespace differed from the top-level directory of the file. For example, 70,561 files under `Development/` declared in `GlobalTheory`. The project also declared directly in Mathlib's `Complex`, `Matrix`, `Real` and `Ideal` namespaces, and placed its modules under about a dozen top-level roots such as `Lemmata`, `Development` and `Formalism`. Its suggestion deny list named five roots, so the declarations under roots such as `Good` (91 files), `Rel` (52 files) and `Rep` (36 files) were not excluded.

Rules:

- **Choose the root before the first file**, and make it match the package and `lean_lib` name. Renaming tens of thousands of declarations later is a large refactor.
- **Open the root in every file** with `namespace MyProject ... end MyProject`. Use sub-namespaces such as `MyProject.GlobalTheory` for areas, not new roots.
- **Do not declare in Mathlib's namespaces.** Write `MyProject.Complex.foo` instead of `Complex.foo`, and `open MyProject` where dot notation is wanted. The exception is code being prepared for Mathlib, which takes Mathlib's name when it moves there.
- **Keep the deny list to one entry**: `nameDenyListExt.addEntry env "MyProject"`. If the list needs one entry per area, the project has more than one root.
