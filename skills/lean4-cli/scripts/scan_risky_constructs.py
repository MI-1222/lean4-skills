#!/usr/bin/env python3
"""
Static scanner for Lean 4 constructs that need attention in a soundness audit.

Finds trust-base extensions that `#print axioms` cannot reveal (elaborator bypass,
environment modification, native evaluation, global notation changes, etc.) by text search.
Comments and string literals are blanked out before matching, so words inside them
do not produce false positives.

Custom syntax (tactics, terms and commands defined with `elab`, `macro`, `syntax`,
`elab_rules` or `macro_rules`) whose definition contains a traced construct is followed
to every place that uses it, including through other macros and same-file helper `def`s,
so that a construct hidden behind a new name is reported where it takes effect.

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
from dataclasses import dataclass, field
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

# Start of a custom syntax definition (the unit that may hide a traced construct).
SYNTAX_COMMAND_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:@\[[^\]\n]*\][ \t]*)?"
    r"(?:(?:local|scoped(?:\[[^\]\n]*\])?)[ \t]+)?"
    r"(?P<kind>macro_rules|macro|syntax|elab_rules|elab)\b",
    re.MULTILINE,
)

# Start of a helper definition (a metaprogram a custom tactic may call).
DEF_COMMAND_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:@\[[^\]\n]*\][ \t]*)?"
    r"(?:(?:private|protected|noncomputable|unsafe|partial|nonrec)[ \t]+)*"
    r"(?:def|abbrev)[ \t]+(?P<name>[^\s:({\[]+)",
    re.MULTILINE,
)

# First string literal of a syntax definition header, i.e. its leading atom ("kexact ").
STRING_LITERAL_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"')

# Head token of a match pattern in `elab_rules` / `macro_rules` (`| `(tactic| foo ...) =>`).
# Only quotations right after an alternative's `|` are patterns; those after `=>` are expansions.
QUOTATION_HEAD_RE = re.compile(
    r"\|\s*`\((?:tactic|term|command|conv|doElem)\|\s*(?P<atom>[^\s$()\[\]]+)"
)

# Rules whose constructs are followed through custom syntax to the places that use it.
TRACED_RULE_IDS = (
    "sorry",
    "admit",
    "sorry-internals",
    "native-evaluation",
    "kernel-check-bypass",
    "goal-assignment",
    "environment-modification",
)

# Suffix of the derived rule that reports a use of custom syntax hiding a traced construct.
VIA_SYNTAX_SUFFIX = "-via-syntax"


@dataclass(frozen=True)
class Rule:
    """
    Definition of a detection rule.

    :param rule_id: Rule identifier used in the output.
    :param severity: One of `critical`, `warning` or `info`.
    :param pattern: Regex applied to the source after comments and strings are blanked out;
        `None` for a derived rule that is reported by syntax tracing instead.
    :param description: Why the construct is flagged and what a reviewer should check.
    :param accept: Optional extra predicate on a match; `None` accepts every match.
    :param keywords: Literal substrings, one of which every match contains. A file without
        any of them is skipped for this rule without running the regex; empty means always run.
    """

    rule_id: str
    severity: str
    pattern: re.Pattern[str] | None
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

# Derived rules: a use of custom syntax whose definition contains a traced construct.
DERIVED_RULES: list[Rule] = [
    Rule(
        rule.rule_id + VIA_SYNTAX_SUFFIX,
        rule.severity,
        None,
        f"Uses custom syntax defined in the scanned sources whose definition contains `{rule.rule_id}`; "
        "the construct takes effect here under another name.",
    )
    for rule in RULES
    if rule.rule_id in TRACED_RULE_IDS
]

# All rules, most severe first; this is the order of the census.
ALL_RULES: list[Rule] = sorted(
    RULES + DERIVED_RULES, key=lambda rule: -SEVERITY_RANK[rule.severity]
)

RULES_BY_ID = {rule.rule_id: rule for rule in ALL_RULES}


@dataclass
class SyntaxUnit:
    """
    A custom syntax definition found in one file.

    :param file: File that contains the definition.
    :param line: 1-indexed line of the definition.
    :param start: Offset of the definition in the file.
    :param end: Offset just past the definition.
    :param atoms: Leading tokens that invoke the syntax (e.g. `kexact`).
    :param body: Masked text of the definition, used to find references to other syntax.
    :param sources: Traced rule IDs whose constructs the definition contains or reaches.
    """

    file: str
    line: int
    start: int
    end: int
    atoms: list[str]
    body: str
    sources: set[str] = field(default_factory=set)


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
    :param rules: Rules to apply; derived rules without a pattern are skipped.
    :return: Findings with `line`, `column`, `rule`, `severity` and `text`.
    """
    line_starts = _line_starts(source)
    original_lines = source.splitlines()

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rule in rules:
        if rule.pattern is None or not _rule_applies(rule, masked):
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
    Syntax tracing across files is not part of this function; see `build_report`.

    :param source: Full Lean source text.
    :param rules: Rules to apply.
    :return: Findings with `line`, `column`, `rule`, `severity` and `text`.
    """
    return scan_masked(source, mask_comments_and_strings(source), rules)


def _command_end(masked: str, start: int, indent_width: int) -> int:
    """
    Return the end of the command that starts at `start`.

    The command extends to the next non-blank line indented no deeper than the command itself.
    Comment-only lines are blank in the masked text, so they never end a command.

    :param masked: Masked source text.
    :param start: Offset of the command's first character.
    :param indent_width: Indentation (in characters) of the command's first line.
    :return: Offset of the first character after the command.
    """
    newline = masked.find("\n", start)
    while newline != -1:
        line_start = newline + 1
        line_end = masked.find("\n", line_start)
        line = masked[line_start : len(masked) if line_end == -1 else line_end]
        stripped = line.lstrip(" \t")
        if stripped and len(line) - len(stripped) <= indent_width:
            return line_start
        newline = line_end
    return len(masked)


def _reference_pattern(token: str) -> re.Pattern[str]:
    """
    Build a regex that finds a syntax atom or identifier as a whole token.

    Word boundaries are required only on sides where the token is identifier-like,
    so symbolic atoms such as `kc%` are found as well. Internal whitespace matches any run.

    :param token: Atom or identifier, without surrounding whitespace.
    :return: Compiled regex.
    """
    body = r"\s+".join(re.escape(part) for part in token.split())
    prefix = r"(?<![\w'])" if _is_identifier_char(token[0]) else ""
    suffix = r"(?![\w'!?])" if _is_identifier_char(token[-1]) else ""
    return re.compile(prefix + body + suffix)


def _direct_sources(text: str) -> set[str]:
    """
    Return the traced rules whose constructs occur in a piece of masked text.

    :param text: Masked text of one definition.
    :return: Rule IDs from `TRACED_RULE_IDS`.
    """
    sources = set()
    for rule_id in TRACED_RULE_IDS:
        rule = RULES_BY_ID[rule_id]
        assert rule.pattern is not None
        if _rule_applies(rule, text) and rule.pattern.search(text):
            sources.add(rule_id)
    return sources


def collect_syntax_units(
    file_path: str, source: str, masked: str
) -> list[SyntaxUnit]:
    """
    Find the custom syntax definitions of one file and what traced constructs they contain.

    A definition's sources include those of helper `def`s in the same file that it refers to,
    transitively. References to syntax from other files are resolved later by `trace_syntax`.

    :param file_path: Path reported for the definitions.
    :param source: Full Lean source text (for the atoms, which live in string literals).
    :param masked: Output of `mask_comments_and_strings(source)`.
    :return: Syntax definitions; empty if the file defines none.
    """
    if not any(k in masked for k in ("macro", "syntax", "elab")):
        return []

    # Helper definitions of this file and the traced constructs each contains.
    helpers: list[tuple[re.Pattern[str], str, set[str]]] = []
    for match in DEF_COMMAND_RE.finditer(masked):
        end = _command_end(masked, match.start(), len(match.group("indent")))
        body = masked[match.start() : end]
        name = match.group("name").split(".")[-1]
        if name:
            helpers.append((_reference_pattern(name), body, _direct_sources(body)))
    changed = True
    while changed:
        changed = False
        for index, (_, body, sources) in enumerate(helpers):
            for other, (pattern, _, other_sources) in enumerate(helpers):
                if other != index and not other_sources <= sources and pattern.search(body):
                    sources |= other_sources
                    changed = True

    line_starts = _line_starts(source)
    units: list[SyntaxUnit] = []
    for match in SYNTAX_COMMAND_RE.finditer(masked):
        start = match.start() + len(match.group("indent"))
        end = _command_end(masked, match.start(), len(match.group("indent")))
        original = source[start:end]
        if match.group("kind") in ("macro_rules", "elab_rules"):
            atoms = [m.group("atom") for m in QUOTATION_HEAD_RE.finditer(original)]
        else:
            literal = STRING_LITERAL_RE.search(original)
            atoms = [literal.group(1)] if literal else []
        atoms = sorted({atom.strip() for atom in atoms if atom.strip()})
        if not atoms:
            continue
        body = masked[start:end]
        sources = _direct_sources(body)
        for pattern, _, helper_sources in helpers:
            if helper_sources and pattern.search(body):
                sources |= helper_sources
        units.append(
            SyntaxUnit(
                file=file_path,
                line=bisect.bisect_right(line_starts, start),
                start=start,
                end=end,
                atoms=atoms,
                body=body,
                sources=sources,
            )
        )
    return units


def trace_syntax(units: list[SyntaxUnit]) -> dict[str, dict[str, Any]]:
    """
    Propagate traced constructs through syntax that expands to other syntax.

    A definition that refers to an atom of another tainted definition (e.g. a macro
    expanding to a goal-assigning tactic) becomes tainted as well, until nothing changes.

    :param units: Syntax definitions from all scanned files; their `sources` are updated.
    :return: Tainted atoms, each mapped to its `sources` (rule IDs) and `definitions` (units).
    """
    patterns: dict[str, re.Pattern[str]] = {}
    changed = True
    while changed:
        changed = False
        tainted: dict[str, set[str]] = {}
        for unit in units:
            if unit.sources:
                for atom in unit.atoms:
                    tainted.setdefault(atom, set()).update(unit.sources)
        for unit in units:
            for atom, sources in tainted.items():
                if atom in unit.atoms or sources <= unit.sources:
                    continue
                pattern = patterns.setdefault(atom, _reference_pattern(atom))
                if pattern.search(unit.body):
                    unit.sources |= sources
                    changed = True

    result: dict[str, dict[str, Any]] = {}
    for unit in units:
        if not unit.sources:
            continue
        for atom in unit.atoms:
            entry = result.setdefault(atom, {"sources": set(), "definitions": []})
            entry["sources"] |= unit.sources
            entry["definitions"].append(unit)
    return result


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
) -> tuple[str, list[dict[str, Any]], list[SyntaxUnit], str | None]:
    """
    First pass over one file: pattern findings and syntax definitions.

    :param task: File path and the IDs of the rules to apply.
    :return: File path, findings, syntax definitions, and an error message if the file is unreadable.
    """
    file_path, rule_ids = task
    try:
        source = _read_source(file_path)
    except OSError as error:
        return file_path, [], [], str(error)
    masked = mask_comments_and_strings(source)
    rules = [RULES_BY_ID[rule_id] for rule_id in rule_ids]
    findings = [{"file": file_path, **f} for f in scan_masked(source, masked, rules)]
    return file_path, findings, collect_syntax_units(file_path, source, masked), None


def _find_atom_uses(
    task: tuple[str, tuple[str, ...]],
) -> tuple[str, list[tuple[str, int, int, int, str]]]:
    """
    Second pass over one file: where tainted syntax atoms are used.

    :param task: File path and the tainted atoms.
    :return: File path and uses as (atom, offset, 0-indexed line, 1-indexed column, line text).
    """
    file_path, atoms = task
    try:
        source = _read_source(file_path)
    except OSError:
        return file_path, []
    present = [atom for atom in atoms if atom.split()[0] in source]
    if not present:
        return file_path, []
    masked = mask_comments_and_strings(source)
    line_starts = _line_starts(source)
    original_lines = source.splitlines()
    uses = []
    for atom in present:
        for match in _reference_pattern(atom).finditer(masked):
            line_index = bisect.bisect_right(line_starts, match.start()) - 1
            text = original_lines[line_index].strip() if line_index < len(original_lines) else ""
            column = match.start() - line_starts[line_index] + 1
            uses.append((atom, match.start(), line_index, column, text[:200]))
    return file_path, uses


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

    The first pass applies the pattern rules and collects custom syntax definitions.
    Syntax whose definition contains a traced construct is then followed to its uses
    in a second pass, which reads only files that contain one of the tainted atoms.

    :param files: `.lean` files to scan.
    :param rules: Enabled rules (pattern rules and derived `*-via-syntax` rules).
    :param fail_on: Lowest severity that counts as a failure; `never` always passes.
    :param jobs: Number of worker processes; 1 scans in this process.
    :return: Report for JSON output.
    """
    rule_ids = tuple(rule.rule_id for rule in rules if rule.pattern is not None)
    enabled = {rule.rule_id for rule in rules}

    findings: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    units: list[SyntaxUnit] = []
    for file_path, file_findings, file_units, error in _map_tasks(
        _analyze_file, [(f, rule_ids) for f in files], jobs
    ):
        if error is not None:
            unreadable.append({"file": file_path, "error": error})
            continue
        findings.extend(file_findings)
        units.extend(file_units)

    tainted = trace_syntax(units)
    traced_syntax = []
    if tainted:
        atoms = tuple(sorted(tainted))
        # A definition's own text (e.g. the quotation pattern of `elab_rules`) is not a use.
        defining_spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for atom, entry in tainted.items():
            for unit in entry["definitions"]:
                defining_spans.setdefault((unit.file, atom), []).append((unit.start, unit.end))
        use_counts = {atom: 0 for atom in atoms}
        seen: set[tuple[str, str, int]] = set()
        for file_path, uses in _map_tasks(_find_atom_uses, [(f, atoms) for f in files], jobs):
            for atom, offset, line_index, column, text in uses:
                spans = defining_spans.get((file_path, atom), [])
                if any(start <= offset < end for start, end in spans):
                    continue
                use_counts[atom] += 1
                definition = tainted[atom]["definitions"][0]
                for source_rule in sorted(tainted[atom]["sources"]):
                    rule_id = source_rule + VIA_SYNTAX_SUFFIX
                    key = (file_path, rule_id, line_index)
                    if rule_id not in enabled or key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        {
                            "file": file_path,
                            "line": line_index + 1,
                            "column": column,
                            "rule": rule_id,
                            "severity": RULES_BY_ID[rule_id].severity,
                            "text": text,
                            "via": atom,
                            "defined_at": f"{definition.file}:{definition.line}",
                        }
                    )
        for atom in atoms:
            traced_syntax.append(
                {
                    "atom": atom,
                    "sources": sorted(tainted[atom]["sources"]),
                    "defined_at": [f"{u.file}:{u.line}" for u in tainted[atom]["definitions"]],
                    "use_count": use_counts[atom],
                }
            )
    findings.sort(key=lambda f: (f["file"], f["line"], f["column"]))

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
        "traced_syntax": traced_syntax,
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
            f"  [{entry['severity']:<8}] {entry['rule']:<35} {entry['count']:>7} / {entry['file_count']}"
        )

    if report["traced_syntax"]:
        lines.append("")
        lines.append("Custom syntax hiding traced constructs (atom: constructs; definitions; uses):")
        for entry in report["traced_syntax"]:
            lines.append(
                f"  `{entry['atom']}`: {', '.join(entry['sources'])}; "
                f"{', '.join(entry['defined_at'])}; {entry['use_count']} use(s)"
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
            via = f"  (via `{f['via']}`, defined at {f['defined_at']})" if "via" in f else ""
            lines.append(
                f"  {f['file']}:{f['line']}:{f['column']}: {f['severity']}: [{f['rule']}] {f['text']}{via}"
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
            "(sorry, axioms, native evaluation, elaborator bypass, environment hacking, global notation), "
            "and follow custom syntax that hides them to the places that use it."
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
        for rule in ALL_RULES:
            print(f"[{rule.severity:<8}] {rule.rule_id:<35} {rule.description}")
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

    rules = [rule for rule in ALL_RULES if rule.rule_id not in set(args.ignore_rule)]
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
