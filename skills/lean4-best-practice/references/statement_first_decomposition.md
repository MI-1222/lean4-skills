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

### Isolating the Novel Core

A large formalization usually contains one genuinely new argument and a layer of standard mathematics that connects it to the published claims (symmetry, a functional equation, a passage from primitive to all characters, a change of number system). Keep the two apart: state the new argument as a single **core statement**, and derive every top-level claim from it by a short **reduction** that uses only library lemmas.

```text
Main claims  ←  reductions (short, library only)  ←  Core.Statement  ←  the long development
```

```lean
namespace Demo

/-- Core claim, the novel part: no natural number squares to 2. -/
def Core.Statement : Prop := ∀ n : Nat, n * n ≠ 2

/-- Published claim: no integer squares to 2. -/
def Main.Statement : Prop := ∀ z : Int, z * z ≠ 2

/-- Standard reduction: pass from `z` to `z.natAbs`, using library lemmas only. -/
theorem Main.of_core (h : Core.Statement) : Main.Statement := by
  intro z hz
  apply h z.natAbs
  have e : ((z.natAbs * z.natAbs : Nat) : Int) = z * z := Int.natAbs_mul_self
  omega

/-- The long development, in its own files. -/
theorem Core.proof : Core.Statement := by
  intro n h
  match n, h with
  | 0, h => simp at h
  | 1, h => simp at h
  | n + 2, h =>
    have : 4 ≤ (n + 2) * (n + 2) :=
      Nat.mul_le_mul (show 2 ≤ n + 2 by omega) (show 2 ≤ n + 2 by omega)
    omega

/-- Assembly. -/
theorem main : Main.Statement := Main.of_core Core.proof

end Demo
```

In one formalization of about 175,000 modules, five top-level claims reduced to a single core statement through two files of about 90 lines in total, built from Mathlib's functional-equation lemmas. Reviewers could check the step from the core to every claim without reading the development.

**Rules**:

- **Write the reduction first.** `Main.of_core` is small, and once it compiles it shows that the core statement is enough for every claim. Do this before investing in `Core.proof`, and run the falsification check from §3.2 on the core statement itself.
- **Put the core statement in a statements file that imports only Mathlib**, like `Statements.lean`, and state it in Mathlib's vocabulary. Reduction files then import Mathlib and that file, and build in minutes in a clean clone. In the formalization above, the core definition sat in a file that also held proofs and imported the development. A reduction that needed the definition therefore imported the whole development, and could not be built on its own.
- **One reduction per claim.** Each top-level claim gets its own `X.of_core`, and `Main.lean` stays a list of one-line references (`theorem x : X := X.of_core Core.proof`).
- **Keep reductions on the library.** A reduction that needs project definitions or lemmas is part of the development, not a reduction. Move that work behind the core statement, or change the core statement.
- **Do not let reductions carry hypotheses beyond the core.** An extra statement hypothesis on `X.of_core` is an open prerequisite of the top-level claim, and §3.3 applies to it.

### Citing Published Results as Statements

A long development leans on many published theorems that are not in Mathlib. Do not prove them inline where they are first needed, and never add them as `axiom`. State each one as a `Prop` in a `Published` namespace, bundle the ones a development relies on into a `structure ... : Prop`, and prove the development conditional on that bundle. The bundle is then the explicit list of cited results that are still unproven.

Continuing the example above:

```lean
namespace Demo

/-- Squares modulo 3. Cite the source here: author, title, theorem number. -/
def Published.SquareModThree : Prop := ∀ n : Nat, n * n % 3 ≠ 2

/-- Squares modulo 4. Cite the source here. -/
def Published.SquareModFour : Prop := ∀ n : Nat, n * n % 4 ≠ 2 ∧ n * n % 4 ≠ 3

/-- The published results this development still relies on. -/
structure Literature : Prop where
  squareModThree : Published.SquareModThree
  squareModFour : Published.SquareModFour

/-- A second claim that uses the same bundle. -/
def Other.Statement : Prop := ∀ n : Nat, n * n ≠ 3

theorem Core.of_literature (L : Literature) : Core.Statement := by
  intro n h
  exact L.squareModThree n (by rw [h])

theorem Other.of_literature (L : Literature) : Other.Statement := by
  intro n h
  exact (L.squareModFour n).2 (by rw [h])

/-- Discharging a field: prove the published result. -/
theorem Published.SquareModThree.proof : Published.SquareModThree := by
  intro n
  rw [Nat.mul_mod]
  have h := Nat.mod_lt n (show 3 > 0 by decide)
  match n % 3, h with
  | 0, _ | 1, _ | 2, _ => decide

theorem Published.SquareModFour.proof : Published.SquareModFour := by
  intro n
  rw [Nat.mul_mod]
  have h := Nat.mod_lt n (show 4 > 0 by decide)
  match n % 4, h with
  | 0, _ | 1, _ | 2, _ | 3, _ => decide

/-- Assembly: the bundle is fully discharged, so no hypothesis remains. -/
theorem core : Core.Statement :=
  Core.of_literature ⟨Published.SquareModThree.proof, Published.SquareModFour.proof⟩

end Demo
```

- A field of a `structure ... : Prop` is a proof, so `L.squareModThree n` applies the cited result directly.
- One bundle serves every claim that cites the same results, so `Core.of_literature` and `Other.of_literature` take one argument each, not one per citation.

In the formalization of about 175,000 modules mentioned above, the published results lived in `PublishedTheorems/` directories as `def ... : Prop`. In the final version, the bundle of results that were still open had three fields. About 190 theorems in one file derived the published results used downstream from it, and the final assembly discharged the three fields by name.

**Rules**:

- **State the result as the source states it, and cite the source in the docstring.** Keep every hypothesis of the published version, such as characteristic zero, algebraic closure or properness. A version stronger than the published one may be false, and §3.2 applies. A weaker or specialized version is fine, but say in the docstring how it differs.
- **Check that the hypotheses can be satisfied.** A cited statement whose hypotheses no object meets, for example because a project definition such as "nef" or "big" is wrong, is vacuously true and proves nothing downstream. Next to the statement, add an `example` that builds one object meeting all the hypotheses (in the formalization above, projective space for a vanishing theorem). §3.8 has the general rules.
- **Name the fields after the results** (`kawamataViehweg`, not `p6`). The bundle is what reviewers read to see what the result still depends on, and the formalization above used `p1` … `q7`.
- **Bundle instead of chaining.** A theorem with a dozen statement hypotheses in a row (`A → B → C → ... → X`) is hard to read and hard to keep consistent. The formalization above had theorems with sixteen. Group them in one structure per area, and nest structures when areas combine.
- **Keep adapters next to the statement.** Corollaries that restate a cited result in the form the development needs (`KawamataViehweg.twist (h : KawamataViehweg) ...`) belong in the statement's file, so that each consumer does not derive them again.
- **Shrink the bundle, never hide it.** Progress means proving a `Published.X`, plugging the proof into the assembly, and deleting the field. If some citations stay unproven, the top-level theorem must show them in its type (`theorem main (L : Literature) : Main.Statement`) and be reported as conditional. An `axiom` would hide them from the type, and Comparator rejects any axiom its config does not allow.

### Layered Directories for Larger Developments

When a development also has its own definitions, cited results (previous section) and witnesses (§3.8), give each kind of file its own directory and fix which directory may import which:

```text
MyProject/
├── Definitions/   -- def, structure, instance, plus the basic API lemmas about them
├── Statements/    -- def X.Statement : Prop, and nothing else
├── Published/     -- def Published.X : Prop, adapters, satisfiability examples
├── Proofs/        -- theorem X.proof, theorem Published.X.proof
├── Witnesses/     -- theorem X.witness, tests; built by a test target, imported by nothing
└── Main.lean      -- assembly theorems
```

| Layer         | May import                                        | Must never import                                |
| :------------ | :------------------------------------------------ | :----------------------------------------------- |
| `Definitions` | Mathlib, `Definitions`                            | `Statements`, `Published`, `Proofs`, `Witnesses` |
| `Statements`  | Mathlib, `Definitions`, `Statements`, `Published` | `Proofs`, `Witnesses`                            |
| `Published`   | Mathlib, `Definitions`, `Statements`, `Published` | `Proofs`, `Witnesses`                            |
| `Proofs`      | Mathlib, `Definitions`, `Statements`, `Published` | `Proofs`, `Witnesses`                            |
| `Witnesses`   | any layer                                         | nothing; but no layer imports `Witnesses`        |
| `Main.lean`   | `Statements`, `Proofs`                            | `Witnesses`                                      |

The rule that matters most is that **nothing above `Proofs` imports `Proofs`**. Then reading a definition or a statement never requires reading a proof, editing a proof never rebuilds a statement, and the proof files build in parallel.

**Directory names do not enforce anything.** In the formalization of about 175,000 modules mentioned above, one library had directories named `Definitions`, `Statements`, `PublishedTheorems`, `Proofs` and `Counterexamples`. Its import lines went against that order on a large scale:

- `Definitions` imported `Proofs` 1,968 times, and held 30,863 theorems.
- `Statements` imported `Proofs` 94 times.
- `PublishedTheorems` imported `Proofs` 307 times.
- `Proofs` imported `Counterexamples` 510 times.

So the names described the intent, not the dependency graph. Check the order in CI from the first commit. The following check assumes the layer directories sit directly under `MyProject/`. It prints every import that goes against the table and fails if there is one:

```bash
! grep -rEo --include='*.lean' '^import MyProject\.[A-Za-z]+' MyProject \
  | awk -F'[:/.]' '{ print $2, "->", $NF, "(" $0 ")" }' \
  | grep -E '^Definitions -> (Statements|Published)|^(Definitions|Statements|Published|Proofs) -> (Proofs|Witnesses)|^Main -> Witnesses'
```

**Rules**:

- **Keep `Definitions` light.** Basic API lemmas about a definition (`simp` lemmas, unfolding lemmas, the instances it needs) belong next to it. Anything with a real argument goes to `Proofs` as a milestone.
- **Put shared lemmas in `Definitions`, not in another proof file.** When two proofs need the same lemma, the "proofs never import proofs" rule leaves two options: move the lemma down to `Definitions` if it is basic API, or make it a milestone with its own `X.Statement`.
- **Keep witnesses out of the main import closure.** List the `Witnesses` library in `defaultTargets` so that every build checks it (§3.8), but never import it from `Proofs` or `Main.lean`.
- **Add the layer check before the first proof file.** Fixing the order after the fact means moving declarations between thousands of files.

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
- Also check the opposite failure, a statement that holds only because its premises cannot be met (§3.8).

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

### 3.8. Witness That the Premises Can Be Met

§3.2 is about a statement that is false. This section is about the opposite failure: a statement that is true for the wrong reason. A statement of the form `∀ x, Premises x → Conclusion x` is trivially true when no `x` meets `Premises`. This happens easily when the premises are a project definition or a `structure ... : Prop` bundle with many fields, and one field contradicts another or a definition is wrong. Such a statement compiles, passes `#print axioms` (§3.1), and gives nothing downstream: whoever uses it must eventually produce `Premises x`, and finds out late that nobody can.

```lean
namespace Demo.Buggy

/-- Premises with a bug: `0 < n` and `n < 1` contradict each other. -/
structure Good (n : Nat) : Prop where
  pos : 0 < n
  small : n < 1

/-- A milestone whose premises no `n` meets. -/
def Bound.Statement : Prop := ∀ n, Good n → n = 42

-- ❌ Compiles, and proves a "result" that says nothing.
theorem Bound.proof : Bound.Statement := fun n h => absurd h.pos (by have := h.small; omega)

-- The witness cannot be built. Its negation can, which exposes the bug.
example : ¬ ∃ n, Good n := fun ⟨_, h⟩ => absurd h.pos (by have := h.small; omega)

end Demo.Buggy

namespace Demo

/-- Premises after the fix. -/
structure Good (n : Nat) : Prop where
  pos : 0 < n
  small : n < 10

/-- ✅ Non-vacuity witness: a concrete `n` that meets every premise. -/
theorem Good.witness : ∃ n, Good n := ⟨3, by decide, by decide⟩

end Demo
```

In the formalization of about 175,000 modules mentioned above, `Counterexamples/` directories held such witnesses, and the project had 20 files with `Inhabited` in their names. One of them builds the cyclotomic field ℚ(ζ₃), its ring of integers and its trace form to meet a whole list of premises at once. Every file was in the import closure of `Main`, so each build checked the witnesses again.

**Rules**:

- **Give every premise bundle a witness.** For each project-defined premise or `structure ... : Prop` that statements quantify over, add `theorem X.witness : ∃ x, Premises x` (or `Nonempty ...`) built from a concrete object. Write it when the bundle is written, before anyone proves a statement that uses it.
- **Pick a non-degenerate witness.** Degenerate objects (the empty type, the zero module, `Unit`, the trivial character) often meet premises for reasons that have nothing to do with the intended mathematics, and a statement that holds only for them is still empty. Choose an object for which the conclusion has real content, or add non-degeneracy facts to the witness itself. The witness in the formalization above also proved that the rank is positive and that complex conjugation is not the identity.
- **Keep witnesses in the build.** Put them in a file that a default build target compiles, so that a later edit to a definition that makes the premises unsatisfiable breaks the build at once. A separate test library listed in `defaultTargets` works and keeps the import closure of `Main` smaller.
- **Treat a short proof by contradiction from the premises as a red flag.** If `X.proof` closes with `absurd`, `exfalso` or `False.elim` from its premises without the expected argument, try to build the witness before accepting the proof. If the negation of the witness is provable (`¬ ∃ x, Premises x`), the premises are broken.
- **A witness does not check the conclusion.** It shows only that the statement has content. Also check that the conclusion is not false for the witness, as in §3.2. The witness is the natural first test case.

---

## 4. Checklist

- [ ] Does every milestone have a `def X.Statement : Prop` with a docstring, in a file that contains no proofs?
- [ ] Does each `X.proof` take as hypotheses only the prerequisite statements listed in the plan?
- [ ] Do proof files import statements files only, never other proof files?
- [ ] In a layered layout, does CI check that `Definitions`, `Statements` and `Published` never import `Proofs`, and that nothing imports `Witnesses`?
- [ ] Has each statement been sanity-checked against boundary values before others build on it?
- [ ] Does every premise bundle that statements quantify over have a non-degenerate `X.witness : ∃ x, Premises x` that a default build target compiles?
- [ ] Is the novel argument stated as one core statement in a Mathlib-only statements file, with each top-level claim derived from it by a short reduction that uses only library lemmas?
- [ ] Is each cited published result a `def Published.X : Prop` with a citation and a satisfiability `example`, collected in a `structure ... : Prop` bundle with descriptive field names, and does the top-level theorem either discharge the bundle or show it in its type?
- [ ] Is there an assembly theorem whose `#check @...` shows no remaining statement hypotheses?
- [ ] Was `#print axioms` run on the assembly theorem, not on conditional `X.proof` declarations?
- [ ] Does every `X.proof` header give explicit universe arguments (`.{0}`, `.{u}`) to each universe-polymorphic statement it mentions?
- [ ] If the result goes to Comparator, does `Statements.lean` import only Mathlib, match the definitions in `Challenge.lean` exactly, and does `Main.lean` contain only one-line references to assembly theorems?
