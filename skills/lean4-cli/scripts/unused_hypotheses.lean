import Lean

/-!
# `#unused_hypotheses`

Reports the explicit `Prop` hypotheses of theorems that the proof term never uses.

A theorem such as `theorem core (L : Literature) : Core.Statement` claims to depend on `L`.
If the proof does not use `L`, the type misreports the dependencies of the result. The
`linter.unusedVariables` linter catches this only when the hypothesis is a named binder in the
signature or in a `fun`; it misses `by intro L ...`, `fun _ => ...` and `_L`. This command checks
the elaborated proof term instead, so the way the proof was written does not matter.

Usage, from the project root (prepend the imports that bring the theorems into scope):

```bash
{ echo "import MyProject.Main"; cat unused_hypotheses.lean; echo "#unused_hypotheses MyProject"; } \
  | lake env lean --stdin
```

`#unused_hypotheses A B.c` checks every theorem whose name starts with `A` or `B.c` (a full
theorem name checks that theorem). Private theorems are included under their user-facing names.
Each finding is a warning, and a final info message gives the totals.

Limits:
- Only explicit binders whose type is a `Prop` are checked. A hypothesis that a later binder or the
  conclusion mentions is part of the statement and is not reported.
- A hypothesis that the proof mentions without needing it (for example `have h := L.a` with `h`
  unused) counts as used.
- A proof that passes the hypothesis on (`core L := other L`) counts as using it. Check `other` too.
-/

open Lean Meta Elab Command

namespace UnusedHypotheses

/-- Substitutes `args` for the leading binders of `e`, looking through metadata, and applies the
rest. The result is the proof body with the hypotheses as free variables. -/
partial def applyArgs (e : Expr) : List Expr → Expr
  | [] => e
  | arg :: rest =>
    match e.consumeMData with
    | .lam _ _ body _ => applyArgs (body.instantiate1 arg) rest
    | other => mkAppN other (arg :: rest).toArray

/-- Returns `(position, binder name, pretty-printed type)` for every explicit `Prop` hypothesis of
the theorem that the proof term does not use. Positions start at 1. -/
def unusedOf (info : TheoremVal) : MetaM (Array (Nat × Name × String)) :=
  forallTelescope info.type fun xs conclusion => do
    let body := applyArgs info.value xs.toList
    let mut result := #[]
    for i in [0:xs.size] do
      let x := xs[i]!
      let decl ← x.fvarId!.getDecl
      unless decl.binderInfo.isExplicit do continue
      unless ← isProp decl.type do continue
      let id := x.fvarId!
      let laterTypes ← (xs.extract (i + 1) xs.size).mapM inferType
      if body.containsFVar id || conclusion.containsFVar id ||
          laterTypes.any (·.containsFVar id) then
        continue
      let type := toString (← ppExpr decl.type)
      -- Binders written as `_` or as an arrow carry hygienic names; print them as `_`.
      let name := if decl.userName.hasMacroScopes then `_ else decl.userName
      result := result.push (i + 1, name, type)
    return result

/-- `#unused_hypotheses P₁ P₂ ...` checks every theorem whose name has one of the given prefixes. -/
syntax (name := unusedHypothesesCmd) "#unused_hypotheses" (ppSpace ident)+ : command

@[command_elab unusedHypothesesCmd]
def elabUnusedHypotheses : CommandElab := fun stx => do
  let prefixes := stx[1].getArgs.map (·.getId)
  let env ← getEnv
  let mut theorems : Array TheoremVal := #[]
  for (name, info) in env.constants.toList do
    if let .thmInfo val := info then
      -- Private names start with an internal `_private` component; compare the user-facing name.
      let userName := privateToUserName name
      if !userName.isInternal && prefixes.any (·.isPrefixOf userName) then
        theorems := theorems.push val
  theorems := theorems.qsort fun a b => (privateToUserName a.name).lt (privateToUserName b.name)
  let mut flagged : Nat := 0
  for val in theorems do
    let unused ← liftTermElabM (unusedOf val)
    unless unused.isEmpty do
      flagged := flagged + 1
      let items := unused.toList.map fun (pos, name, type) => s!"#{pos} ({name} : {type})"
      logWarning m!"`{privateToUserName val.name}` does not use hypothesis {", ".intercalate items}"
  logInfo m!"#unused_hypotheses: {theorems.size} theorem(s) checked, {flagged} with unused hypotheses"

end UnusedHypotheses
