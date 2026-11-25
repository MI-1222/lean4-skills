import Lean

/-!
# `#duplicate_fields`

Reports fields of a `structure ... : Prop` bundle whose types are the same proposition.

A bundle of cited results lists what a development still relies on, one field per result. Two
fields with the same type cite one proposition under two names: at least one of them does not
state the result its name refers to, and the bundle looks longer than it is. The command compares
every pair of fields, after expanding fields whose types are themselves `Prop` bundles, and reports
pairs that are syntactically identical or definitionally equal after unfolding definitions.

Usage, from the project root (prepend the imports that bring the bundle into scope):

```bash
{ echo "import MyProject.Main"; cat duplicate_fields.lean; echo "#duplicate_fields MyProject.Literature"; } \
  | lake env lean --stdin
```

`#duplicate_fields A B` checks the bundles `A` and `B` separately. Each duplicate pair is a
warning, and a final info message gives the totals.

Limits:
- Only equal propositions are reported. A field that merely implies another is not.
- Fields of type `A ∧ B` or `A ↔ B` are compared as a whole.
- Definitional equality is checked at default transparency, so it can be slow for very large
  statements, and it does not see through theorems or irreducible definitions.
-/

open Lean Meta Elab Command

namespace DuplicateFields

/-- Logical connectives that are structures in core but are compared as a whole, not expanded. -/
def connectives : List Name := [``And, ``Iff]

/-- Returns the leaf fields of a bundle type as `(path, type)` pairs. A field whose type is itself
a `Prop`-valued structure (other than `∧` and `↔`) is expanded into its fields, with the path
joined by `.`. Parent structures from `extends` are expanded the same way. -/
partial def leafFields (path : String) (type : Expr) : MetaM (Array (String × Expr)) := do
  let type ← instantiateMVars type
  let env ← getEnv
  let .const structName _ := type.getAppFn | return #[(path, type)]
  unless isStructure env structName && !connectives.contains structName do
    return #[(path, type)]
  unless ← isProp type do return #[(path, type)]
  let ctor := getStructureCtor env structName
  let ctorType ← instantiateForall (ctor.type.instantiateLevelParams ctor.levelParams
    type.getAppFn.constLevels!) type.getAppArgs
  let (fields, _, _) ← forallMetaTelescope ctorType
  let fieldNames := getStructureFields env structName
  let mut result := #[]
  for i in [0:fields.size] do
    let name := (fieldNames[i]?.map toString).getD s!"field{i + 1}"
    let fieldPath := if path.isEmpty then name else s!"{path}.{name}"
    result := result ++ (← leafFields fieldPath (← inferType fields[i]!))
  return result

/-- Returns `(path₁, path₂, identical?)` for every pair of leaf fields whose types are the same
proposition: syntactically identical, or definitionally equal at default transparency. -/
def duplicatesOf (bundle : Name) : MetaM (Array (String × String × Bool)) := do
  let info ← getConstInfo bundle
  forallTelescope info.type fun params _ => do
    let bundleType := mkAppN (.const bundle (info.levelParams.map Level.param)) params
    unless ← isProp bundleType do throwError "`{bundle}` is not a `structure ... : Prop`"
    let leaves ← leafFields "" bundleType
    let mut result := #[]
    for i in [0:leaves.size] do
      for j in [i + 1:leaves.size] do
        let (pathI, typeI) := leaves[i]!
        let (pathJ, typeJ) := leaves[j]!
        if typeI == typeJ then
          result := result.push (pathI, pathJ, true)
        -- A fresh metavariable context keeps the check from assigning anything.
        else if ← withNewMCtxDepth (withTransparency .default (isDefEq typeI typeJ)) then
          result := result.push (pathI, pathJ, false)
    return result

/-- `#duplicate_fields S₁ S₂ ...` checks each `Prop` bundle for fields with the same type. -/
syntax (name := duplicateFieldsCmd) "#duplicate_fields" (ppSpace ident)+ : command

@[command_elab duplicateFieldsCmd]
def elabDuplicateFields : CommandElab := fun stx => do
  let mut pairs : Nat := 0
  let names := stx[1].getArgs
  for nameStx in names do
    let bundle ← liftCoreM <| realizeGlobalConstNoOverloadWithInfo nameStx
    let duplicates ← liftTermElabM (duplicatesOf bundle)
    for (pathI, pathJ, identical) in duplicates do
      pairs := pairs + 1
      let how := if identical then "the same type" else "definitionally equal types"
      logWarning m!"`{bundle}`: fields `{pathI}` and `{pathJ}` have {how}"
  logInfo m!"#duplicate_fields: {names.size} bundle(s) checked, {pairs} duplicate pair(s)"

end DuplicateFields
