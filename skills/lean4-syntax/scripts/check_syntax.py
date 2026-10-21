#!/usr/bin/env python3
"""
Fast syntax and elaboration checker for Lean 4 code snippets and files.

Supports:
1. Static Lean 3 deprecation linting (detecting obsolete syntax like `begin ... end`,
   trailing commas, `<-`, deprecated `calc` colons, etc.).
2. Real-time compiler diagnostics via `lake env lean --json` on temporary files or
   existing Lean files.

Zero external dependencies: uses only Python standard library.
"""

import argparse
import dataclasses
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


@dataclasses.dataclass
class Diagnostic:
    severity: str  # "error", "warning", "info"
    line: int
    column: int
    message: str
    source: str  # "lean-compiler" or "lean3-linter"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "source": self.source,
        }


@dataclasses.dataclass
class CheckResult:
    is_valid: bool
    has_warnings: bool
    diagnostics: List[Diagnostic]
    raw_output: str
    checked_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "has_warnings": self.has_warnings,
            "checked_path": self.checked_path,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "raw_output": self.raw_output,
        }


class Lean3Linter:
    """Detects legacy Lean 3 patterns frequently hallucinated by LLMs."""

    # Patterns to detect Lean 3 syntax
    RULES: List[Tuple[str, re.Pattern, str, str]] = [
        (
            "LEAN3_BEGIN_END",
            re.compile(r"\bbegin\b"),
            "error",
            "Found 'begin' block. Lean 4 uses 'by' for tactic mode, not 'begin ... end'.",
        ),
        (
            "LEAN3_TRAILING_COMMA",
            re.compile(
                r"^\s*(?:[·•\-]\s*)?(?:intro|intros|exact|apply|refine|rw|simp|dsimp|ring|omega|aesop|linarith|nlinarith|positivity|gcongr|rcases|obtain|cases|split|rfl|constructor|left|right|ext|norm_num|assumption|contradiction|subst|revert|clear)\b.*,\s*(?:--.*)?$"
            ),
            "error",
            "Found trailing comma at end of tactic line. Lean 4 separates tactics by newline or semicolon ';', never trailing commas.",
        ),
        (
            "LEAN3_ASCII_REWRITE_ARROW",
            re.compile(r"\b(?:rw|simp_rw|simp|dsimp)\s*\[[^\]]*<-\s*"),
            "warning",
            "Found '<-' inside rewrite tactic. Lean 4 uses Unicode left arrow '←' (\\l).",
        ),
        (
            "LEAN3_CALC_COLON",
            re.compile(
                r"^(?!\s*(?:theorem|lemma|def|instance|axiom|variable|have|let)\b)"
                r"\s*(?:calc\s+)?(?:_|.+?)\s*[=<≤≥>~≃≈]\s*.*?(?<!:):(?!=)\s*(?:by|proof|\{|_|[a-zA-Z0-9_]+)\b"
            ),
            "error",
            "Found ':' before proof in 'calc' step. Lean 4 uses ':=' instead of ':'.",
        ),
        (
            "LEAN3_HAVE_FROM",
            re.compile(r"\bhave\s+[^:]+:[^:]+,\s*from\b"),
            "error",
            "Found 'have ..., from'. Lean 4 uses 'have ... := ...' without 'from' and without comma.",
        ),
        (
            "LEAN3_SUFFICES_FROM",
            re.compile(r"\bsuffices\s+[^:]+:[^:]+,\s*from\b"),
            "error",
            "Found 'suffices ..., from'. Lean 4 uses 'suffices ... := ...' or 'suffices ... by ...' without 'from' and without comma.",
        ),
        (
            "LEAN3_OPEN_LOCALE",
            re.compile(r"^\s*open_locale\b"),
            "error",
            "Found 'open_locale'. Lean 4 uses 'open scoped <Namespace>' (e.g. 'open scoped Classical').",
        ),
        (
            "LEAN3_UNIVERSES_PLURAL",
            re.compile(r"^\s*universes\b"),
            "error",
            "Found 'universes' (plural). Lean 4 uses 'universe' (singular) or 'variable {u v : Level}'.",
        ),
        (
            "LEAN3_INDUCTION_WITH_VARS",
            re.compile(r"\binduction\s+\S+\s+with\s+(?!\|\s*)[a-zA-Z0-9_]+\s+[a-zA-Z0-9_]+"),
            "warning",
            "Found 'induction ... with <var1> <var2>'. Lean 4 pattern-matches induction cases with 'with | zero => ... | succ n ih => ...' or binds them via subsequent 'intro'.",
        ),
        (
            "LEAN3_CASES_WITH_VARS",
            re.compile(r"^\s*(?:[·•\-]\s*)?cases\s+\S+\s+with\s+(?!\|\s*)[a-zA-Z0-9_]+\s+[a-zA-Z0-9_]+"),
            "warning",
            "Found 'cases ... with <var1> <var2>'. Lean 4 uses 'rcases ... with ⟨...⟩', 'obtain', or pattern matching with 'with | ... => ...'.",
        ),
        (
            "LEAN3_SPLIT_CONJUNCTION",
            re.compile(r"^\s*(?:[·•\-]\s*)?split\b\s*,?\s*(?:--.*)?$"),
            "warning",
            "Found bare 'split' tactic without an enclosing 'if' or 'match'. In Lean 4, 'split' decomposes 'if-then-else' and 'match' statements; to split a conjunction (P ∧ Q) or constructor target, use 'constructor' or 'refine ⟨?_, ?_⟩'.",
        ),
        (
            "LEAN3_BRACE_SUBGOAL",
            re.compile(r"^\s*\{\s*(?:--.*)?$"),
            "warning",
            "Found standalone opening brace '{' for subgoal. Lean 4 standard practice uses focus dots '·' (\\.) to delimit subgoals.",
        ),
    ]

    @classmethod
    def mask_comments_and_strings(cls, code: str) -> str:
        """Mask inline/block comments and string literals with spaces.

        Preserves exact line counts, line breaks ('\\n'), and column positions
        so that syntax lint diagnostics report accurate line and column numbers
        without false positives from comments or string contents.
        """
        chars = list(code)
        n = len(chars)
        i = 0
        state = "code"  # "code", "string", "line_comment", "block_comment"
        block_depth = 0

        while i < n:
            c = chars[i]
            c_next = chars[i + 1] if i + 1 < n else ""

            if state == "code":
                # Check for character literals like 'a', '"', '\'', etc.
                # Avoid confusing Lean primed identifiers (e.g., x', h') with character literals.
                if c == "'":
                    is_ident_char_before = i > 0 and (chars[i - 1].isalnum() or chars[i - 1] in ("_", "'"))
                    if not is_ident_char_before:
                        # Check for simple char literal: 'x'
                        if i + 2 < n and chars[i + 2] == "'" and chars[i + 1] != "\\":
                            chars[i] = " "
                            chars[i + 1] = " "
                            chars[i + 2] = " "
                            i += 3
                            continue
                        # Check for escaped char literal: '\n', '\'', '\"'
                        if i + 3 < n and chars[i + 1] == "\\" and chars[i + 3] == "'":
                            chars[i] = " "
                            chars[i + 1] = " "
                            chars[i + 2] = " "
                            chars[i + 3] = " "
                            i += 4
                            continue

                if c == '"':
                    state = "string"
                    chars[i] = " "
                    i += 1
                elif c == "-" and c_next == "-":
                    state = "line_comment"
                    chars[i] = " "
                    chars[i + 1] = " "
                    i += 2
                elif c == "/" and c_next == "-":
                    state = "block_comment"
                    block_depth = 1
                    chars[i] = " "
                    chars[i + 1] = " "
                    i += 2
                else:
                    i += 1
            elif state == "string":
                if c == "\\":
                    chars[i] = " "
                    if i + 1 < n:
                        if chars[i + 1] != "\n":
                            chars[i + 1] = " "
                        i += 2
                    else:
                        i += 1
                elif c == '"':
                    chars[i] = " "
                    state = "code"
                    i += 1
                else:
                    if c != "\n":
                        chars[i] = " "
                    i += 1
            elif state == "line_comment":
                if c == "\n":
                    state = "code"
                    i += 1
                else:
                    chars[i] = " "
                    i += 1
            elif state == "block_comment":
                if c == "/" and c_next == "-":
                    block_depth += 1
                    chars[i] = " "
                    chars[i + 1] = " "
                    i += 2
                elif c == "-" and c_next == "/":
                    block_depth -= 1
                    chars[i] = " "
                    chars[i + 1] = " "
                    i += 2
                    if block_depth <= 0:
                        state = "code"
                else:
                    if c != "\n":
                        chars[i] = " "
                    i += 1

        return "".join(chars)

    @classmethod
    def lint(cls, code: str) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        lines = code.splitlines()

        # Check for module docstrings `/-!` placed before `import` statements
        has_seen_mod_doc = False
        mod_doc_line = 0
        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("/-!"):
                has_seen_mod_doc = True
                mod_doc_line = line_idx
            elif (stripped.startswith("import ") or stripped.startswith("public import ")) and has_seen_mod_doc:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        line=mod_doc_line,
                        column=1,
                        message="[LEAN4_MODULE_DOC_BEFORE_IMPORT] Module docstring `/-! ... -/` must be placed AFTER all `import` statements. Placing it before imports triggers an `invalid 'import' command` compile error.",
                        source="lean3-linter",
                    )
                )
                has_seen_mod_doc = False

        # Mask comments and string literals to prevent false positives
        masked_code = cls.mask_comments_and_strings(code)
        masked_lines = masked_code.splitlines()

        decl_pattern = re.compile(r"^\s*(?:theorem|lemma|def|instance|example)\b")
        branch_pattern = re.compile(r"\b(?:if|match)\b")
        current_decl_start = 0

        for line_idx, masked_line in enumerate(masked_lines, start=1):
            if decl_pattern.search(masked_line):
                current_decl_start = line_idx - 1

            if not masked_line.strip():
                continue

            for rule_id, pattern, severity, message in cls.RULES:
                match = pattern.search(masked_line)
                if match:
                    if rule_id == "LEAN3_SPLIT_CONJUNCTION":
                        # In static linting, if the enclosing declaration contains 'if' or 'match',
                        # 'split' is legitimate Lean 4 syntax for case-splitting branches.
                        enclosing_context = "\n".join(masked_lines[current_decl_start:line_idx])
                        if branch_pattern.search(enclosing_context):
                            continue

                    col = match.start() + 1
                    diagnostics.append(
                        Diagnostic(
                            severity=severity,
                            line=line_idx,
                            column=max(1, col),
                            message=f"[{rule_id}] {message}",
                            source="lean3-linter",
                        )
                    )

        return diagnostics


class Lean4SyntaxChecker:
    """Validates Lean 4 code syntax and elaboration via `lake env lean --json`."""

    def __init__(self, project_root: Optional[Path] = None, timeout: float = 30.0):
        self.project_root = self._resolve_project_root(project_root)
        self.timeout = timeout

    @staticmethod
    def _resolve_project_root(explicit_root: Optional[Path]) -> Path:
        if explicit_root:
            resolved = explicit_root.resolve()
            if (resolved / "lean-toolchain").exists():
                return resolved
            return resolved

        cwd = Path.cwd().resolve()
        cur = cwd
        while cur != cur.parent:
            if (cur / "lean-toolchain").exists() or (cur / "lakefile.lean").exists() or (cur / "lakefile.toml").exists():
                return cur
            cur = cur.parent

        return cwd

    def check_file(
        self,
        file_path: Path,
        run_lint: bool = True,
        auto_import_mathlib: bool = False,
    ) -> CheckResult:
        """Checks an existing Lean file."""
        if not file_path.exists():
            return CheckResult(
                is_valid=False,
                has_warnings=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        line=0,
                        column=0,
                        message=f"Target file does not exist: {file_path}",
                        source="lean-compiler",
                    )
                ],
                raw_output="",
                checked_path=str(file_path),
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return CheckResult(
                is_valid=False,
                has_warnings=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        line=0,
                        column=0,
                        message=f"Failed to read file {file_path}: {e}",
                        source="lean-compiler",
                    )
                ],
                raw_output="",
                checked_path=str(file_path),
            )

        if auto_import_mathlib:
            res = self.check_snippet(content, run_lint=run_lint, auto_import_mathlib=True)
            res.checked_path = str(file_path)
            return res

        lint_diags = Lean3Linter.lint(content) if run_lint else []
        compiler_result = self._run_lean_compiler(file_path)

        all_diags = self._reconcile_diagnostics(lint_diags, compiler_result.diagnostics)
        has_error = any(d.severity == "error" for d in all_diags)
        has_warning = any(d.severity == "warning" for d in all_diags)

        return CheckResult(
            is_valid=(not has_error),
            has_warnings=has_warning,
            diagnostics=all_diags,
            raw_output=compiler_result.raw_output,
            checked_path=str(file_path),
        )

    @staticmethod
    def _reconcile_diagnostics(
        lint_diags: List[Diagnostic], compiler_diags: List[Diagnostic]
    ) -> List[Diagnostic]:
        """Reconcile static linter warnings with real-time compiler diagnostics.

        Suppresses heuristic false positives (such as `LEAN3_SPLIT_CONJUNCTION`) when
        the compiler executed without a split tactic failure on that line.
        """
        split_failure_lines = set()
        compiler_executed = False

        for cd in compiler_diags:
            if cd.line > 0:
                compiler_executed = True
            msg_lower = cd.message.lower()
            if "split" in msg_lower and ("failed" in msg_lower or "could not split" in msg_lower):
                split_failure_lines.add(cd.line)

        # If compiler produced no diagnostics, it executed successfully and cleanly
        if not compiler_diags:
            compiler_executed = True

        filtered_lint: List[Diagnostic] = []
        for ld in lint_diags:
            if "[LEAN3_SPLIT_CONJUNCTION]" in ld.message:
                # If the compiler executed and did NOT report a split failure on this line,
                # the split is valid in Lean 4 and should not trigger a warning.
                if compiler_executed and ld.line not in split_failure_lines:
                    continue
            filtered_lint.append(ld)

        return filtered_lint + compiler_diags

    def check_snippet(
        self,
        code_snippet: str,
        run_lint: bool = True,
        auto_import_mathlib: bool = False,
    ) -> CheckResult:
        """Writes a snippet to a temporary file in `.lake/temp_check/` and validates it."""
        lint_diags = Lean3Linter.lint(code_snippet) if run_lint else []

        line_offset = 0
        snippet_to_compile = code_snippet
        if auto_import_mathlib:
            has_mathlib_import = bool(
                re.search(r"^\s*import\s+Mathlib\b", code_snippet, re.MULTILINE)
            )
            if not has_mathlib_import:
                snippet_to_compile = f"import Mathlib\n{code_snippet}"
                line_offset = 1

        temp_dir = self.project_root / ".lake" / "temp_check"
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            temp_dir = Path(tempfile.gettempdir())

        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lean",
            dir=temp_dir,
            delete=False,
            encoding="utf-8",
        )
        temp_file_path = Path(temp_file.name)

        try:
            temp_file.write(snippet_to_compile)
            temp_file.flush()
            temp_file.close()

            compiler_result = self._run_lean_compiler(temp_file_path)
        finally:
            if temp_file_path.exists():
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass

        # Adjust compiler diagnostic line numbers to match original snippet
        adjusted_compiler_diags: List[Diagnostic] = []
        for d in compiler_result.diagnostics:
            if line_offset > 0:
                if d.line > line_offset:
                    d = Diagnostic(
                        severity=d.severity,
                        line=d.line - line_offset,
                        column=d.column,
                        message=d.message,
                        source=d.source,
                    )
                elif d.line == 1 and line_offset == 1:
                    d = Diagnostic(
                        severity=d.severity,
                        line=0,
                        column=d.column,
                        message=f"(auto-import) {d.message}",
                        source=d.source,
                    )
            adjusted_compiler_diags.append(d)

        all_diags = self._reconcile_diagnostics(lint_diags, adjusted_compiler_diags)
        has_error = any(d.severity == "error" for d in all_diags)
        has_warning = any(d.severity == "warning" for d in all_diags)

        return CheckResult(
            is_valid=(not has_error),
            has_warnings=has_warning,
            diagnostics=all_diags,
            raw_output=compiler_result.raw_output,
            checked_path="<snippet>",
        )

    def _run_lean_compiler(self, lean_file: Path) -> CheckResult:
        """Executes `lake env lean --json <file>`."""
        cmd = ["lake", "env", "lean", "--json", str(lean_file)]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            # Fall back to standalone `lean --json` if lake is not found in PATH
            cmd_fallback = ["lean", "--json", str(lean_file)]
            try:
                proc = subprocess.run(
                    cmd_fallback,
                    cwd=str(self.project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout,
                )
            except Exception as e:
                return CheckResult(
                    is_valid=False,
                    has_warnings=False,
                    diagnostics=[
                        Diagnostic(
                            severity="error",
                            line=0,
                            column=0,
                            message=f"Failed to execute lean command: {e}",
                            source="lean-compiler",
                        )
                    ],
                    raw_output="",
                )
        except subprocess.TimeoutExpired:
            return CheckResult(
                is_valid=False,
                has_warnings=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        line=0,
                        column=0,
                        message=f"Validation timed out after {self.timeout}s",
                        source="lean-compiler",
                    )
                ],
                raw_output="",
            )
        except Exception as e:
            return CheckResult(
                is_valid=False,
                has_warnings=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        line=0,
                        column=0,
                        message=f"Error executing validation: {e}",
                        source="lean-compiler",
                    )
                ],
                raw_output="",
            )

        diagnostics: List[Diagnostic] = []
        has_error = False
        raw_stdout = proc.stdout.strip()

        if raw_stdout:
            for line in raw_stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    records = record if isinstance(record, list) else [record]
                    for r in records:
                        sev = r.get("severity", "info").lower()
                        pos = r.get("pos", {})
                        data = r.get("data", "")
                        d = Diagnostic(
                            severity=sev,
                            line=pos.get("line", 0),
                            column=pos.get("column", 0),
                            message=data.strip(),
                            source="lean-compiler",
                        )
                        diagnostics.append(d)
                        if sev == "error":
                            has_error = True
                except json.JSONDecodeError:
                    continue

        if proc.returncode != 0 and not has_error:
            has_error = True
            err_msg = proc.stderr.strip() or "Lean compilation failed with non-zero exit code"
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    line=0,
                    column=0,
                    message=err_msg,
                    source="lean-compiler",
                )
            )

        has_warning = any(d.severity == "warning" for d in diagnostics)

        return CheckResult(
            is_valid=(not has_error),
            has_warnings=has_warning,
            diagnostics=diagnostics,
            raw_output=raw_stdout,
        )


def format_text_output(result: CheckResult) -> str:
    status_str = "VALID" if result.is_valid else "INVALID"
    lines = [
        f"=== Lean 4 Syntax & Elaboration Check: {status_str} ===",
        f"Target: {result.checked_path or '<snippet>'}",
    ]

    if not result.diagnostics:
        lines.append("No errors or warnings detected.")
    else:
        lines.append(f"Total diagnostics: {len(result.diagnostics)}")
        for d in result.diagnostics:
            pos_str = f"L{d.line}:C{d.column}" if d.line > 0 else "[-:-]"
            lines.append(f"[{d.severity.upper():<7}] {pos_str:<10} ({d.source}) {d.message}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fast Lean 4 Syntax & Elaboration Checker with Lean 3 Linting"
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "file",
        nargs="?",
        type=str,
        help="Path to an existing .lean file to check",
    )
    group.add_argument(
        "-s",
        "--snippet",
        type=str,
        help="Lean 4 code snippet string to check",
    )
    group.add_argument(
        "--stdin",
        action="store_true",
        help="Read code snippet from standard input",
    )

    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Path to Lean project root (defaults to nearest ancestor with lean-toolchain)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Subprocess execution timeout in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--no-lint",
        action="store_true",
        help="Disable Lean 3 deprecation linter",
    )
    parser.add_argument(
        "--lint-only",
        action="store_true",
        help="Run only the static Lean 3 linter without calling Lean compiler",
    )
    parser.add_argument(
        "--mathlib",
        "--auto-import",
        action="store_true",
        dest="mathlib",
        help="Automatically prepend 'import Mathlib' to snippets if not already present",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )

    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else None
    checker = Lean4SyntaxChecker(project_root=project_root, timeout=args.timeout)
    run_lint = not args.no_lint

    # Read snippet from stdin if specified
    if args.stdin or (not args.file and not args.snippet and not sys.stdin.isatty()):
        code = sys.stdin.read()
        if args.lint_only:
            diags = Lean3Linter.lint(code)
            has_error = any(d.severity == "error" for d in diags)
            res = CheckResult(
                is_valid=(not has_error),
                has_warnings=any(d.severity == "warning" for d in diags),
                diagnostics=diags,
                raw_output="",
                checked_path="<stdin>",
            )
        else:
            res = checker.check_snippet(code, run_lint=run_lint, auto_import_mathlib=args.mathlib)
    elif args.snippet:
        code = args.snippet
        if args.lint_only:
            diags = Lean3Linter.lint(code)
            has_error = any(d.severity == "error" for d in diags)
            res = CheckResult(
                is_valid=(not has_error),
                has_warnings=any(d.severity == "warning" for d in diags),
                diagnostics=diags,
                raw_output="",
                checked_path="<snippet>",
            )
        else:
            res = checker.check_snippet(code, run_lint=run_lint, auto_import_mathlib=args.mathlib)
    elif args.file:
        file_path = Path(args.file)
        if args.lint_only:
            if not file_path.exists():
                res = CheckResult(
                    is_valid=False,
                    has_warnings=False,
                    diagnostics=[
                        Diagnostic(
                            severity="error",
                            line=0,
                            column=0,
                            message=f"File not found: {file_path}",
                            source="lean3-linter",
                        )
                    ],
                    raw_output="",
                    checked_path=str(file_path),
                )
            else:
                diags = Lean3Linter.lint(file_path.read_text(encoding="utf-8"))
                has_error = any(d.severity == "error" for d in diags)
                res = CheckResult(
                    is_valid=(not has_error),
                    has_warnings=any(d.severity == "warning" for d in diags),
                    diagnostics=diags,
                    raw_output="",
                    checked_path=str(file_path),
                )
        else:
            res = checker.check_file(file_path, run_lint=run_lint, auto_import_mathlib=args.mathlib)
    else:
        parser.print_help()
        return 1

    if args.json:
        print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_text_output(res))

    return 0 if res.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
