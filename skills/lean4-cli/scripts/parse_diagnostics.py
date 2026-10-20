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
from typing import Any, Dict, List, Optional, Tuple


# Regex pattern to strip ANSI color escape sequences.
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Regex pattern matching standard Lean 4 diagnostic lines.
# e.g.: /path/to/File.lean:12:4: error: type mismatch
# e.g.: File.lean:12:4: warning: unused variable `x`
DIAGNOSTIC_HEADER_RE = re.compile(
    r"^(?P<file>[^:\n\r]+):(?P<line>\d+):(?P<col>\d+):\s+(?P<severity>error|warning|info):\s*(?P<message>.*)$",
    re.IGNORECASE,
)

# Regex pattern matching generic Lake error/warning lines.
# e.g.: error: build failed
# e.g.: error: > lean --make ... failed
LAKE_GENERIC_ERROR_RE = re.compile(
    r"^(?P<severity>error|warning|info):\s*(?P<message>.*)$",
    re.IGNORECASE,
)


def strip_ansi(text: str) -> str:
    """
    Remove ANSI escape sequences from a string.

    :param text: Input string.
    :return: String with ANSI escape sequences removed.
    """
    return ANSI_ESCAPE_RE.sub("", text)


def parse_diagnostics_text(raw_text: str) -> List[Dict[str, Any]]:
    """
    Parse console output from Lean 4 and Lake, returning a list of diagnostics.

    :param raw_text: Raw compiler or build output text.
    :return: List of structured diagnostic dictionaries.
    """
    clean_text = strip_ansi(raw_text)
    lines = clean_text.splitlines()

    diagnostics: List[Dict[str, Any]] = []
    current_diag: Optional[Dict[str, Any]] = None

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
            continue

        # 1. Match standard diagnostic line with file position.
        file_match = DIAGNOSTIC_HEADER_RE.match(line)
        if file_match:
            flush_current()
            current_diag = {
                "file": file_match.group("file").strip(),
                "line": int(file_match.group("line")),
                "column": int(file_match.group("col")),
                "severity": file_match.group("severity").lower(),
                "message": file_match.group("message"),
            }
            continue

        # 2. Match generic Lake error/warning line without file position.
        lake_match = LAKE_GENERIC_ERROR_RE.match(line)
        if lake_match:
            # Record Lake generic notifications as independent diagnostic entries.
            flush_current()
            current_diag = {
                "file": None,
                "line": None,
                "column": None,
                "severity": lake_match.group("severity").lower(),
                "message": lake_match.group("message"),
            }
            continue

        # 3. Continuation lines for the current diagnostic (stack traces, details, etc.).
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

    flush_current()
    return diagnostics


def run_command_and_capture(command: str) -> Tuple[int, str]:
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

    diagnostics = parse_diagnostics_text(raw_output)

    error_count = sum(1 for d in diagnostics if d["severity"] == "error")
    warning_count = sum(1 for d in diagnostics if d["severity"] == "warning")
    info_count = sum(1 for d in diagnostics if d["severity"] == "info")

    success = (exit_code == 0) and (error_count == 0)

    result: Dict[str, Any] = {
        "success": success,
        "exit_code": exit_code,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "summary": f"{error_count} error(s), {warning_count} warning(s), {info_count} info(s)",
    }

    if not args.summary_only:
        result["diagnostics"] = diagnostics

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
