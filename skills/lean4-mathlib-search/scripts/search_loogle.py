#!/usr/bin/env python3
"""
Loogle Search Client for Lean 4 and Mathlib.
Searches Mathlib definitions, theorems, and lemmas by type signatures, constants,
and subexpression patterns using either the Loogle REST API or a local loogle CLI / lake exe loogle.
Uses only the Python 3 standard library.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API_URL = "https://loogle.lean-lang.org/json"
USER_AGENT = "LeanMathlibSearchAgent/1.0 (Autonomous Theorem Prover)"


def find_local_loogle_runner(
    lake_dir: str | None = None,
) -> tuple[list[str], Path | None] | None:
    """
    Locate a local loogle invocation command and working directory.
    Returns (cmd_args, working_directory) if found, otherwise None.
    """
    # 1. Explicit directory passed via CLI
    if lake_dir:
        target_path = Path(lake_dir).expanduser().resolve()
        if target_path.is_dir():
            return (["lake", "exe", "loogle"], target_path)

    # 2. Environment variable LOOGLE_PROJECT_DIR
    env_dir = os.environ.get("LOOGLE_PROJECT_DIR")
    if env_dir:
        target_path = Path(env_dir).expanduser().resolve()
        if target_path.is_dir():
            return (["lake", "exe", "loogle"], target_path)

    # 3. Check current working directory and ancestors for a Lake project with loogle
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        has_lake = (parent / "lakefile.lean").exists() or (
            parent / "lakefile.toml"
        ).exists()
        if has_lake:
            loogle_pkg = parent / ".lake" / "packages" / "loogle"
            if loogle_pkg.exists() or (parent / "Loogle").exists():
                return (["lake", "exe", "loogle"], parent)

    # 4. Check if `loogle` binary exists on PATH
    loogle_bin = shutil.which("loogle")
    if loogle_bin:
        return ([loogle_bin], None)

    return None


def extract_loogle_json(raw_output: str) -> dict[str, Any] | None:
    """
    Extract a valid Loogle JSON payload from command output,
    ignoring compiler progress indicators, lake replay messages, and warnings.
    """
    # Try parsing line by line from the end (JSON is usually the final line)
    for line in reversed(raw_output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict) and (
                    "hits" in data or "error" in data or "count" in data
                ):
                    return data
            except json.JSONDecodeError:
                continue

    # Try regex match across entire output
    match = re.search(r'\{.*"(?:hits|error|count)".*\}', raw_output, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


def search_via_local_cli(
    query: str,
    limit: int = 10,
    timeout: float = 20.0,
    lake_dir: str | None = None,
) -> dict[str, Any]:
    """Execute search using a locally installed `loogle` CLI or `lake exe loogle`."""
    runner = find_local_loogle_runner(lake_dir)
    if not runner:
        return {
            "success": False,
            "source": "local",
            "query": query,
            "count": 0,
            "hits": [],
            "error": "Local 'loogle' executable or Lake project with loogle not found.",
        }

    cmd_base, work_dir = runner
    cmd = cmd_base + ["--json", query]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
            cwd=str(work_dir) if work_dir else None,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "source": "local",
            "query": query,
            "count": 0,
            "hits": [],
            "error": (
                f"Local loogle search timed out after {timeout} seconds.\n"
                "Hint: If loogle is being compiled for the first time, pre-build it using "
                "'lake build loogle' or run with '--timeout 180'."
            ),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "success": False,
            "source": "local",
            "query": query,
            "count": 0,
            "hits": [],
            "error": f"Failed to execute local loogle ({' '.join(cmd)}): {exc}",
        }

    raw_output = proc.stdout.strip()
    data = extract_loogle_json(raw_output)

    if data is None:
        # Fallback to parsing plain text if JSON extraction failed
        hits = []
        for line in raw_output.splitlines():
            line_str = line.strip()
            # Skip compiler warnings and progress bars
            if line_str.startswith(("⚠", "warning:")) or "Running job" in line_str:
                continue
            if line_str.startswith("Found ") or "declarations mentioning" in line_str:
                continue
            if line_str and not line_str.startswith("Of these"):
                # Clean up format like: "Real.sin (from Mathlib...)"
                match_decl = re.match(r"^([^\s]+)(?:\s+\(from\s+([^\)]+)\))?", line_str)
                if match_decl:
                    hits.append(
                        {
                            "name": match_decl.group(1),
                            "type": "",
                            "module": match_decl.group(2) or "",
                            "doc": None,
                        }
                    )
                else:
                    hits.append(
                        {"name": line_str, "type": "", "module": "", "doc": None}
                    )

        if hits:
            if limit > 0:
                hits = hits[:limit]
            return {
                "success": True,
                "source": "local",
                "runner": " ".join(cmd_base),
                "cwd": str(work_dir) if work_dir else None,
                "query": query,
                "count": len(hits),
                "hits": hits,
                "error": None,
            }

        err_msg = (
            proc.stderr.strip()
            or raw_output
            or f"loogle exited with code {proc.returncode}"
        )
        if (
            "unknown executable loogle" in err_msg.lower()
            or "unknown executable `loogle`" in err_msg.lower()
        ):
            err_msg += (
                "\nHint: Even if '.lake/packages/loogle' exists, Lake requires 'loogle' to be "
                "explicitly declared as a direct dependency in the root package configuration.\n"
                "Add '[[require]] name = \"loogle\"' to lakefile.toml (or 'require loogle from ...' in lakefile.lean), "
                "then run 'lake update loogle && lake build loogle'."
            )
        return {
            "success": False,
            "source": "local",
            "query": query,
            "count": 0,
            "hits": [],
            "error": err_msg,
        }

    if "error" in data:
        return {
            "success": False,
            "source": "local",
            "runner": " ".join(cmd_base),
            "cwd": str(work_dir) if work_dir else None,
            "query": query,
            "count": 0,
            "hits": [],
            "error": data.get("error"),
            "suggestions": data.get("suggestions"),
        }

    raw_hits = data.get("hits", [])
    total_count = data.get("count", len(raw_hits))
    hits = []
    for hit in raw_hits:
        hits.append(
            {
                "name": hit.get("name", ""),
                "type": hit.get("type", "").strip(),
                "module": hit.get("module", ""),
                "doc": hit.get("doc"),
            }
        )
    if limit > 0:
        hits = hits[:limit]

    return {
        "success": True,
        "source": "local",
        "runner": " ".join(cmd_base),
        "cwd": str(work_dir) if work_dir else None,
        "query": query,
        "count": total_count,
        "hits": hits,
        "header": data.get("header"),
        "heartbeats": data.get("heartbeats"),
        "error": None,
    }


def search_via_rest_api(
    query: str,
    api_url: str = DEFAULT_API_URL,
    limit: int = 10,
    timeout: float = 15.0,
    max_retries: int = 3,
    default_backoff: float = 3.0,
) -> dict[str, Any]:
    """Execute search using the public Loogle REST API."""
    encoded_params = urllib.parse.urlencode({"q": query})
    target_url = f"{api_url}?{encoded_params}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    req = urllib.request.Request(target_url, headers=headers, method="GET")

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
                result_json = json.loads(payload)

                # Check if Loogle returned an engine-level elaboration/syntax error
                if "error" in result_json:
                    return {
                        "success": False,
                        "source": "api",
                        "query": query,
                        "count": 0,
                        "hits": [],
                        "error": result_json.get("error"),
                        "suggestions": result_json.get("suggestions"),
                    }

                raw_hits = result_json.get("hits", [])
                total_count = result_json.get("count", len(raw_hits))

                hits = []
                for hit in raw_hits:
                    hits.append(
                        {
                            "name": hit.get("name", ""),
                            "type": hit.get("type", "").strip(),
                            "module": hit.get("module", ""),
                            "doc": hit.get("doc"),
                        }
                    )

                if limit > 0:
                    hits = hits[:limit]

                return {
                    "success": True,
                    "source": "api",
                    "query": query,
                    "count": total_count,
                    "hits": hits,
                    "header": result_json.get("header"),
                    "heartbeats": result_json.get("heartbeats"),
                    "error": None,
                }

        except urllib.error.HTTPError as http_err:
            if http_err.code == 503:
                # Handle server load shedding with Retry-After header
                retry_header = http_err.headers.get("Retry-After")
                sleep_duration = (
                    float(retry_header) if retry_header else default_backoff
                )
                if attempt < max_retries - 1:
                    time.sleep(sleep_duration)
                    continue
                return {
                    "success": False,
                    "source": "api",
                    "query": query,
                    "count": 0,
                    "hits": [],
                    "error": f"Loogle server is busy (HTTP 503). Retried {max_retries} times.",
                }
            elif http_err.code == 403:
                return {
                    "success": False,
                    "source": "api",
                    "query": query,
                    "count": 0,
                    "hits": [],
                    "error": "HTTP 403 Forbidden: Access denied. User-Agent may have been restricted.",
                }
            else:
                return {
                    "success": False,
                    "source": "api",
                    "query": query,
                    "count": 0,
                    "hits": [],
                    "error": f"HTTP {http_err.code}: {http_err.reason}",
                }
        except urllib.error.URLError as url_err:
            return {
                "success": False,
                "source": "api",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"Network error: {url_err.reason}",
            }
        except json.JSONDecodeError as json_err:
            return {
                "success": False,
                "source": "api",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"Invalid JSON response from server: {json_err}",
            }
        except (TimeoutError, OSError, ValueError, RuntimeError) as exc:
            return {
                "success": False,
                "source": "api",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"Unexpected error during search: {exc}",
            }

    return {
        "success": False,
        "source": "api",
        "query": query,
        "count": 0,
        "hits": [],
        "error": f"Failed after {max_retries} retry attempts.",
    }


def format_text_output(result: dict[str, Any]) -> str:
    """Format search results into human and LLM-friendly plain text."""
    lines = []
    query = result.get("query", "")
    source = result.get("source", "unknown")
    runner = result.get("runner")
    cwd = result.get("cwd")

    if not result.get("success"):
        lines.append(f"Loogle Search Failed ({source}):")
        lines.append(f"  Query: {query}")
        err_str = str(result.get("error", ""))
        err_lines = err_str.splitlines()
        if len(err_lines) <= 1:
            lines.append(f"  Error: {err_str}")
        else:
            lines.append("  Error:")
            for err_l in err_lines:
                lines.append(f"    {err_l}")
        suggestions = result.get("suggestions")
        if suggestions:
            lines.append(f"  Suggestions: {suggestions}")
        return "\n".join(lines)

    total_count = result.get("count", 0)
    hits = result.get("hits", [])
    header = result.get("header")

    source_info = source.upper()
    if runner:
        source_info += f" via '{runner}'"
    if cwd:
        source_info += f" in {cwd}"

    lines.append(f"Loogle Search Results [{source_info}] for: {query}")
    if header:
        lines.append(f"Summary: {header.strip()}")
    lines.append(f"Matched {total_count} declaration(s) (showing top {len(hits)}):")
    lines.append("=" * 70)

    if not hits:
        lines.append("No matching declarations found.")
        return "\n".join(lines)

    for idx, hit in enumerate(hits, start=1):
        name = hit.get("name", "")
        decl_type = hit.get("type", "")
        module = hit.get("module", "")
        doc = hit.get("doc")

        lines.append(f"{idx}. {name}")
        if decl_type:
            lines.append(f"   Type   : {decl_type}")
        if module:
            lines.append(f"   Module : {module}")
        if doc:
            clean_doc = doc.strip().split("\n")[0]
            if len(clean_doc) > 100:
                clean_doc = clean_doc[:97] + "..."
            lines.append(f"   Doc    : {clean_doc}")
        lines.append("-" * 70)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search Mathlib definitions and theorems using Loogle (local Lake CLI and REST API)."
    )
    parser.add_argument(
        "query", type=str, help="Search query (e.g., 'Real.sqrt ?a * Real.sqrt ?a')"
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Maximum number of hits to display/return (default: 10, 0 for all).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full structured JSON.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force execution via local 'loogle' / 'lake exe loogle'.",
    )
    parser.add_argument(
        "--prefer-local",
        action="store_true",
        help="Use local 'loogle' / 'lake exe loogle' if available, falling back to REST API.",
    )
    parser.add_argument(
        "--lake-dir",
        type=str,
        default=None,
        help="Directory of Lake project containing loogle (e.g. /path/to/lake_project).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=DEFAULT_API_URL,
        help=f"Base URL for Loogle JSON API (default: {DEFAULT_API_URL}).",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=25.0,
        help="Query timeout in seconds (default: 25.0).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Max retries on HTTP 503 or network failure (default: 3).",
    )

    args = parser.parse_args()

    # Determine execution strategy
    use_local = False
    if args.local or args.lake_dir:
        use_local = True
    elif args.prefer_local:
        use_local = find_local_loogle_runner(args.lake_dir) is not None

    if use_local:
        result = search_via_local_cli(
            args.query,
            limit=args.limit,
            timeout=args.timeout,
            lake_dir=args.lake_dir,
        )
        # Fallback to API if prefer_local was used and local failed
        if not result["success"] and args.prefer_local:
            result = search_via_rest_api(
                query=args.query,
                api_url=args.api_url,
                limit=args.limit,
                timeout=args.timeout,
                max_retries=args.retries,
            )
    else:
        result = search_via_rest_api(
            query=args.query,
            api_url=args.api_url,
            limit=args.limit,
            timeout=args.timeout,
            max_retries=args.retries,
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_text_output(result))

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
