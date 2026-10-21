#!/usr/bin/env python3
"""
Lean 4 and Lake build/typecheck output parser.

Extracts diagnostic messages (errors, warnings, infos) from stdin,
log files, or command execution results, and outputs structured JSON.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

# Regex pattern to strip ANSI color escape sequences.
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Regex pattern matching direct Lean 4 compiler output (path:line:col: severity: message).
# Handles Windows absolute paths with drive letters (e.g. C:\path\to\File.lean:12:4: error: ...).
# e.g.: /path/to/File.lean:12:4: error: type mismatch
# e.g.: C:\path\to\File.lean:12:4: warning: unused variable `x`
DIAGNOSTIC_HEADER_LEAN_RE = re.compile(
    r"^\s*(?P<file>(?:[a-zA-Z]:)?[^:\n\r]+):(?P<line>\d+):(?P<col>\d+):\s+(?P<severity>error|warning|info):\s*(?P<message>.*)$",
    re.IGNORECASE,
)

# Regex pattern matching Lake build output (severity: path:line:col: message).
# Handles Windows absolute paths with drive letters.
# e.g.: warning: MathProof/Algebra/Group.lean:32:2: `simp` is a flexible tactic
# e.g.: error: C:\path\to\Basic.lean:10:4: type mismatch
DIAGNOSTIC_HEADER_LAKE_RE = re.compile(
    r"^\s*(?P<severity>error|warning|info):\s+(?P<file>(?:[a-zA-Z]:)?[^:\n\r]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<message>.*)$",
    re.IGNORECASE,
)

# Regex pattern matching generic Lake error/warning lines without file positions.
# e.g.: error: build failed
# e.g.: error: > lean --make ... failed
LAKE_GENERIC_ERROR_RE = re.compile(
    r"^\s*(?P<severity>error|warning|info):\s*(?P<message>.*)$",
    re.IGNORECASE,
)

# Lake progress lines (e.g., "[2071/2071] Built ...") and build summary lines.
LAKE_PROGRESS_OR_STATUS_RE = re.compile(
    r"^\s*(?:(?:[⚠ℹ✔✖]\s*)?\[\d+/\d+\].*|Build (?:completed|failed).*)$",
    re.IGNORECASE,
)

# Regex pattern matching Lean `#print axioms` output lines.
# e.g.: 'MyModule.my_theorem' depends on axioms: [propext]
# e.g.: 'MyModule.my_theorem' does not depend on any axioms
LEAN_AXIOM_PRINT_RE = re.compile(
    r"^\s*'(?:[^'\n\r]+)'\s+(?:depends on axioms:|does not depend on any axioms)",
    re.IGNORECASE,
)

# Regex pattern matching other Lean top-level command prints (#check, #print, etc.).
# e.g.: 'MyModule.foo' : Nat -> Nat
# e.g.: def MyModule.foo : ...
LEAN_TOPLEVEL_PRINT_RE = re.compile(
    r"^\s*(?:'(?:[^'\n\r]+)'\s*:|(?:def|theorem|inductive|structure|class)\s+[a-zA-Z0-9_.]+\s*:)",
)


def strip_ansi(text: str) -> str:
    """
    Remove ANSI escape sequences from a string.

    :param text: Input string.
    :return: String with ANSI escape sequences removed.
    """
    return ANSI_ESCAPE_RE.sub("", text)


def parse_build_output(raw_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Parse console output from Lean 4 and Lake, separating diagnostics from top-level command prints.

    :param raw_text: Raw compiler or build output text.
    :return: Tuple of (structured diagnostics list, list of non-diagnostic print/command output strings).
    """
    clean_text = strip_ansi(raw_text)
    lines = clean_text.splitlines()

    diagnostics: list[dict[str, Any]] = []
    prints: list[str] = []
    current_diag: dict[str, Any] | None = None
    in_print_block: bool = False

    def flush_current():
        """Finalize and append the accumulated diagnostic object to the list."""
        nonlocal current_diag
        if current_diag is not None:
            # Strip trailing whitespace and newlines from the message.
            current_diag["message"] = current_diag["message"].strip()
            diagnostics.append(current_diag)
            current_diag = None

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            # Treat empty lines as paragraph breaks in multi-line messages.
            if current_diag is not None:
                current_diag["message"] += "\n"
            in_print_block = False
            continue

        # Ignore Lake progress and status lines.
        if LAKE_PROGRESS_OR_STATUS_RE.match(line):
            flush_current()
            in_print_block = False
            continue

        # 1. Match standard direct Lean diagnostic line (path:line:col: severity: message).
        lean_match = DIAGNOSTIC_HEADER_LEAN_RE.match(line)
        if lean_match:
            flush_current()
            in_print_block = False
            current_diag = {
                "file": lean_match.group("file").strip(),
                "line": int(lean_match.group("line")),
                "column": int(lean_match.group("col")),
                "severity": lean_match.group("severity").lower(),
                "message": lean_match.group("message"),
            }
            continue

        # 2. Match Lake build diagnostic line (severity: path:line:col: message).
        lake_file_match = DIAGNOSTIC_HEADER_LAKE_RE.match(line)
        if lake_file_match:
            flush_current()
            in_print_block = False
            current_diag = {
                "file": lake_file_match.group("file").strip(),
                "line": int(lake_file_match.group("line")),
                "column": int(lake_file_match.group("col")),
                "severity": lake_file_match.group("severity").lower(),
                "message": lake_file_match.group("message"),
            }
            continue

        # 3. Match generic Lake error/warning line without file position.
        lake_generic_match = LAKE_GENERIC_ERROR_RE.match(line)
        if lake_generic_match:
            flush_current()
            in_print_block = False
            current_diag = {
                "file": None,
                "line": None,
                "column": None,
                "severity": lake_generic_match.group("severity").lower(),
                "message": lake_generic_match.group("message"),
            }
            continue

        # 4. Check for top-level non-diagnostic prints (#print axioms, #check, #print, etc.).
        if LEAN_AXIOM_PRINT_RE.match(line) or LEAN_TOPLEVEL_PRINT_RE.match(line):
            flush_current()
            in_print_block = True
            prints.append(stripped_line)
            continue

        if in_print_block:
            # Continuation line for print block (e.g., multi-line axiom list [..., ...])
            prints.append(stripped_line)
            continue

        # 5. Continuation lines for the current diagnostic (stack traces, details, etc.).
        if current_diag is not None:
            current_diag["message"] += "\n" + line
        else:
            # Handle critical lines outside diagnostic headers (e.g. panics, uncaught exceptions).
            if "panic at" in line or "uncaught exception" in line.lower():
                current_diag = {
                    "file": None,
                    "line": None,
                    "column": None,
                    "severity": "error",
                    "message": line,
                }
            elif stripped_line.startswith("'") and (
                "depends on" in stripped_line or "does not depend" in stripped_line
            ):
                prints.append(stripped_line)

    flush_current()
    return diagnostics, prints


def parse_diagnostics_text(raw_text: str) -> list[dict[str, Any]]:
    """
    Parse console output from Lean 4 and Lake, returning a list of diagnostics.
    Maintains backward compatibility by extracting only the diagnostic list.

    :param raw_text: Raw compiler or build output text.
    :return: List of structured diagnostic dictionaries.
    """
    diagnostics, _ = parse_build_output(raw_text)
    return diagnostics


def run_command_and_capture(command: str) -> tuple[int, str]:
    """
    Execute a shell command and capture its exit code and combined stdout/stderr.

    :param command: Shell command string to execute.
    :return: Tuple of (exit code, combined stdout and stderr).
    """
    process = subprocess.run(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.returncode, process.stdout


def main():
    """Parse command-line arguments and run diagnostic parser."""
    parser = argparse.ArgumentParser(
        description="Parse Lean 4 and Lake build/diagnostic output into structured JSON.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to a log file to parse (reads from stdin if not specified).",
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run the specified command and parse its output directly (e.g. --run 'lake build').",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Output only the summary, omitting detailed diagnostic list.",
    )

    args = parser.parse_args()

    exit_code = 0
    raw_output = ""

    if args.run:
        exit_code, raw_output = run_command_and_capture(args.run)
    elif args.file:
        if not os.path.exists(args.file):
            print(
                json.dumps(
                    {
                        "success": False,
                        "exit_code": 1,
                        "error_count": 1,
                        "warning_count": 0,
                        "info_count": 0,
                        "diagnostics": [
                            {
                                "file": args.file,
                                "line": None,
                                "column": None,
                                "severity": "error",
                                "message": f"Log file not found: {args.file}",
                            }
                        ],
                        "summary": f"Error: Log file not found: {args.file}",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            raw_output = f.read()
    else:
        # Read from standard input if piped or redirected.
        if not sys.stdin.isatty():
            raw_output = sys.stdin.read()
        else:
            parser.print_help()
            sys.exit(0)

    diagnostics, prints = parse_build_output(raw_output)

    error_count = sum(1 for d in diagnostics if d["severity"] == "error")
    warning_count = sum(1 for d in diagnostics if d["severity"] == "warning")
    info_count = sum(1 for d in diagnostics if d["severity"] == "info")

    success = (exit_code == 0) and (error_count == 0)

    result: dict[str, Any] = {
        "success": success,
        "exit_code": exit_code,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "summary": f"{error_count} error(s), {warning_count} warning(s), {info_count} info(s)",
    }

    if not args.summary_only:
        result["diagnostics"] = diagnostics
        if prints:
            result["prints"] = prints

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
