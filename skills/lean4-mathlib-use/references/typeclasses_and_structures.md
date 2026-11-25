# Mathematical Structures and Typeclass Hierarchy in Mathlib

This guide explains how to interact with Mathlib's algebraic, topological, and order hierarchies, avoid common typeclass elaboration pitfalls, and explicitly guide instance synthesis.

---

## 1. Multiple Inheritance and "Invisible Dependencies"

Mathlib's abstract mathematics relies on Lean 4's typeclass system using structural extension (`extends`):

- Algebraic structures (e.g., `Semigroup` $\to$ `Monoid` $\to$ `Group` $\to$ `CommGroup` $\to$ `Ring` $\to$ `CommRing` $\to$ `Field`).
- Topological & geometric structures (e.g., `TopologicalSpace` $\to$ `UniformSpace` $\to$ `MetricSpace` $\to$ `NormedAddCommGroup`).

Research on Mathlib's internal dependency graphs reveals that **74.2% of all dependency edges are "invisible" (synthesized edges)**—generated implicitly by the elaborator through typeclass synthesis, operator resolution (`HAdd`, `HMul`), numeric literal conversion (`OfNat`), and coercions (`Coe`).

While this provides standard mathematical notation, it creates massive search spaces for typeclass resolution when clues are ambiguous, occasionally leading to `maximum synth pending depth reached` or `maxHeartbeats exceeded`.

---

## 2. Mandatory Discipline: Disable `autoImplicit`

In standard Lean 4, unquoted lowercase identifiers (e.g., `x`, `n`, `g`) in declarations are automatically generalized as implicit universal variables if `autoImplicit` is left on.

In mathematical formalization, this frequently introduces accidental free variables that break typeclass resolution or create subtly invalid lemma statements:

```lean
-- Set at the top of every Mathlib formalization file or section:
set_option autoImplicit false
```

With `autoImplicit false`, any undeclared variable produces an immediate compiler error, forcing explicit typing and preventing typeclass confusion.

---

## 3. Explicit Type Annotations to Pin Search Anchors

When expressions contain polymorphic constants, the elaborator must search multiple candidate instance paths simultaneously. Pinning expressions with explicit type annotations eliminates backtracking.

### Numeric Literals and Zero/One

- Writing `0` or `1` without context forces Lean to guess whether it is `Nat`, `Int`, `Real`, or a generic monoid identity.
- **Best Practice**: Use `(0 : ℝ)` or annotate binders `(x : ℝ)`.

### Coercions and Embeddings

- When embedding natural numbers or integers into real or complex numbers, Lean uses coercion operators ($\uparrow$).
- If the target type is ambiguous, write `((n : ℝ))` or `(n : ℝ)` explicitly to prevent failed instance synthesis.

```lean
-- Ambiguous:
example (n : ℕ) : (n : ℝ) ≥ 0 := by ...

-- Distinct and firmly anchored:
example (n : ℕ) : 0 ≤ (n : ℝ) := by
  exact Nat.cast_nonneg n
```

---

## 4. Local Instance Injection: Defeq Transparency (`have` vs `let` / `letI`)

When working with conditional structures, sub-structures, or localized hypotheses, the global typeclass synthesizer might fail to automatically discover an instance that only holds conditionally in the local proof context.

### The Definitional Transparency Distinction

In Lean 4, local instance registration behaves fundamentally differently depending on whether the instance carries **computational data** (e.g. algebraic operations, metrics, topologies) or is a **proposition** (`Prop`-valued typeclass such as `Fact p`, `Decidable p`):

| Tactic / Pattern                                      | Transparency    | Primary Use Cases                                                                                     | Defeq Behavior                                                                                 |
| :---------------------------------------------------- | :-------------- | :---------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| `have : PropClass := pf`                              | **Opaque**      | `Prop` typeclasses (`Fact p`, `Decidable p`), or proof-internal finiteness (`Fintype s`)              | **Safe for Prop**: Proof irrelevance ensures opacity cannot cause defeq mismatches.            |
| `letI : DataClass := pf` (or `let : DataClass := pf`) | **Transparent** | Data typeclasses (`Group`, `Ring`, `Topology`, `MetricSpace`) when operators appear in goal/signature | **Preserves defeq**: Operators resolve to the exact definition, preventing instance pollution. |
| `haveI : Instance := pf`                              | _Legacy_        | Deprecated in modern Mathlib; flagged by linter.                                                      | Inlines value; avoid in new code.                                                              |

---

### Safe Pattern 1: Supplying a `Fact` Instance for Conditional Theorems

Many Mathlib theorems require hypotheses wrapped in the `Fact` typeclass (e.g., primality `[Fact (Nat.Prime p)]` or field characteristics):

```lean
import Mathlib.Data.Nat.Prime.Basic

-- A theorem requires [Fact (Nat.Prime p)] to invoke downstream field or prime properties:
theorem prime_has_property (p : ℕ) (hp : Nat.Prime p) :
    p > 1 := by
  -- Inject the Prop typeclass into the local instance cache via anonymous have:
  have : Fact (Nat.Prime p) := ⟨hp⟩
  -- Any lemma requiring [Fact (Nat.Prime p)] synthesizes cleanly:
  exact Nat.Prime.one_lt (Fact.out : Nat.Prime p)
```

Because `Fact` is in `Prop`, the opacity of `have` causes no definitional issues.

---

### Safe Pattern 2: Supplying Proof-Internal Finiteness (`Fintype`)

When invoking combinatorial lemmas within a proof where the goal signature does not conflict with the instance:

```lean
import Mathlib.Data.Fintype.Basic

theorem bounded_set_card {α : Type*} (s : Set α) (h_fin : s.Finite) :
    True := by
  -- Provide a local Fintype instance for the subtype without conflicting with ambient signature:
  have : Fintype s := h_fin.fintype
  trivial
```

---

### Anti-Pattern & Pitfall: Opaque `have` on Data Typeclasses (Self-Inflicted Instance Pollution)

> [!CAUTION]
> **Never inject data-carrying typeclasses (`Group`, `Ring`, `Inv`, `Mul`) using opaque `have` when the operators already appear in the theorem signature or goal.**

#### The Failure Mechanism:

```lean
-- BROKEN ANTI-PATTERN:
theorem subgroup_element_mul_inv {G : Type*} [Group G] (H : Subgroup G) (x : H) :
    x * x⁻¹ = 1 := by
  -- WRONG: have is opaque! It shadows the ambient instance and creates an un-unifiable `this`:
  have : Group H := Subgroup.toGroup H
  exact mul_inv_cancel x  -- FAILS: Type mismatch!
```

**Why this fails**:

1. **Redundant Injection**: Mathlib already registers a global instance for `Subgroup.toGroup H`. Re-declaring it locally is unnecessary.
2. **Defeq Breakage**: The theorem signature (`x * x⁻¹ = 1`) was elaborated against the ambient `Subgroup.toGroup H` instance. Running `have : Group H := ...` binds an **opaque** local constant `this`. When `mul_inv_cancel x` is invoked, it uses `this.toInv`, which cannot definitionally unify with the ambient `H.inv` in the goal.

#### Correct Approaches:

1. **Rely on Ambient Instances (Best)**: Do not inject instances locally if Mathlib's global instance synthesis already covers the type:

   ```lean
   theorem subgroup_element_mul_inv {G : Type*} [Group G] (H : Subgroup G) (x : H) :
       x * x⁻¹ = 1 := by
     exact mul_inv_cancel x  -- Synthesizes automatically via global instance
   ```

2. **Use Transparent `letI` or `let` when Defeq Preservation is Required**: If a local data instance must be provided dynamically, use transparent binding so that Lean can unfold its definition during unification:
   ```lean
   -- Use letI (or transparent let) when downstream tactics require definitional equality:
   letI : Group CustomType := customGroupConstruction
   ```

---

## 5. Avoiding Instance Resolution Loops

Instance synthesis loops typically occur when:

1. Two typeclasses define reciprocal conversion instances without a clear decrease in structure complexity.
2. A lemma expects a general algebraic structure, but a concrete type's bundled fields fail unification.

### Diagnostic Techniques

- Inspect instance synthesis paths:
  ```lean
  set_option trace.Meta.synthInstance true in
  #check ...
  ```
- If heartbeats expire during instance synthesis, verify that:
  - All type parameters have explicit class constraints (e.g., `[CommRing R]` rather than just `(R : Type*)`).
  - No conflicting duplicate instances exist in the active `open` namespaces.

---

## 6. Avoiding Instance Pollution (Sub-σ-algebras, Orders, Metrics)

### The Problem

When multiple instances of the same typeclass exist in the same scope (e.g., sub-σ-algebras `MeasurableSpace Ω`, multiple metrics `MetricSpace α`, or alternative orderings `Preorder β`), Lean's elaborator preferentially selects the **most recently bound local constant** rather than the ambient instance.

This leads to cryptic errors like:

```text
type mismatch
  synthesized: mSub, inferred: inst✝
```

or 500k+ heartbeat timeout explosions.

### Prevention & Recovery Patterns

#### Pattern 1: Name and Pin the Ambient Instance

Name the ambient instance in the declaration signature:

```lean
theorem my_theorem (Ω β : Type*) [m0 : MeasurableSpace Ω] [MeasurableSpace β]
    (Z : Ω → β) (hZ : Measurable Z) : ... := by
```

If the signature is fixed (e.g., from an upstream project or library specification), capture the ambient instance on the very first line before creating any local sub-structures:

```lean
  let m0 : MeasurableSpace Ω := ‹MeasurableSpace Ω›
```

_(The `‹…›` French quote syntax captures the currently active local instance)._

#### Pattern 2: Use Explicit `@` Application for Ambient Facts

When referencing lemmas that rely on the ambient structure, explicitly pass the pinned ambient instance:

```lean
  -- Explicitly anchor to ambient m0:
  have h_meas : @Measurable Ω β m0 _ Z := hZ
```

#### Pattern 3: Avoid Local Class-Typed Bindings When Possible

Instead of declaring `let mSub : MeasurableSpace Ω := ...` early in the proof (which immediately shadows the ambient instance), inline the expression or introduce it only after all ambient facts have been elaborated.

#### Pattern 4: Exclude Unwanted Section Variables via `omit` (Lean 4.11+)

When an ambient section declares a typeclass variable that a specific lemma or theorem does not require (which would otherwise pollute search or induce looping):

```lean
-- Exclude MeasurableSpace Ω for this specific lemma:
omit [MeasurableSpace Ω] in
theorem independent_lemma (n : ℕ) : n + 0 = n := by
  rfl
```

> [!WARNING]
> **Docstring Placement with `in`**:
> Command-level prefix modifiers with `in` (such as `omit [...] in`, `open ... in`, or `set_option ... in`) must appear **before** the docstring (`/-- ... -/`), NOT between the docstring and `theorem`/`def`:
>
> ```lean
> -- ⭕ CORRECT: omit placed before docstring
> omit [MeasurableSpace Ω] in
> /-- An independent lemma that does not require the ambient measure space. -/
> theorem independent_lemma (n : ℕ) : n + 0 = n := by
>   rfl
>
> -- ❌ INCORRECT: parser error "unexpected token 'omit'; expected 'lemma'"
> /-- An independent lemma ... -/
> omit [MeasurableSpace Ω] in
> theorem independent_lemma (n : ℕ) : n + 0 = n := by
>   rfl
> ```
>
> In Lean 4's grammar, `/-- ... -/` begins `declModifiers` which must immediately precede the declaration keyword (`theorem`, `def`, `lemma`). Interleaving a command like `omit` between the docstring and declaration causes a syntax error.

---

## 7. Instances Needed in Many Files: Fix the Cause or Use a Scope

`attribute [local instance] foo` makes the definition `foo` an instance until the end of the current section or file. It is the right tool for a single file. When the same line is copied into hundreds of files, the choice of structure is made again in every file instead of once:

- Files with the line and files without it elaborate the same expression differently. Without it, synthesis fails or finds another instance.
- Renaming `foo`, or switching to a better structure, means editing every one of those files.

In one formalization of about 175,000 modules, `attribute [local instance]` appeared in 46,562 files. A single definition, a `StarRing` on a CM field, was registered this way in 24,134 files. `Matrix.normedAddCommGroup` was registered locally in 1,794 files, while Mathlib's own scope for it (`open scoped Matrix.Norms.Elementwise`) was opened in only 216.

Count the repeated registrations first:

```bash
rg -o --no-filename 'attribute \[local instance\] (\S+)' -r '$1' . | sort | uniq -c | sort -rn | head
```

For every definition near the top of that list, find out why it is not already an instance, and pick one of the fixes below.

### 7.1. The Structure Is Canonical but an Instance Argument Is Missing

The commonest cause is a `Prop` class, such as `IsCMField E`, stored as an ordinary structure field. Mathlib's global instance needs that class as an instance argument, cannot find it, and so a wrapper definition gets registered locally in every file:

```lean
import Mathlib.NumberTheory.NumberField.CMField

open NumberField

structure Host where
  E : Type
  [field : Field E]
  [numberField : NumberField E]
  isCM : IsCMField E          -- an ordinary field, not an instance

attribute [instance] Host.field Host.numberField

-- ❌ Fails: "failed to synthesize instance of type class Star H.E"
example (H : Host) (x : H.E) : star (star x) = x := star_star x

-- ❌ The workaround that spread to every file:
--   @[instance_reducible] noncomputable def cmStar : StarRing H.E :=
--     @IsCMField.starRing H.E _ _ H.isCM _
--   attribute [local instance] cmStar

-- ✅ Register the stored field once, next to the structure.
attribute [instance] Host.isCM

-- Mathlib's global `IsCMField.starRing` now applies in every importing file.
example (H : Host) (x : H.E) : star (star x) = x := star_star x
```

Verified on Lean `v4.35.0` with Mathlib `v4.35.0`. In the formalization above, three files declared `instance : IsCMField H.E := H.isCMField_hostE` themselves, but the 24,134 files that registered the wrapper never did.

- Mark `Prop` fields that are classes with `[...]` binders in the `structure`, or register them with `attribute [instance]` in the structure's file.
- `Prop` instances cannot conflict with each other (proof irrelevance), so registering them globally is safe.

### 7.2. The Structure Is Not Canonical: Use a Scope

Some structures are deliberately not instances, because a type has several natural choices: the norms on matrices, a monoidal structure on a category, a relation derived from one particular valuation. Give each choice a **scope**: a namespace in which the definitions are `scoped` instances. Files activate the scope with `open scoped`.

**Reuse Mathlib's scopes first.** Mathlib (`v4.35.0`, `Mathlib/Analysis/Matrix/Normed.lean`) defines the matrix norms as definitions and groups them by scope:

```lean
namespace Norms.Elementwise

attribute [scoped instance]
  Matrix.seminormedAddCommGroup
  Matrix.normedAddCommGroup
  Matrix.normedSpace
  ...
```

```lean
import Mathlib.Analysis.Matrix.Normed

-- ✅ One line activates the whole elementwise-norm package for one declaration.
open scoped Matrix.Norms.Elementwise in
example (A : Matrix (Fin 2) (Fin 2) ℝ) : 0 ≤ ‖A‖ := norm_nonneg A

-- ❌ Outside the scope: "failed to synthesize instance of type class Norm (Matrix (Fin 2) (Fin 2) ℝ)"
example (A : Matrix (Fin 2) (Fin 2) ℝ) : 0 ≤ ‖A‖ := norm_nonneg A
```

Search Mathlib for `attribute [scoped instance]` and `scoped[` before defining a scope of your own. Other scopes, such as `Matrix.Norms.Frobenius`, `Matrix.Norms.Operator` and `MatrixOrder`, are built the same way. Outside the namespace, Mathlib also uses the one-line form `scoped[Matrix.Norms.L2Operator] attribute [instance] Matrix.instL2OpNormedAddCommGroup`.

**For project definitions, declare the scope once:**

```lean
def Pt := Nat

@[instance_reducible] def ptInhabitedFive : Inhabited Pt := ⟨(5 : Nat)⟩

namespace MyProject.PtFive
attribute [scoped instance] ptInhabitedFive
end MyProject.PtFive

-- ❌ Inactive until the scope is opened: "failed to synthesize instance of type class Inhabited Pt"
example : Inhabited Pt := inferInstance

-- ✅ For the rest of the section or file
section
open scoped MyProject.PtFive
example : (default : Pt) = (5 : Nat) := rfl
end

-- ✅ For one declaration
open scoped MyProject.PtFive in
example : (default : Pt) = (5 : Nat) := rfl
```

Verified on Lean `v4.33.1` and `v4.35.0`. Each file still needs one line, but the line names a choice (`MyProject.PtFive`), not an implementation detail. Several definitions can share one scope, and adding a definition to the scope changes every user at once.

**Alternative: a type synonym.** If one type is always used with the same non-canonical structure, define a synonym (`def Pt := Nat`, as above) and make the structure a global instance on the synonym. The synonym does not inherit the original type's instances (the example above shows `Inhabited Pt` missing although `Nat` has one), so every instance it needs must be transferred explicitly, for example with `inferInstanceAs`. This is the better fix when the synonym already exists for another reason, and more work otherwise.

### 7.3. Mark Definitions Meant as Instances `@[instance_reducible]`

A definition of class type that will be used as an instance should carry `@[instance_reducible]`, as Mathlib's `Matrix.normedAddCommGroup` does. Without it, both the definition and each `attribute [local instance]` / `attribute [scoped instance]` that uses it report (Lean `v4.33.1` and `v4.35.0`):

```text
warning: Definition `ptInhabitedSeven` of class type is semireducible. Most type class instances should be
instance-reducible, so consider marking this definition with `@[instance_reducible]`. If it is
intentionally semireducible, this warning can be disabled with `set_option warn.classDefReducibility false`.
```

Since Lean `v4.29.0`, unification no longer unfolds ordinary definitions automatically when it compares implicit arguments, including instances. This is why the reducibility of instance definitions matters. Since Lean `v4.33.0` (lean4#13637), `@[implicit_reducible]` no longer lets type class search see through a definition. Use `@[instance_reducible]` for definitions that are meant to be instances.

### Rules

- **Fix the cause before scoping.** If the instance is missing only because an argument is not an instance (§7.1), register that argument once. Only structures that are genuinely non-canonical need a scope.
- **One choice, one scope.** Name the scope after the choice it makes (`Matrix.Norms.Elementwise`, `MyProject.CMConjugation`), not after the file that first needed it. Reuse Mathlib's scope when one exists.
- **Keep `attribute [local instance]` local.** Use it for a structure needed in one file or one section. Mathlib itself does this for a single section of `Mathlib/Analysis/Matrix/Normed.lean` (`attribute [local instance] Matrix.seminormedAddCommGroup`). A definition registered locally in more than a few files is a design decision and belongs in one place.
- **Do not silence `warn.classDefReducibility`.** Add `@[instance_reducible]` to the definition instead.
