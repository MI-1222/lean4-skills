# Statement-First Decomposition (Scaling Top-Down Proofs)

[Sorry-driven development](sorry_driven_development.md) works well inside one file: the skeleton lives in a single theorem, and each `have ... := by sorry` is a milestone. When a formalization grows to many files, several agents, or a long-running effort, two problems appear:

1. **Sorries leak into every audit.** While any milestone is open, `#print axioms` on everything downstream reports `sorryAx`, so you cannot tell finished parts from unfinished ones.
2. **Proof files import each other.** Downstream files must import the files that _prove_ their prerequisites, so the build graph becomes a long chain and nothing can be built or worked on in parallel.

**Statement-first decomposition** solves both by splitting every milestone into a **statement** (a `Prop`-valued definition) and a **proof** that takes the statements of its prerequisites as hypotheses. The pattern has been used at very large scale (thousands of `X.Statement` definitions in a single formalization).

---

## 1. The Pattern

Each milestone `X` gets two declarations:

| Declaration   | Kind                     | Lives in           | Depends on                           |
| :------------ | :----------------------- | :----------------- | :----------------------------------- |
| `X.Statement` | `def X.Statement : Prop` | a statements file  | definitions only, never proofs       |
| `X.proof`     | `theorem`                | its own proof file | statements of its prerequisites only |

A final **assembly** theorem plugs the proofs into each other and has no hypotheses.

```lean
namespace Demo

/-- Contract for the first milestone. -/
def AddZero.Statement : Prop := ∀ n : Nat, n + 0 = n

/-- Contract for the second milestone. -/
def ZeroAdd.Statement : Prop := ∀ n : Nat, 0 + n = n

/-- Contract for the main result. -/
def Main.Statement : Prop := ∀ n : Nat, n + 0 = 0 + n

theorem AddZero.proof : AddZero.Statement := by
  intro n
  rfl

theorem ZeroAdd.proof : ZeroAdd.Statement := by
  intro n
  exact Nat.zero_add n

/-- The main argument, conditional on its two prerequisites. -/
theorem Main.proof (hAddZero : AddZero.Statement) (hZeroAdd : ZeroAdd.Statement) :
    Main.Statement := by
  intro n
  rw [hAddZero n, hZeroAdd n]

/-- Assembly: no hypotheses remain. -/
theorem main : Main.Statement := Main.proof AddZero.proof ZeroAdd.proof

end Demo
```

- `intro` unfolds `X.Statement` to reach its binders, so a proof starts exactly as if the statement were written inline.
- Instance binders in a statement (`∀ (K : Type u) [Field K], ...`) can be introduced as `_` (`intro K _`). The instance stays in the local context and type class resolution still finds it.
- A hypothesis `h : X.Statement` can be applied directly (`h n`) because application also unfolds the definition.

### File Layout

```text
MyProject/
├── Statements/Analysis.lean     -- def AddZero.Statement, def ZeroAdd.Statement, ...
├── Statements/Main.lean         -- def Main.Statement
├── Proofs/AddZero.lean          -- import Statements.Analysis;              theorem AddZero.proof
├── Proofs/ZeroAdd.lean          -- import Statements.Analysis;              theorem ZeroAdd.proof
├── Proofs/Main.lean             -- import Statements.Analysis, Statements.Main; theorem Main.proof
└── Main.lean                    -- imports all Proofs/*;                     theorem main
```

Proof files import **only statements files** (and the definitions those need). They never import each other, so Lake can build them in parallel, and editing one proof does not rebuild the others.

### Top-Level Statements and the Challenge File

When the final result will be judged against a challenge file with Comparator (see `lean4-cli` → `soundness_and_axiom_audit.md` §8), keep the top-level claims in their own statements file and mirror it in the challenge:

```text
src/
├── Statements.lean   -- imports only Mathlib; `def MainClaim : Prop := ...` (definitions only)
├── Challenge.lean    -- the same definitions, byte for byte, plus `theorem main_claim : MainClaim := by sorry`
├── Proofs/...        -- statement-first milestones and assembly theorems
└── Main.lean         -- imports Statements and the assemblies; `theorem main_claim : MainClaim := main`
```

- **Why a copy, not an import**: the challenge must import only Mathlib, so that it is compiled and exported where no project code has run. The solution cannot import the challenge either, because the challenge contains `sorry`. The definitions therefore exist twice and must stay identical.
- **`Statements.lean` imports only Mathlib**, never a project file. Otherwise the meaning of the claim depends on project definitions that the challenge cannot see.
- **`Main.lean` contains nothing but the claimed theorems**, with the challenge's exact names and types, each a one-line reference to an assembly theorem. Reviewers then read `Statements.lean` and `Challenge.lean` to know what is claimed, and never have to read the proof for that. In one formalization of about 175,000 modules, `Main.lean` was five one-line theorems.
- **Check the copy mechanically**: in CI, build `Challenge` alone in a clean clone with only Mathlib's cache (`lake exe mathlib/cache get`, then `lake build Challenge`), and compare its definition block with `Statements.lean`.

---

## 2. Why It Helps

1. **The statement is the header fence.** `X.Statement` is the immutable contract from [header_fence_and_docstrings.md](header_fence_and_docstrings.md), written down once in a file that contains no proofs. Whoever proves `X` must produce exactly `theorem X.proof ... : X.Statement`.
2. **No `sorry` in intermediate states.** An unfinished milestone is simply an unproven statement, not a `sorryAx` that contaminates everything downstream. Finished parts can be built, checked and reviewed while others are still open.
3. **Parallel work and parallel builds.** Each `X.proof` can be handed to a different agent or person, and the files build concurrently.
4. **Progress is explicit.** The open work is exactly the set of statements that no assembly yet discharges, visible from the assembly theorem's dependencies.

### When to Use It

| Situation                                                      | Recommended structure                                 |
| :------------------------------------------------------------- | :---------------------------------------------------- |
| One theorem, a handful of milestones, one session              | `have ... := by sorry` in one file (sorry-driven)     |
| Several helper lemmas in one file                              | Standalone lemmas with `sorry` (sorry-driven, Step 4) |
| Many files, multiple agents or contributors, long-running work | Statement-first decomposition                         |

---

## 3. Pitfalls and Rules

### 3.1. Conditional Proofs Look Clean to `#print axioms` (Critical)

A proof that takes statements as hypotheses reports **no axioms at all**, even if those statements are never proved:

```lean
#print axioms Demo.Main.proof
-- 'Demo.Main.proof' does not depend on any axioms
```

`Main.proof` is only a conditional result. Its type, `AddZero.Statement → ZeroAdd.Statement → Main.Statement`, shows the open prerequisites, but the axiom list does not.

**Rules**:

- Run the soundness audit (`#print axioms`) **only on assembly theorems**, never on `X.proof` declarations.
- Confirm that the assembly theorem has **no statement hypotheses left**: `#check @Demo.main` must print `Demo.main : Demo.Main.Statement` with no arrows in front.
- Never report a milestone as done because its `X.proof` compiles; it is done when an assembly that depends on it compiles without hypotheses.

### 3.2. A False Statement Poisons Everything Downstream

A conditional proof from a false statement is valid Lean and proves anything:

```lean
def Bogus.Statement : Prop := ∀ n : Nat, n = n + 1

theorem zero_eq_one_of_bogus (h : Bogus.Statement) : (0 : Nat) = 1 := h 0
-- 'zero_eq_one_of_bogus' does not depend on any axioms
```

Downstream work built on a wrong statement is wasted, and nothing fails until someone tries to prove the statement itself.

**Rules**:

- Before handing out or building on a statement, sanity-check it: probe boundary values and try to refute it (see `lean4-proof-repair` → `falsification_and_disproof.md`).
- Prefer proving the riskiest statements first (the statement-level version of "hardest case first").

### 3.3. Adding a Hypothesis Is a Contract Change

An agent stuck on `X.proof` may be tempted to add a new hypothesis `(hY : Y.Statement)` for some convenient `Y`. That is exactly the goal drift the header fence forbids, in a new form: it moves the difficulty into an unproven statement.

**Rules**:

- The prerequisite list of `X.proof` is part of the plan. Adding a prerequisite requires the same approval as changing a theorem statement.
- Every new statement must itself be scheduled for a proof and pass the falsification check in §3.2.

### 3.4. Unfold Before Rewriting with a Statement

`intro` and function application see through `X.Statement`, but `simp` and `rw` do not use a hypothesis `h : X.Statement` as a rewrite rule until the definition is unfolded:

```lean
def Foo (n : Nat) : Nat := n + 0

-- ❌ Fails: simp reports "This simp argument is unused: h"
example (h : AddZero.Statement) (m : Nat) : Foo m = m := by
  simp only [Foo, h]

-- ✅ Works: unfold the statement first
example (h : AddZero.Statement) (m : Nat) : Foo m = m := by
  unfold AddZero.Statement at h
  simp only [Foo, h]

-- ✅ Works: instantiate the hypothesis and rewrite with the result
example (h : AddZero.Statement) (m : Nat) : Foo m = m := by
  rw [Foo, h m]
```

Use `unfold X.Statement at h` (or `simp only [X.Statement] at h`), or apply the hypothesis to its arguments (`h m`) and rewrite with the result.

### 3.5. Keep Statements Readable

Statements written as one long `∀` over dozens of binders are hard to review, and reviewing them is the whole point (§3.2).

- Bundle recurring data and hypotheses into a `structure` and quantify over that.
- Give every `X.Statement` a docstring that states the claim in mathematical language.
- Keep each statement close to the informal milestone it formalizes; split a statement rather than letting it grow.

### 3.6. Choose the Granularity Deliberately

One file per milestone maximizes parallelism, but every module has a fixed cost: Lean loads its imports, and Lake writes per-module build metadata. In a formalization with about 175,000 single-milestone modules, the per-module setup files Lake writes averaged about 6 MB each (around a terabyte in total) and had to be deleted during the build.

- Group closely related milestones into one statements file and, where they are proved together, one proof file.
- Split a proof into its own file when it is slow to elaborate, worked on independently, or frequently edited.
- Statements files should import only what the definitions need. Importing proof files from a statements file brings back the long build chain.

### 3.7. Write Universe Arguments Explicitly (Universe-Polymorphic Statements)

A statement that quantifies over types (`∀ (K : Type u) ...`) is a universe-polymorphic definition, and **every `theorem` header gets fresh universe parameters for each statement it mentions without explicit levels**. Two failures follow (verified on Lean `v4.33.1`):

```lean
universe u

def Pointed.Statement : Prop := ∀ (K : Type u) [Inhabited K], ∃ _ : K, True
def NatPointed.Statement : Prop := ∃ _ : Nat, True
def Small.Statement : Prop := ∀ K : Type, Nonempty K → True

theorem Pointed.proof : Pointed.Statement := by   -- becomes Pointed.proof.{u_1}
  intro K _
  exact ⟨default, trivial⟩

-- ❌ Failure 1: the hypothesis is used at a concrete universe.
-- `h` has a fresh parameter `u_1` that the body cannot specialize:
-- "Application type mismatch: ... Nat has type Type ... but is expected to have type Type u_1"
theorem NatPointed.proof (h : Pointed.Statement) : NatPointed.Statement := h Nat

-- ❌ Failure 2: the universe appears only in a hypothesis (a phantom universe).
-- `Small.proof` compiles, but the assembly cannot choose the level:
-- "declaration `small` contains universe level metavariables"
theorem Small.proof (h : Pointed.Statement) : Small.Statement := fun _ _ => trivial
theorem small : Small.Statement := Small.proof Pointed.proof
```

```lean
-- ✅ Pin the level where the prerequisite is used at a fixed universe
theorem NatPointed.proof (h : Pointed.Statement.{0}) : NatPointed.Statement := h Nat
theorem natPointed : NatPointed.Statement := NatPointed.proof Pointed.proof

-- ✅ Name the shared universe when the milestone is polymorphic in it
def Lift.Statement : Prop := ∀ (K : Type u) [Inhabited K], Nonempty K

theorem Lift.proof (h : Pointed.Statement.{u}) : Lift.Statement.{u} := by
  intro K _
  obtain ⟨x, -⟩ := h K
  exact ⟨x⟩

-- ✅ Or fix the level at the assembly
theorem small : Small.Statement := Small.proof.{0} Pointed.proof.{0}
```

**Rules**:

- In every `X.proof` header, write the universe arguments of each universe-polymorphic statement explicitly: `.{0}` (or another fixed level) where the prerequisite is used at that level, `.{u}` where the milestone is polymorphic in the same universe.
- A polymorphic proof such as `Pointed.proof` can be used at any level (`Pointed.Statement.{1}` works), so prove statements at the most general universe and pin levels only at the use site.
- Inside a statement body, `Type _` fails with "Failed to infer universe levels in binder type". Declare `universe u` and write `Type u`, or use Mathlib's `Type*`, which adds a universe parameter to the definition.
- Fixing a type to `Type` inside a statement (`(σ : Type)`) to avoid universe work makes the claim weaker. That is acceptable for an internal milestone, but it is a contract change for a top-level statement (§3.3) and a point for the statement fidelity review.

---

## 4. Checklist

- [ ] Does every milestone have a `def X.Statement : Prop` with a docstring, in a file that contains no proofs?
- [ ] Does each `X.proof` take as hypotheses only the prerequisite statements listed in the plan?
- [ ] Do proof files import statements files only, never other proof files?
- [ ] Has each statement been sanity-checked against boundary values before others build on it?
- [ ] Is there an assembly theorem whose `#check @...` shows no remaining statement hypotheses?
- [ ] Was `#print axioms` run on the assembly theorem, not on conditional `X.proof` declarations?
- [ ] Does every `X.proof` header give explicit universe arguments (`.{0}`, `.{u}`) to each universe-polymorphic statement it mentions?
- [ ] If the result goes to Comparator, does `Statements.lean` import only Mathlib, match the definitions in `Challenge.lean` exactly, and does `Main.lean` contain only one-line references to assembly theorems?
