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

Proof files import **only statements files** (and the definitions those need). They never import each other, so Lake can build them in parallel, and editing one proof does not rebuild the others. §3.11 shows how to check this with the length of the longest import chain.

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
- **Cite different results as different propositions.** Two fields with the same type cite one proposition under two names. At least one of them then does not state the result its name refers to, and the bundle looks longer than the list of results still open. Fix the misstated field so that it states its source (§3.2 applies to it). If the same result really is cited twice, keep one field and name both sources in its docstring. Check every bundle mechanically with `#duplicate_fields` from `lean4-cli` (`scripts/duplicate_fields.lean`):

  ```bash
  { echo "import MyProject.Main"; cat <skills-path>/lean4-cli/scripts/duplicate_fields.lean
    echo "#duplicate_fields MyProject.Literature"; } | lake env lean --stdin
  ```

  It expands nested bundles and parent structures, and reports both identical types and types that are only definitionally equal, such as a `def Published.B : Prop := Published.A` that renames another citation. A definitional match can also come from computation (`k + 0 = k` and `k = k` for `k : Nat`), so read both statements before merging. In the formalization above, two of the three fields of the final bundle, `caraianiLocalGlobalDual` and `galoisRepOfPolarizedPairLit`, had the same type, and the assembly filled both with the same hypothesis `h`: the bundle named three open results, but only two were different.

- **Bundle instead of chaining.** A theorem with a dozen statement hypotheses in a row (`A → B → C → ... → X`) is hard to read and hard to keep consistent. The formalization above had theorems with sixteen. Group them in one structure per area, and nest structures when areas combine.
- **Keep adapters next to the statement.** Corollaries that restate a cited result in the form the development needs (`KawamataViehweg.twist (h : KawamataViehweg) ...`) belong in the statement's file, so that each consumer does not derive them again.
- **Shrink the bundle, never hide it.** Progress means proving a `Published.X`, plugging the proof into the assembly, and deleting the field. If some citations stay unproven, the top-level theorem must show them in its type (`theorem main (L : Literature) : Main.Statement`) and be reported as conditional. An `axiom` would hide them from the type, and Comparator rejects any axiom its config does not allow.

### One Development for Several Variants

A long development is often needed in more than one version: arbitrary and compactly supported coefficients, a local and a global form, a class of objects and a smaller one. When the shared part is written against the first version, calling its theorems in proofs or naming its definitions in statements, the second version tends to need its own copy of those declarations and of the ones built on them. Turning the theorem into a hypothesis is not enough when the type of the hypothesis still names the first version:

```lean
namespace Demo.OneVersion

/-- Numbers of the first version. -/
def IsEven (n : Nat) : Prop := n % 2 = 0

/-- Numbers of the second version. -/
def DivFour (n : Nat) : Prop := n % 4 = 0

def EvenAdd.Statement : Prop := ∀ a b, IsEven a → IsEven b → IsEven (a + b)

/-- A hypothesis instead of a concrete theorem, but its type still names `IsEven`. -/
theorem even_twice (h : EvenAdd.Statement) (a b : Nat) (ha : IsEven a) (hb : IsEven b) :
    IsEven (a + b + (a + b)) :=
  h _ _ (h a b ha hb) (h a b ha hb)

-- ❌ Fails for the second version:
-- "Application type mismatch: The argument ha has type DivFour a
--  but is expected to have type IsEven a"
theorem divFour_twice (h : EvenAdd.Statement) (a b : Nat) (ha : DivFour a) (hb : DivFour b) :
    DivFour (a + b + (a + b)) :=
  even_twice h a b ha hb

end Demo.OneVersion
```

Make **what differs** a parameter, here the class of numbers. State what the shared part uses about it as a `structure ... : Prop`, prove the shared part once from that bundle, and obtain each version as an instance:

```lean
namespace Demo.Variants

/-- Numbers of the first version. -/
def IsEven (n : Nat) : Prop := n % 2 = 0

/-- Numbers of the second version. -/
def DivFour (n : Nat) : Prop := n % 4 = 0

/-- What the shared development uses about its class `Good`. -/
structure Closed (Good : Nat → Prop) : Prop where
  add : ∀ a b, Good a → Good b → Good (a + b)

/-- Proved once, for every class that meets the premises. -/
theorem Closed.twice {Good : Nat → Prop} (h : Closed Good) (a b : Nat) (ha : Good a)
    (hb : Good b) : Good (a + b + (a + b)) :=
  h.add _ _ (h.add a b ha hb) (h.add a b ha hb)

theorem IsEven.closed : Closed IsEven :=
  ⟨fun a b ha hb => by unfold IsEven at *; omega⟩

theorem DivFour.closed : Closed DivFour :=
  ⟨fun a b ha hb => by unfold DivFour at *; omega⟩

-- ✅ Each version is a one-line instance.
theorem even_twice (a b : Nat) (ha : IsEven a) (hb : IsEven b) : IsEven (a + b + (a + b)) :=
  IsEven.closed.twice a b ha hb

theorem divFour_twice (a b : Nat) (ha : DivFour a) (hb : DivFour b) :
    DivFour (a + b + (a + b)) :=
  DivFour.closed.twice a b ha hb

/-- The empty class meets the premises too, so they do not show that a class has members. -/
theorem closed_false : Closed (fun _ => False) := ⟨fun _ _ h _ => h⟩

/-- Non-vacuity witness: the class has a nonzero member. -/
theorem DivFour.witness : ∃ n, n ≠ 0 ∧ DivFour n := ⟨4, by decide, rfl⟩

end Demo.Variants
```

When many theorems share the parameter and the bundle, declare both once with `variable`. A theorem receives an explicit section variable only if its header refers to it or it is `include`d (Lean `4.11.0+`). Headers mention the parameter `Good`, but usually not the bundle `h`, which only the proofs use:

```lean
namespace Demo.Section

structure Closed (Good : Nat → Prop) : Prop where
  add : ∀ a b, Good a → Good b → Good (a + b)

section
variable {Good : Nat → Prop} (h : Closed Good)

-- ❌ Fails with "Unknown identifier `h.add`": the header does not mention `h`.
theorem double (a : Nat) (ha : Good a) : Good (a + a) := h.add a a ha ha

include h

-- ✅ `include` makes `h` an argument.
theorem double' (a : Nat) (ha : Good a) : Good (a + a) := h.add a a ha ha

-- ⚠️ Added here too: "automatically included section variable(s) unused in theorem"
theorem same (a : Nat) (ha : Good a) : Good a := ha

-- ✅ Leave it out where the proof does not need it.
omit h in
theorem same' (a : Nat) (ha : Good a) : Good a := ha

end

end Demo.Section
```

In the formalization of about 175,000 modules mentioned above, part of one theory was needed a second time, for compactly supported coefficients. The base premise changed too: the second version assumes a weaker form of it, with an extra `HasCompactSupport F` assumption in one clause. Some theorems already took premises such as `VIso` and `SizeStd` as hypotheses, but each of these was stated for the first class of coefficients, and other proofs applied the concrete theorems that proved them inside their bodies. For the second version, three files write out 45 declarations ending in `Cpt`, and a command, `cpt_copy_thms`, added 21 more (18 theorems and 3 definitions). Starting from six theorems, it followed their dependencies, replaced three premise theorems by ones proved for the new class, rewrote constant names in the elaborated types and values, and added the results with `addDecl` under `set_option maxHeartbeats 0 in`.

**Rules**:

- **Check for a corollary first.** If the second claim follows from the first in a few lines, for example because only a hypothesis narrows to a smaller class (`DivFour n → IsEven n`), write the corollary. It usually does not follow when the class also appears in the conclusion, as above. A second version that rests on a weaker premise rules it out too, because theorems proved from the stronger premise do not apply.
- **Choose the parameters before the first proof** when a second version is already planned. Cover everything the versions differ in, both the data or class predicate and the premises about it. Definitions and statements that mention these take them as arguments too (`def X.Statement (Good : Nat → Prop) : Prop`).
- **Put into the bundle only what the proofs use**, one property per field. Adding a field later changes the contract of every instance (§3.3).
- **Give each instance a proof and a witness.** `theorem X.closed : Closed X` shows that the class meets the premises. A non-degenerate member (§3.8) shows that the class is not empty.
- **When the second version appears late**, turn the existing proofs into parameterized theorems, and keep the old names and headers as one-line instances. The old contracts stay unchanged, and so do the files that use them.
- **Treat the wish to copy declarations as a sign of a missing parameter.** This covers a command that re-adds declarations under rewritten names with `addDecl`, and a suffixed copy of a chain of theorems. `#duplicate_decls` compares statements, so it misses every copy whose statement changed. `scan_risky_constructs.py` lists `addDecl` commands and their uses (`lean4-cli` → `soundness_and_axiom_audit.md` §5).
- **Watch what `include` adds.** Every later theorem in the section gets the included variable, whether its proof uses it or not (§3.10). Keep such sections small, use `omit ... in`, and fail the build on `linter.unusedSectionVars` as on `linter.unusedVariables`.

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
- **Fix the order between libraries too.** The table above orders the layers of one development. When it is split into several `[[lean_lib]]` blocks, Lake lets them import each other in both directions, so state which library may import which and check it in CI with `library_dag.py --allow` (`performance_and_heartbeats.md` §4, "Keep the Imports Between Libraries One-Way").

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

Every module has a fixed cost, however short its file is. A separate `lean` process builds it and first loads its whole import closure, and Lake writes a `.setup.json` file that lists that closure. In a formalization with about 175,000 modules, these files averaged about 6 MB each (around a terabyte in total) and had to be deleted during the build.

Short theorems do not need separate modules to be checked in parallel. Since `v4.19.0` ([#7084](https://github.com/leanprover/lean4/pull/7084)), Lean elaborates the proofs of different theorems in one file in parallel. Two kinds of work still run one after another within a module (measured on Lean `v4.33.1`, `v4.35.0` and `v4.36.0`, eight declarations per file, 12 cores):

- **Elaboration of anything but a standalone theorem.** Tactic proofs of the same cost took 3–7 s of wall time as eight `theorem`s (`private` or not), and 19–27 s as eight `def`s, eight `Prop`-valued `instance`s, eight `example`s or one `mutual` block of theorems. `set_option Elab.async false` makes theorems sequential too. `lemma` behaved like `theorem` (checked on `v4.35.0` with Mathlib).
- **Kernel type checking.** The kernel checks the declarations of a module one at a time, theorems included. Eight theorems whose cost is almost all in the kernel (`by decide +kernel`) took 19–21 s, about eight times as long as one of them.

The following builds were measured with `lake build` (Lean `v4.35.0`, 12 cores that other processes were also using). The first four rows import `Mathlib.Tactic.Ring`, `Mathlib.Tactic.Positivity` and `Mathlib.Basic.Real.Basic` (964 modules in the closure); the last four use Lean core only. A `.setup.json` file lists absolute paths, so its size also depends on the length of the project path.

| Theorems and layout                       | Cold build, wall | Cold build, CPU | Rebuild after editing one theorem | `.setup.json` in total |
| :---------------------------------------- | :--------------- | :-------------- | :-------------------------------- | :--------------------- |
| 96 short, one module                      | 2.0–2.8 s        | 3.0–3.7 s       | 2.0–2.1 s                         | 1 MB                   |
| 96 short, 96 modules                      | 24–25 s          | 249–264 s       | 1.9 s                             | 97 MB                  |
| 24 slow (`ring`), one module              | 56–58 s          | 160–176 s       | 53–56 s                           | 1 MB                   |
| 24 slow (`ring`), 24 modules              | 24–28 s          | 234–238 s       | 6.3–6.7 s                         | 24 MB                  |
| 8 slow in the kernel only, one module     | 19.9–20.6 s      | 20–21 s         | Not measured                      | Not measured           |
| 8 slow in the kernel only, 8 modules      | 4.4–4.5 s        | 28–29 s         | Not measured                      | Not measured           |
| 8 slow in the elaborator only, one module | 4.4–7.1 s        | 22–24 s         | Not measured                      | Not measured           |
| 8 slow in the elaborator only, 8 modules  | 5.0–5.2 s        | 34–35 s         | Not measured                      | Not measured           |

One module per short theorem made the cold build about ten times slower. Splitting the slow `ring` theorems paid off mainly because of the kernel: checking the one-module file with `-Dprofiler=true` reported 22 s of `type checking` in a run of 41 s. To see where the time of a module goes, run:

```bash
lake lean MyProject/Foo.lean -- -Dprofiler=true -Dprofiler.threshold=100000
```

The `cumulative profiling times` at the end list `import`, `elaboration` and `type checking`. `elaboration` adds up the time of all threads, so it can exceed the wall time.

**Rules**: give a proof its own module for one of these reasons.

- **Kernel time.** `type checking` is large compared with `import` and comes from several declarations. Separate modules let the kernel check them at the same time.
- **Independent or frequent work.** A different person or agent owns the proof, or it is edited often. An edit rebuilds the whole module, including every slow proof that shares it. Without the `module` header, a change to a proof also rebuilds the modules that import it (Lake `v4.35.0`).
- **An interface boundary.** Definitions and statements that other modules import stay in files without proofs (§1), so that editing a proof does not rebuild their importers. Statements files import only what the definitions need; importing proof files from them brings back the long build chain.

Otherwise, keep it together:

- **Do not create a module only to check a short theorem in parallel.** Group closely related milestones into one statements file and, where they are proved together, one proof file.
- **State a slow proof as a theorem.** `theorem aux : C := by ...` followed by `instance : C := aux` runs the proof in its own task. Eight such pairs took under 4 s, against 22–27 s for the proofs written directly in eight `instance`s.
- **Before `v4.19.0`** the proofs of one file were not elaborated in parallel, so this advice about parallelism does not apply there.

#### Check for Small Modules

Count the modules under 25 lines, then look at what they are. The threshold only selects files to review; it is not a minimum length. For comparison, 223 of the 8,624 files of Mathlib (`v4.35.0`) were under 25 lines (2.6%), and 161 of those were `deprecated_module` files.

```bash
cd src   # the source directory of the project
# 1. Modules under 25 lines per top-level entry; their paths go to /tmp/small.txt
find . -name '*.lean' -not -path '*/.lake/*' -exec wc -l {} + |
  awk '$2 != "total" { split($2, p, "/"); n[p[2]]++
         if ($1 < 25) { s[p[2]]++; sub(/^\.\//, "", $2); print $2 > "/tmp/small.txt" } }
       END { for (d in n) printf "%s: %d of %d (%.1f%%)\n", d, s[d], n[d], 100 * s[d] / n[d] }'
# 2. How many of them are catch-all glue (§3.9)
tr '\n' '\0' < /tmp/small.txt | xargs -0 grep -lE 'first +\| +\(?exact @' | wc -l
# 3. Small modules with exactly one importer
grep -rE --include='*.lean' --exclude-dir=.lake '^(public +)?(meta +)?import +' . |
  LC_ALL=C sort -u | awk '{ print $NF }' | LC_ALL=C sort | uniq -c |
  awk '$1 == 1 { print $2 }' > /tmp/one-importer.txt
sed 's/\.lean$//; s|/|.|g' /tmp/small.txt | LC_ALL=C sort |
  LC_ALL=C comm -12 - /tmp/one-importer.txt
```

In the formalization of about 175,000 modules, 55,396 of 175,188 modules (31.6%) were under 25 lines, and 35.8% of the modules in its largest library. Step 2 found the catch-all `first` of §3.9 in 44,280 of them (80%), so most small files there called for removing glue rather than for merging theorems.

- **Remove glue first** (§3.9).
- **Review the single-importer modules** that step 3 prints. Move each into its importer or into a neighboring proof file unless one of the three reasons above applies.
- **Leave small interface files** (definitions and statements that several modules share) as they are.

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

### 3.9. Do Not Bridge Proofs and Contracts with Catch-All Tactics

When a proof ends up under a different name or a slightly different signature than its contract, it is tempting to connect the two with a generic tactic that tries several forms:

```lean
theorem contract_name : <contract type> := by
  first | exact @proof_name | exact proof_name | (intros; apply proof_name <;> assumption)
```

The type in the header still fixes what is proved, so this is sound. But it hides how the proof differs from the contract:

```lean
theorem double_pos (n : Nat) (h : 0 < n) : 0 < 2 * n := by omega

-- ❌ Compiles: the third branch drops the premise `n ≠ 5` without a trace.
theorem pos_glue : ∀ n : Nat, 0 < n → n ≠ 5 → 0 < 2 * n := by
  first
    | exact @double_pos
    | exact double_pos
    | (intros; apply double_pos <;> assumption)

-- A direct term shows the difference:
-- "Type mismatch: double_pos has type ∀ (n : Nat), 0 < n → 0 < 2 * n
--  but is expected to have type ∀ (n : Nat), 0 < n → n ≠ 5 → 0 < 2 * n"
theorem pos_direct : ∀ n : Nat, 0 < n → n ≠ 5 → 0 < 2 * n := @double_pos

-- ❌ When every branch fails, only the last branch's error is reported:
-- "Tactic `apply` failed: could not unify the conclusion of `double_pos`"
theorem neg_glue : ∀ n : Nat, 0 < 3 * n := by
  first
    | exact @double_pos
    | exact double_pos
    | (intros; apply double_pos <;> assumption)
```

```lean
def Pos.Statement : Prop := ∀ n : Nat, 0 < n → 0 < 2 * n
def PosNe.Statement : Prop := ∀ n : Nat, 0 < n → n ≠ 5 → 0 < 2 * n

-- ✅ Same type: a term is checked once, and a mismatch prints both types.
theorem Pos.proof : Pos.Statement := double_pos

-- ✅ Different type: write the adaptation out, so the dropped premise is visible as `_`.
theorem PosNe.proof : PosNe.Statement := fun n h _ => double_pos n h
```

If the unused premise is given a name (`fun n h hne => ...`), `linter.unusedVariables` warns about it. Note also that `intros` does not unfold `def X.Statement`, while `intro n h` does, so the third branch does nothing useful against a statement-first contract.

The formalization of about 175,000 modules mentioned above did this on a large scale. It had 46,610 files named `...Statement.lean`, about a quarter of all its modules, and 44,387 of them contained exactly this three-branch `first`. 45,641 of them raised `maxHeartbeats`. In a sample of 932, 915 imported the proof file of the same name, so the "statement" files depended on proofs and separated nothing in the build. In four files checked by hand, the contract type matched the proof's type up to binder names: the glue was only a rename, at the cost of one extra module and one extra name per theorem.

**Rules**:

- **Prefer no glue.** Write the proof under the contract's name and type (`theorem X.proof : X.Statement := by ...`).
- **For a rename, use a term.** When an existing lemma already proves the contract, write `theorem X.proof : X.Statement := Y`. It is checked once, and a mismatch is reported with both types.
- **For a real difference, write the adaptation out.** Name dropped premises `_`, and pass arguments explicitly (`fun n h _ => Y n h`). A premise that the proof does not need is a point for the contract review: either the contract is weaker than it could be, or the planned argument was expected to need it (§3.3).
- **Collapse generated glue before merging.** If an agent produces `first | ... | ...` glue while signatures are still moving, replace each one with the single alternative that works, starting with the plain term. Treat any case that needs the `intros; apply ... <;> assumption` branch as a contract mismatch to review.
- **Keep any remaining glue in the proof file.** A separate glue module that imports the proof adds a module and a second name, and decouples nothing.

### 3.10. Unused Hypotheses Misreport Dependencies

The type of a conditional proof is where reviewers read what a result depends on (§3.1). The type lists what the proof may use, not what it does use. When the proof ignores a hypothesis, the result is stronger than its type says, and the dependency list is wrong: the result is reported as open on a statement or citation it does not need, and a bundle of cited results (§1, "Citing Published Results as Statements") looks as if more work were left than there is.

```lean
namespace Demo.Unused

/-- A cited result that the development still relies on. -/
def Published.AddComm : Prop := ∀ a b : Nat, a + b = b + a

structure Literature : Prop where
  addComm : Published.AddComm

def AddZero.Statement : Prop := ∀ n : Nat, n + 0 = n

-- ❌ The type says "conditional on the literature"; the proof is unconditional.
theorem AddZero.of_literature (L : Literature) : AddZero.Statement := by
  intro n
  rfl

end Demo.Unused
```

The `linter.unusedVariables` linter reports this case (``Variable name `L` is not explicitly referenced``), but it sees only some of the ways to write the same proof. The `#unused_hypotheses` command from `lean4-cli` (`scripts/unused_hypotheses.lean`) checks the elaborated proof term instead. Measured on Lean `v4.33.1` and `v4.35.0`:

| How the unused hypothesis is written                      | `linter.unusedVariables` | `#unused_hypotheses` |
| :-------------------------------------------------------- | :----------------------- | :------------------- |
| `(L : Literature)` in the signature, term or tactic proof | Warns                    | Reports              |
| `Literature → X := fun L => ...`                          | Warns                    | Reports              |
| `Literature → X := by intro L ...`                        | **Silent**               | Reports              |
| `fun _ => ...` or `(_L : Literature)`                     | **Silent**               | Reports              |
| `have h := L.addComm` with `h` never used                 | Silent                   | Silent               |

The `intro` form is the usual way to start a proof of `A.Statement → B.Statement`, so the linter alone misses most cases in a statement-first development.

In the formalization of about 175,000 modules mentioned above, 195 theorems in one file took the bundle of open cited results as an argument `O`, and 152 of them never used it: their proofs referred to closed theorems instead. Their names (`..._of_literature`) and types reported a dependency on the literature that did not exist. The project also set `linter.unusedVariables false` in 503 files.

**The fix is to delete the hypothesis**, not to silence the warning:

```lean
-- ✅ The type now says what the proof shows: the result is unconditional.
theorem AddZero.proof : AddZero.Statement := by
  intro n
  rfl
```

Callers stop passing the argument, and the assembly shows one prerequisite fewer. If the plan expected the argument to use the hypothesis, treat the short proof with suspicion before deleting anything: check that the statement still says what was intended (§3.2) and is not vacuous (§3.8).

**Rules**:

- **Never silence an unused statement hypothesis.** Do not rename it to `_L` or `_`, and do not set `linter.unusedVariables false` in proof files. Each of these hides the misreported dependency instead of removing it.
- **Run the semantic check.** Run `#unused_hypotheses` on the project namespace before reporting progress, and in CI:

  ```bash
  { echo "import MyProject.Main"; cat <skills-path>/lean4-cli/scripts/unused_hypotheses.lean
    echo "#unused_hypotheses MyProject"; } | lake env lean --stdin
  ```

- **Fail the build on the linter in proof files.** `parse_diagnostics.py` from `lean4-cli` counts warnings per linter and can turn one linter into a failure for some paths only:

  ```bash
  lake build 2>&1 | python3 <skills-path>/lean4-cli/scripts/parse_diagnostics.py --summary-only \
    --fail-on-linter linter.unusedVariables --fail-path-prefix MyProject/Proofs
  ```

  Lake prints the stored warnings of modules that are already up to date again (`⚠ [2/4] Replayed ...`, Lake `v4.35.0`), so this check also works on an incremental build.

- **Count the overrides.** The option census of `scan_risky_constructs.py` lists every `set_option linter.unusedVariables false` with its number of files. In a statement-first development the count for proof files should be zero.
- **A hypothesis passed on counts as used.** `#unused_hypotheses` cannot see that `core L := other L` depends on `L` only through `other`; it reports `other` if `other` ignores it. Run it on every theorem along the chain, not only on the assembly.

### 3.11. Measure the Longest Import Chain

Lake builds a module only after every module it imports is built. The modules on the longest chain of imports are therefore built one after another, however many cores the machine has, and each of them first loads its whole import closure. The length of that chain costs time in two ways:

- **Cold builds.** With equal module times, a build can keep busy on average at most as many cores as the **parallelism**, the number of modules divided by the chain length. On a machine with more cores than that, the chain, not the core count, sets the build time.
- **Rebuilds after an edit.** Editing a module near the start of the chain rebuilds every module after it on the chain, in sequence, before the assembly theorem can be checked again.

Statement-first decomposition is meant to keep the chain short. Proofs import only statements and definitions (§1), so a chain contains the definitions, statements and cited results a proof needs, at most one proof, and the assembly. Every proof file that imports another proof file adds a step, so a chain that keeps growing with the number of proofs shows that proofs import proofs, whatever the directories are called.

`import_depth.py` from `lean4-cli` reads the `import` lines of every source file (no build needed), prints the longest chain module by module, and fails with exit code `1` when the chain is longer than `--max-depth`:

```bash
python3 <skills-path>/lean4-cli/scripts/import_depth.py . --to MyProject.Main --max-depth 12
```

The argument is the source directory (the package's `srcDir`), and `--to` limits the measurement to the import closure of the assembly. Only the project's own modules are counted; Mathlib comes from the cache.

In the formalization of about 175,000 modules mentioned above, the longest chain had 203 modules, from a module in `ReciprocityTheory` to `Main`. 150 of its 202 imports went from a file in a `Proofs` directory to another such file. 63 of its modules were `...Statement` glue modules (§3.9) that imported the proof of the same name, so each one added a step and separated nothing; without them the chain would still have had 141 modules. The chain did not limit a cold build there: with 175,188 modules the parallelism was 863, far more than any build machine has cores. It did limit rebuilds: an edit near the start of the chain had to pass through about 200 modules in sequence before `Main` could be checked again. For comparison, the import closure of `Mathlib` (`v4.35.0`) has 8,625 modules, a longest chain of 177 and a parallelism of about 49, so a long chain is not a defect in itself. Compare it with what the layers allow.

**Rules**:

- **Measure the chain from the first proof file, and cap it in CI.** Start `--max-depth` at the current length, or at the length the layers allow (definitions, statements, one proof, assembly), and lower it as the structure improves. Raising it is a design change to review, like adding a hypothesis (§3.3).
- **Cut the chain where a proof imports a proof.** Read the chain the script prints. Each step from one proof file to another is an import to remove: move the shared lemma down to `Definitions` if it is basic API, or make it a milestone with its own `X.Statement` (§1, "Layered Directories for Larger Developments").
- **Do not count glue modules as separation.** A statement module that imports its own proof adds a step to every chain through it (§3.9).
- **Check the parallelism against the build machine.** If the number of modules divided by the chain length is below the number of cores, shortening the chain shortens every cold build.

### 3.12. Keep the Assembly's Imports to What the Theorems Use

A corollary, a special case or an extra check that no top-level theorem uses does not need to be imported by `Main.lean`, directly or through another module. Moving it out saves less than it seems, because the checks differ in what they read:

| An unused module in the import closure of `Main`   | Effect                                                                            |
| :------------------------------------------------- | :-------------------------------------------------------------------------------- |
| `lake build Main`                                  | Builds it and its imports too, and fails if it fails                              |
| `lake comparator`, or `leanexport Main -- <names>` | The export is byte-identical. The exporter loads the module (memory and time)     |
| Kernels judging that export                        | None, since they read the same file                                               |
| `lake env leanchecker --fresh Main`                | Replays its declarations too                                                      |
| `lake check`                                       | Moving it out changes nothing while a default target still includes or imports it |

`lean4-cli` → `soundness_and_axiom_audit.md` §8 lists what each command checks, with measurements.

**Rules**:

- **Treat a result that must be judged as a top-level theorem.** Keep it in the import closure of the solution module, and name it in the challenge file and in `theorem_names`. Comparator exports only what `theorem_names` and `definition_names` list, the permitted axioms and the kernel's primitives, with their dependencies, so a theorem that `Main` merely imports is not judged.
- **Move the other results that no top-level theorem uses to a library of their own.** List it in `defaultTargets` so that every build checks it (as for witnesses, §3.8), and do not import it from `Main`.
- **Do not expect a smaller export from moving files.** The size of a targeted export, and the kernel time of the judging run, follow from the declarations that the named theorems depend on.
- **Measure before restructuring.** Compare the closure of `Main` with the closure of the statements and of the modules that declare what its theorems use:

  ```bash
  python3 <skills-path>/lean4-cli/scripts/import_depth.py src --to Main | grep '^Modules'
  python3 <skills-path>/lean4-cli/scripts/import_depth.py src --to Statements --to MyProject.MainTheorems | grep '^Modules'
  ```

In the formalization of about 175,000 modules mentioned above, `Main` imported, through two import-only files, four modules of further results that none of its theorems used. Without them the closure of `Main` would have had 175,181 modules instead of 175,187.

### 3.13. Import the Modules You Use, Not an Aggregate

An **aggregate** (umbrella or barrel) module holds only `import` lines. The file itself adds one module to a closure. What costs is that each importer gets everything behind it, including the parts it does not use. Measured with Lake from Lean `v4.33.1`, `v4.35.0` and `v4.36.0`, where `Hub` imports `A` and `B` (with `public import` in the variant with `module` headers):

| Change                                                          | Imports `Hub`, uses `A` | Imports `A` | Imports `Hub`, uses `A` and `B` | Imports `A` and `B` |
| :-------------------------------------------------------------- | :---------------------- | :---------- | :------------------------------ | :------------------ |
| Proof edited in `B`, no `module` header                         | Rebuilt                 | Not rebuilt | Rebuilt                         | Rebuilt             |
| Proof edited in `B`, `module` header, public `.olean` unchanged | Not rebuilt             | Not rebuilt | Not rebuilt                     | Not rebuilt         |
| Public theorem added to `B`                                     | Rebuilt                 | Not rebuilt | Rebuilt                         | Rebuilt             |
| Import added to `Hub`                                           | Rebuilt                 | Not rebuilt | Rebuilt                         | Not rebuilt         |
| Project modules listed in the importer's `.setup.json`          | `A`, `B`, `Hub`         | `A`         | `A`, `B`, `Hub`                 | `A`, `B`            |

With a `module` header, a proof edit that changes the public `.olean` still rebuilds the importers; replacing the test proof with `by simp [B.val]` did.

Replacing an aggregate import with imports of all its members therefore gains next to nothing. The gain comes from leaving out the members that a file does not use.

**Rules**:

- **Inside the project, import the modules that declare what the file uses.**
- **Keep an aggregate only as an entry point for users of the library**, such as the root file of a library, and let no module of the project import it. For comparison, Mathlib's header linter (`v4.35.0`) reports a Mathlib file that imports all of `Mathlib.Tactic`, `Std` or `Batteries`.
- **With `module` headers, let `lake shake` narrow the imports.** In the module that used only `A`, `lake shake --fix` replaced the import of `Hub` with an import of `A` (checked on `v4.33.1`, `v4.35.0` and `v4.36.0`). It also proposes removing the imports of the aggregate itself, which declares nothing, so write the first line of an aggregate you keep as `module -- shake: keep-all`. If any loaded module lacks the header, it stops with ``lake shake` only works with `module`s currently``, and the imports have to be narrowed by hand. Run `lake build` afterwards.
- **Find the aggregates that project modules import.** The command prints each one with the number of `import` lines that name it:

  ```bash
  cd src   # the source directory of the project
  # 1. Modules that hold only import lines (a file with a block comment is not listed)
  find . -name '*.lean' -not -path '*/.lake/*' -exec awk '
    FNR == 1 { if (n && !other) print f; f = FILENAME; n = other = 0 }
    /^(public +)?(meta +)?import / { n++; next }
    !/^((module|prelude)([[:space:]]|$)|[[:space:]]*(--|$))/ { other = 1 }
    END { if (n && !other) print f }' {} + |
    sed 's|^\./||; s/\.lean$//; s|/|.|g' | LC_ALL=C sort > /tmp/aggregates.txt
  # 2. How often the project imports each of them
  grep -rhE --include='*.lean' --exclude-dir=.lake '^(public +)?(meta +)?import +' . |
    sed 's/ *--.*//' | awk '{ print $NF }' | LC_ALL=C sort | uniq -c |
    awk 'NR == FNR { agg[$1] = 1; next } $2 in agg' /tmp/aggregates.txt - | sort -rn
  ```

  Start with the aggregates that have both many imports and many importers. An aggregate with a single import adds only itself to a closure.

In the formalization of about 175,000 modules, 150 of 175,188 modules held only imports (0.09%). 54 of them had a single import, among them the most imported one, with 2,242 importers.

---

## 4. Checklist

- [ ] Does every milestone have a `def X.Statement : Prop` with a docstring, in a file that contains no proofs?
- [ ] Does each `X.proof` take as hypotheses only the prerequisite statements listed in the plan?
- [ ] Do proof files import statements files only, never other proof files?
- [ ] In a layered layout, does CI check that `Definitions`, `Statements` and `Published` never import `Proofs`, and that nothing imports `Witnesses`?
- [ ] If the project has several `[[lean_lib]]` blocks, does CI check the imports between them against a list of allowed imports with `library_dag.py --allow`?
- [ ] Does CI measure the longest import chain with `import_depth.py` and fail when it exceeds the set `--max-depth`?
- [ ] Does each separate proof module have a reason (kernel time, independent or frequent work, an interface boundary), with no module added only to check a short theorem in parallel, and have the modules under 25 lines been reviewed (§3.6)?
- [ ] Does `Main` import only what the top-level theorems use, with other results in a library of their own that a default target builds (§3.12)?
- [ ] Do project modules import the modules they use rather than import-only aggregates (§3.13)?
- [ ] Has each statement been sanity-checked against boundary values before others build on it?
- [ ] Does every premise bundle that statements quantify over have a non-degenerate `X.witness : ∃ x, Premises x` that a default build target compiles?
- [ ] Is every proof connected to its contract by its own header, a plain term, or an explicit adaptation, with no catch-all `first | exact ... | apply ...` glue left?
- [ ] Does `#unused_hypotheses` report no unused statement hypotheses, with no `_`-renamed hypotheses and no `set_option linter.unusedVariables false` in proof files?
- [ ] Is the novel argument stated as one core statement in a Mathlib-only statements file, with each top-level claim derived from it by a short reduction that uses only library lemmas?
- [ ] Is each cited published result a `def Published.X : Prop` with a citation and a satisfiability `example`, collected in a `structure ... : Prop` bundle with descriptive field names, and does the top-level theorem either discharge the bundle or show it in its type?
- [ ] Does `#duplicate_fields` report no two fields of a bundle with the same proposition?
- [ ] Where a development serves several versions, is the shared part proved once over a parameter and a `structure ... : Prop` of premises, with a proof and a witness for each instance, and no copied chain of declarations (`addDecl` command or suffixed copies)?
- [ ] Is there an assembly theorem whose `#check @...` shows no remaining statement hypotheses?
- [ ] Was `#print axioms` run on the assembly theorem, not on conditional `X.proof` declarations?
- [ ] Does every `X.proof` header give explicit universe arguments (`.{0}`, `.{u}`) to each universe-polymorphic statement it mentions?
- [ ] If the result goes to Comparator, does `Statements.lean` import only Mathlib, match the definitions in `Challenge.lean` exactly, and does `Main.lean` contain only one-line references to assembly theorems?
