# Lean 4 Skills

English | [日本語](README.md)

A suite of skills designed for AI coding agents to autonomously perform formal mathematical proving in Lean 4 and Mathlib (theorem proving, proof search, and error repair).

## Features

- **Specialized in Formal Proofs**: Focused on theorem proving, Mathlib lemma discovery, and compiler error diagnostics rather than general-purpose programming.
- **Lean LSP Interaction Loop**: Queries `lean --server` via Language Server Protocol (LSP) to inspect proof goals (Tactic State) step-by-step.
- **Zero External Dependencies**: All bundled scripts rely exclusively on the Python 3 standard library (`subprocess`, `json`, `urllib`). No third-party packages required.

## Prerequisites & Compatibility

| Component         | Target / Supported          | Verified / Tested Version             | Notes                                                                   |
| :---------------- | :-------------------------- | :------------------------------------ | :---------------------------------------------------------------------- |
| **Lean 4 / Lake** | `^4.14.0` (4.14.0+)         | `v4.35.0` (Release, commit `eb6cafb`) | Installation via [elan](https://github.com/leanprover/elan) recommended |
| **Mathlib**       | Compatible with target Lean | Contemporary with Lean `v4.35.0`      | Uses modular domain imports and modern syntax                           |
| **Python**        | `>=3.10`                    | `3.14.7`                              | Standard library only (required for script-bundled skills)              |

## Skills Overview

| Skill                                                       | Description                                                                       | Bundled Scripts / References                 |
| :---------------------------------------------------------- | :-------------------------------------------------------------------------------- | :------------------------------------------- |
| [`lean4-interactive-proof`](skills/lean4-interactive-proof) | Interacts with `lean --server` to fetch Tactic State (goals) at a target position | `scripts/lean_goal.py`                       |
| [`lean4-proof-repair`](skills/lean4-proof-repair)           | Diagnoses and repairs common compiler errors (type mismatch, timeouts, etc.)      | `references/*.md` (7 diagnostic guides)      |
| [`lean4-syntax`](skills/lean4-syntax)                       | Fast syntax checking and proof syntax reference (prevents Lean 3 contamination)   | `scripts/check_syntax.py`, `references/*.md` |
| [`lean4-cli`](skills/lean4-cli)                             | Automates `lake`/`lean` commands and parses build logs into structured JSON       | `scripts/parse_diagnostics.py`               |
| [`lean4-best-practice`](skills/lean4-best-practice)         | Top-down proof workflow (sorry-driven), `simp` discipline, and naming rules       | `references/*.md` (6 practice guides)        |
| [`lean4-mathlib-search`](skills/lean4-mathlib-search)       | Searches Mathlib lemmas via Loogle (type signature) and inline search tactics     | `scripts/search_loogle.py`                   |
| [`lean4-mathlib-use`](skills/lean4-mathlib-use)             | Minimal imports, typeclass hierarchy guidance, junk values, and classical logic   | `references/*.md` (4 usage guides)           |

## Installation

Download the latest `lean4-skills.zip` from [Releases](https://github.com/MI-1222/lean4-skills/releases), and extract it into your project or agent workspace's `skills/` directory:

Each skill folder (`skills/<skill-name>/`) contains a standardized agent specification file (`SKILL.md`).

## Directory Structure

```text
skills/
├── lean4-interactive-proof/  # Interactive goal inspection via LSP
├── lean4-proof-repair/       # Error triage and fix prescriptions
├── lean4-syntax/             # Syntax checker and proof conventions
├── lean4-cli/                # Build commands and diagnostic parser
├── lean4-best-practice/      # Proving methodology and simp hygiene
├── lean4-mathlib-search/     # Loogle theorem search
└── lean4-mathlib-use/        # Mathlib usage and import guidelines
```

## License

[MIT License](LICENSE)
