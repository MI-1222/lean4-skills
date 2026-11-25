#!/usr/bin/env python3
"""
Static scanner for Lean 4 constructs that need attention in a soundness audit.

Finds trust-base extensions that `#print axioms` cannot reveal (elaborator bypass,
environment modification, native evaluation, global notation changes, etc.) by text search.
Comments and string literals are blanked out before matching, so words inside them
do not produce false positives.

A text search is not a proof. The results do not replace kernel replay
(`leanchecker`, Comparator, ...); treat them as a first-pass filter that narrows
down what a human reviewer must read.
"""

import argparse
import bisect
import fnmatch
import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

# Severity ordering; a larger value is more severe.
SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}

# Directory names skipped by default.
DEFAULT_EXCLUDED_DIRS = {".lake", ".git", "lake-packages", "__pycache__"}

# With `--jobs 0` (auto), scans of at least this many files run in parallel.
AUTO_PARALLEL_MIN_FILES = 256

# Attributes and modifiers that may precede a declaration keyword; anchored at line start.
DECL_PREFIX = r"^[ \t]*(?:@\[[^\]\n]*\][ \t]*)?(?:(?:private|protected|noncomputable|unsafe|partial|nonrec)[ \t]+)*"

# Scope qualifier for notation: `local`, `scoped` or `scoped[NS]`.
SCOPE_PREFIX = r"(?P<scope>(?:local|scoped(?:\[[^\]\n]*\])?)[ \t]+)?"

# Character literal (e.g. 'a', '\n', '\x41', '"'), as opposed to a trailing prime in an identifier (h').
CHAR_LITERAL_RE = re.compile(r"'(?:\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)|[^\\'\n])'")

# Opening of a raw string literal (e.g. r"...", r#"..."#).
RAW_STRING_START_RE = re.compile(r'r(#*)"')

# Positions where a comment, string, character literal or «...» identifier may start.
MASK_CANDIDATE_RE = re.compile(r"--|/-|«|\"|'|r#*\"")

# Any character except a newline; used to blank out a range while keeping line numbers.
NON_NEWLINE_RE = re.compile(r"[^\n]")

@dataclass(frozen=True)
class Rule:
    """
    Definition of a detection rule.

    :param rule_id: Rule identifier used in the output.
    :param severity: One of `critical`, `warning` or `info`.
    :param pattern: Regex applied to the source after comments and strings are blanked out.
    :param description: Why the construct is flagged and what a reviewer should check.
    :param accept: Optional extra predicate on a match; `None` accepts every match.
    :param keywords: Literal substrings, one of which every match contains. A file without
        any of them is skipped for this rule without running the regex; empty means always run.
    """

    rule_id: str
    severity: str
    pattern: re.Pattern[str]
    description: str
    accept: Callable[[re.Match[str]], bool] | None = None
    keywords: tuple[str, ...] = ()


def _compile(pattern: str) -> re.Pattern[str]:
    """
    Compile a rule regex in multiline mode.

    :param pattern: Regex string.
    :return: Compiled regex.
    """
    return re.compile(pattern, re.MULTILINE)


def _is_unscoped(match: re.Match[str]) -> bool:
    """
    Return True if a notation definition is not restricted by `local` / `scoped`.

    :param match: Match object with a `scope` named group.
    :return: `True` for a global notation definition.
    """
    return match.group("scope") is None


RULES: list[Rule] = [
    # critical: unproven assumptions, or kernel checking disabled.
    Rule(
        "sorry",
        "critical",
        _compile(r"\bsorry\b"),
        "Unproven placeholder; the proof depends on `sorryAx`.",
        keywords=("sorry",),
    ),
    Rule(
        "admit",
        "critical",
        _compile(r"\badmit\b"),
        "Synonym of `sorry`; the proof depends on `sorryAx`.",
        keywords=("admit",),
    ),
    Rule(
        "sorry-internals",
        "critical",
        _compile(r"\b(?:sorryAx|mkSorry|admitGoal)\b"),
        "Direct use of sorry internals (e.g. inside a custom tactic) can hide `sorryAx` behind a harmless-looking name.",
        keywords=("sorryAx", "mkSorry", "admitGoal"),
    ),
    Rule(
        "axiom-declaration",
        "critical",
        _compile(DECL_PREFIX + r"axiom\b"),
        "User-declared axiom; postulates a claim without proof.",
        keywords=("axiom",),
    ),
    Rule(
        "native-evaluation",
        "critical",
        _compile(
            r"\b(?:native_decide|ofReduceBool|ofReduceNat|trustCompiler)\b"
            r"|\bLean\.reduce(?:Bool|Nat)\b"
            r"|\bdecide[ \t]*\+[ \t]*native\b"
        ),
        "Trusts the compiler and native code (`Lean.ofReduceBool` / `Lean.trustCompiler`) instead of the kernel.",
        keywords=("native", "ofReduce", "trustCompiler", "reduceBool", "reduceNat"),
    ),
    Rule(
        "kernel-check-bypass",
        "critical",
        _compile(
            r"\bset_option[ \t]+debug\.|\bskipKernelTC\b|\baddDeclWithoutChecking\b"
        ),
        "Disables or skips kernel type checking (`debug.*` options, `addDeclWithoutChecking`).",
        keywords=("debug.", "skipKernelTC", "addDeclWithoutChecking"),
    ),
    # warning: the kernel still checks, but elaborator checks or the trust base change.
    Rule(
        "goal-assignment",
        "warning",
        _compile(
            r"\.(?:assign|checkedAssign)\b|\bassignExprMVar\b"
            r"|\bcloseMainGoal(?:Using)?(?![\w'!?])"
        ),
        "Assigns a metavariable or closes the goal without comparing types itself (`checkedAssign` and "
        "`closeMainGoal` add only an occurs check; `closeMainGoalUsing` leaves the check to its "
        "callback). A custom tactic built on this without a type check (e.g. an `exact` variant) "
        "skips the elaborator's check; only the kernel checks the resulting term.",
        keywords=(".assign", ".checkedAssign", "assignExprMVar", "closeMainGoal"),
    ),
    Rule(
        "metaprogram-evaluation",
        "warning",
        _compile(r"\brun_(?:tac|cmd|elab|meta)\b|#eval!?(?![\w'])"),
        "Runs an arbitrary metaprogram while the file is elaborated.",
        keywords=("run_", "#eval"),
    ),
    Rule(
        "environment-modification",
        "warning",
        _compile(r"\b(?:addDecl|addAndCompile|modifyEnv|setEnv)\b"),
        "Adds or rewrites environment entries programmatically; check what is added and under which name.",
        keywords=("addDecl", "addAndCompile", "modifyEnv", "setEnv"),
    ),
    Rule(
        "initializer",
        "warning",
        _compile(r"^[ \t]*(?:builtin_)?initialize\b"),
        "Code that runs whenever the module is imported.",
        keywords=("initialize",),
    ),
    Rule(
        "unsafe-code",
        "warning",
        _compile(r"\bunsafe(?:Cast|BaseIO|IO|EIO)?\b|\ballowUnsafeReducibility\b"),
        "Unsafe code or unsafe reducibility changes; outside the guarantees of the type system.",
        keywords=("unsafe", "allowUnsafeReducibility"),
    ),
    Rule(
        "compiler-trust",
        "warning",
        _compile(r"\b(?:implemented_by|extern)\b"),
        "Replaces a definition's compiled code; matters whenever native evaluation is trusted.",
        keywords=("implemented_by", "extern"),
    ),
    Rule(
        "sat-certificate",
        "warning",
        _compile(r"\bbv_(?:decide|check)\b"),
        "Proof by SAT certificate; depending on the Lean version it may rely on native evaluation. "
        "Confirm with `#print axioms`.",
        keywords=("bv_",),
    ),
    Rule(
        "global-notation",
        "warning",
        _compile(
            r"^[ \t]*(?:@\[[^\]\n]*\][ \t]*)?"
            + SCOPE_PREFIX
            + r"(?:notation3?|infixl|infixr|infix|prefix|postfix)\b"
        ),
        "Global notation (not `local` / `scoped`); can change how a theorem statement reads.",
        accept=_is_unscoped,
        keywords=("notation", "infix", "prefix", "postfix"),
    ),
    Rule(
        "io-side-effect",
        "warning",
        _compile(r"\bIO\.(?:Process|FS|getEnv)\b"),
        "Starts processes, touches files or reads the environment during elaboration.",
        keywords=("IO.",),
    ),
    # info: places with metaprogramming capability.
    Rule(
        "lean-meta-import",
        "info",
        _compile(
            r"^[ \t]*(?:(?:public|private|meta)[ \t]+)*import[ \t]+(?:all[ \t]+)?Lean(?:\.[\w.]+)?(?![\w'])"
        ),
        "Imports Lean's metaprogramming API; review the custom commands and tactics defined with it.",
        keywords=("Lean",),
    ),
    Rule(
        "syntax-extension",
        "info",
        _compile(
            r"^[ \t]*(?:@\[[^\]\n]*\][ \t]*)?"
            + SCOPE_PREFIX
            + r"(?:macro_rules|macro|syntax|elab_rules|elab|declare_syntax_cat)\b"
        ),
        "Defines new syntax, macros or elaborators; read what each one expands to.",
        keywords=("macro", "syntax", "elab"),
    ),
    Rule(
        "opaque-declaration",
        "info",
        _compile(DECL_PREFIX + r"opaque\b"),
        "Opaque constant; its value is hidden from definitional unfolding.",
        keywords=("opaque",),
    ),
]

RULES_BY_ID = {rule.rule_id: rule for rule in RULES}


def _is_identifier_char(char: str) -> bool:
    """
    Return whether a character can be part of a Lean identifier.

    :param char: Single character to test.
    :return: `True` if it can occur in an identifier.
    """
    return char.isalnum() or char in "_'!?"


def mask_comments_and_strings(source: str) -> str:
    """
    Replace comments and string literals with spaces, keeping newlines so line numbers are preserved.

    Handles line comments (`--`), nested block comments (`/- -/`, including docstrings),
    string literals, raw string literals and character literals.
    Identifiers quoted with `«...»` are kept as identifiers, with their contents filled with `_`.

    :param source: Full Lean source text.
    :return: Source with comments and strings blanked out; same length as `source`.
    """
    length = len(source)
    pieces: list[str] = []
    kept_until = 0

    def replace(start: int, end: int, filler: str) -> None:
        """Copy the text before `start`, then the range with every non-newline replaced by `filler`."""
        nonlocal kept_until
        end = min(end, length)
        pieces.append(source[kept_until:start])
        pieces.append(NON_NEWLINE_RE.sub(filler, source[start:end]))
        kept_until = end

    i = 0
    while i < length:
        candidate = MASK_CANDIDATE_RE.search(source, i)
        if candidate is None:
            break
        i = candidate.start()
        char = source[i]
        previous = source[i - 1] if i > 0 else ""

        # Line comment.
        if source.startswith("--", i):
            end = source.find("\n", i)
            end = length if end == -1 else end
            replace(i, end, " ")
            i = end
            continue

        # Block comment or docstring (may be nested).
        if source.startswith("/-", i):
            depth = 1
            j = i + 2
            while j < length and depth > 0:
                if source.startswith("/-", j):
                    depth += 1
                    j += 2
                elif source.startswith("-/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            replace(i, j, " ")
            i = j
            continue

        # Keep a «...» identifier as a single token by filling its contents with `_`,
        # so that e.g. «sorry-free» is not reported as `sorry`.
        if char == "«":
            end = source.find("»", i + 1)
            end = length if end == -1 else end
            replace(i + 1, end, "_")
            i = end + 1
            continue

        # Raw string literal.
        if char == "r" and not _is_identifier_char(previous):
            raw_match = RAW_STRING_START_RE.match(source, i)
            if raw_match:
                terminator = '"' + raw_match.group(1)
                end = source.find(terminator, raw_match.end())
                end = length if end == -1 else end + len(terminator)
                replace(i, end, " ")
                i = end
                continue

        # Ordinary string literal (including interpolated s!"...").
        if char == '"':
            j = i + 1
            while j < length and source[j] != '"':
                j += 2 if source[j] == "\\" else 1
            replace(i, j + 1, " ")
            i = j + 1
            continue

        # Character literal; a trailing prime of an identifier is not one.
        if char == "'" and not _is_identifier_char(previous):
            char_match = CHAR_LITERAL_RE.match(source, i)
            if char_match:
                replace(i, char_match.end(), " ")
                i = char_match.end()
                continue

        i += 1

    pieces.append(source[kept_until:])
    return "".join(pieces)


def _rule_applies(rule: Rule, masked: str) -> bool:
    """
    Return whether a rule's regex can match, judged by its keywords.

    :param rule: Rule with a pattern.
    :param masked: Masked source text.
    :return: `False` if the rule has keywords and none of them occurs in the text.
    """
    return not rule.keywords or any(keyword in masked for keyword in rule.keywords)


def _line_starts(source: str) -> list[int]:
    """
    Return the offset of the first character of every line.

    :param source: Source text.
    :return: Ascending offsets, starting with 0.
    """
    return [0] + [m.end() for m in re.finditer("\n", source)]


def scan_masked(source: str, masked: str, rules: list[Rule]) -> list[dict[str, Any]]:
    """
    Apply pattern rules to one file's masked source.

    Multiple matches of the same rule on the same line are reported once.

    :param source: Full Lean source text, used for line text in the findings.
    :param masked: Output of `mask_comments_and_strings(source)`.
    :param rules: Rules to apply.
    :return: Findings with `line`, `column`, `rule`, `severity` and `text`.
    """
    line_starts = _line_starts(source)
    original_lines = source.splitlines()

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rule in rules:
        if not _rule_applies(rule, masked):
            continue
        for match in rule.pattern.finditer(masked):
            if rule.accept is not None and not rule.accept(match):
                continue
            # Line-anchored rules also match leading whitespace; report the first non-blank position.
            offset = match.start() + (
                len(match.group(0)) - len(match.group(0).lstrip())
            )
            line_index = bisect.bisect_right(line_starts, offset) - 1
            key = (rule.rule_id, line_index)
            if key in seen:
                continue
            seen.add(key)
            text = (
                original_lines[line_index].strip()
                if line_index < len(original_lines)
                else ""
            )
            findings.append(
                {
                    "line": line_index + 1,
                    "column": offset - line_starts[line_index] + 1,
                    "rule": rule.rule_id,
                    "severity": rule.severity,
                    "text": text[:200],
                }
            )
    findings.sort(key=lambda f: (f["line"], f["column"]))
    return findings


def scan_source(source: str, rules: list[Rule]) -> list[dict[str, Any]]:
    """
    Scan one file's source and return the locations matched by the rules.

    Multiple matches of the same rule on the same line are reported once.

    :param source: Full Lean source text.
    :param rules: Rules to apply.
    :return: Findings with `line`, `column`, `rule`, `severity` and `text`.
    """
    return scan_masked(source, mask_comments_and_strings(source), rules)


def iter_lean_files(paths: list[str], excludes: list[str]) -> list[str]:
    """
    List the `.lean` files under the given paths.

    Default-excluded directories such as `.lake` and `.git` are not traversed.

    :param paths: File or directory paths.
    :param excludes: Glob patterns of paths to skip (matched against slash-separated paths).
    :return: Sorted, de-duplicated file paths.
    """

    def is_excluded(path: str) -> bool:
        """Return True if the path matches any of the exclusion globs."""
        normalized = os.path.normpath(path).replace(os.sep, "/")
        return any(fnmatch.fnmatch(normalized, pattern) for pattern in excludes)

    files: set[str] = set()
    for path in paths:
        if os.path.isfile(path):
            if path.endswith(".lean") and not is_excluded(path):
                files.add(os.path.normpath(path))
            continue
        for root, dirs, names in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS)
            for name in names:
                if not name.endswith(".lean"):
                    continue
                file_path = os.path.normpath(os.path.join(root, name))
                if not is_excluded(file_path):
                    files.add(file_path)
    return sorted(files)


def _read_source(file_path: str) -> str:
    """
    Read a Lean source file as UTF-8, replacing undecodable bytes.

    :param file_path: Path of the file.
    :return: File contents.
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _analyze_file(
    task: tuple[str, tuple[str, ...]],
) -> tuple[str, list[dict[str, Any]], str | None]:
    """
    Apply the pattern rules to one file.

    :param task: File path and the IDs of the rules to apply.
    :return: File path, findings, and an error message if the file is unreadable.
    """
    file_path, rule_ids = task
    try:
        source = _read_source(file_path)
    except OSError as error:
        return file_path, [], str(error)
    masked = mask_comments_and_strings(source)
    rules = [RULES_BY_ID[rule_id] for rule_id in rule_ids]
    findings = [{"file": file_path, **f} for f in scan_masked(source, masked, rules)]
    return file_path, findings, None


def _map_tasks(
    function: Callable[[Any], Any], tasks: list[Any], jobs: int
) -> Iterable[Any]:
    """
    Apply a function to every task, in parallel when `jobs` is greater than 1.

    :param function: Top-level function (picklable for worker processes).
    :param tasks: Arguments, one per call.
    :param jobs: Number of worker processes; 1 runs in this process.
    :return: Results in task order.
    """
    if jobs <= 1 or len(tasks) <= 1:
        return map(function, tasks)
    with ProcessPoolExecutor(max_workers=jobs) as executor:
        return list(executor.map(function, tasks, chunksize=max(1, len(tasks) // (jobs * 16))))


def build_report(
    files: list[str], rules: list[Rule], fail_on: str, jobs: int = 1
) -> dict[str, Any]:
    """
    Scan all files and build the census and per-file findings.

    :param files: `.lean` files to scan.
    :param rules: Rules to apply.
    :param fail_on: Lowest severity that counts as a failure; `never` always passes.
    :param jobs: Number of worker processes; 1 scans in this process.
    :return: Report for JSON output.
    """
    rule_ids = tuple(rule.rule_id for rule in rules)

    findings: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    for file_path, file_findings, error in _map_tasks(
        _analyze_file, [(f, rule_ids) for f in files], jobs
    ):
        if error is not None:
            unreadable.append({"file": file_path, "error": error})
            continue
        findings.extend(file_findings)

    census = []
    for rule in rules:
        hits = [f for f in findings if f["rule"] == rule.rule_id]
        census.append(
            {
                "rule": rule.rule_id,
                "severity": rule.severity,
                "count": len(hits),
                "file_count": len({f["file"] for f in hits}),
                "description": rule.description,
            }
        )

    counts = {severity: 0 for severity in ("critical", "warning", "info")}
    for finding in findings:
        counts[finding["severity"]] += 1

    if fail_on == "never":
        passed = True
    else:
        threshold = SEVERITY_RANK[fail_on]
        passed = not any(SEVERITY_RANK[f["severity"]] >= threshold for f in findings)

    return {
        "passed": passed,
        "fail_on": fail_on,
        "scanned_files": len(files),
        "counts": counts,
        "summary": (
            f"{len(files)} file(s) scanned: {counts['critical']} critical, "
            f"{counts['warning']} warning(s), {counts['info']} info(s)"
        ),
        "census": census,
        "findings": findings,
        "unreadable_files": unreadable,
    }


def format_text_report(report: dict[str, Any], max_findings: int) -> str:
    """
    Format the report as human-readable text.

    :param report: Return value of `build_report`.
    :param max_findings: Maximum number of findings to show; 0 shows all.
    :return: Formatted text.
    """
    lines = [
        f"Risky-construct scan: {report['summary']}",
        "",
        "Census (occurrences / files):",
    ]
    for entry in report["census"]:
        lines.append(
            f"  [{entry['severity']:<8}] {entry['rule']:<26} {entry['count']:>7} / {entry['file_count']}"
        )

    findings = sorted(
        report["findings"],
        key=lambda f: (-SEVERITY_RANK[f["severity"]], f["file"], f["line"]),
    )
    if findings:
        lines.append("")
        lines.append("Findings:")
        shown = findings if max_findings == 0 else findings[:max_findings]
        for f in shown:
            lines.append(
                f"  {f['file']}:{f['line']}:{f['column']}: {f['severity']}: [{f['rule']}] {f['text']}"
            )
        if len(shown) < len(findings):
            lines.append(
                f"  ... {len(findings) - len(shown)} more (use --max-findings 0 to show all)"
            )

    for entry in report["unreadable_files"]:
        lines.append(f"Unreadable file: {entry['file']} ({entry['error']})")

    lines.append("")
    verdict = "PASSED" if report["passed"] else "FAILED"
    lines.append(f"Result: {verdict} (fail-on: {report['fail_on']})")
    lines.append(
        "Note: a text scan is not a proof. Kernel replay and axiom checks are still required."
    )
    return "\n".join(lines)


def main() -> None:
    """Parse command-line arguments and run the scan."""
    parser = argparse.ArgumentParser(
        description=(
            "Scan Lean 4 sources for constructs that need a soundness review "
            "(sorry, axioms, native evaluation, elaborator bypass, environment hacking, global notation)."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: current directory). `.lake` and `.git` are skipped.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Glob pattern of paths to skip, e.g. 'src/Challenge.lean'. May be repeated.",
    )
    parser.add_argument(
        "--ignore-rule",
        action="append",
        default=[],
        metavar="RULE",
        help="Rule ID to disable, e.g. 'lean-meta-import'. May be repeated.",
    )
    parser.add_argument(
        "--fail-on",
        choices=["critical", "warning", "info", "never"],
        default="critical",
        help="Exit with status 1 if any finding at or above this severity exists (default: critical).",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=200,
        help="Maximum findings to print in text mode; 0 for all (default: 200). JSON output always lists all.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Worker processes (default: 0 = auto, one per CPU when scanning at least "
            f"{AUTO_PARALLEL_MIN_FILES} files, otherwise 1)."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="Output the full report as JSON."
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="Print the available rules and exit.",
    )
    args = parser.parse_args()

    if args.list_rules:
        for rule in RULES:
            print(f"[{rule.severity:<8}] {rule.rule_id:<26} {rule.description}")
        sys.exit(0)

    unknown_rules = [r for r in args.ignore_rule if r not in RULES_BY_ID]
    if unknown_rules:
        parser.error(
            f"unknown rule ID(s): {', '.join(unknown_rules)} (see --list-rules)"
        )
    if args.jobs < 0:
        parser.error("--jobs must be 0 (auto) or a positive number")

    missing_paths = [p for p in args.paths if not os.path.exists(p)]
    if missing_paths:
        parser.error(f"path(s) not found: {', '.join(missing_paths)}")

    rules = [rule for rule in RULES if rule.rule_id not in set(args.ignore_rule)]
    files = iter_lean_files(args.paths, args.exclude)
    if not files:
        parser.error("no .lean files found under the given path(s)")

    jobs = args.jobs
    if jobs == 0:
        jobs = (os.cpu_count() or 1) if len(files) >= AUTO_PARALLEL_MIN_FILES else 1

    report = build_report(files, rules, args.fail_on, jobs)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text_report(report, args.max_findings))
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
