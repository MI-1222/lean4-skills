#!/usr/bin/env python3
"""
LeanSearch Semantic Search Client for Lean 4 and Mathlib.
Searches Mathlib declarations and theorems by natural language mathematical concepts
(e.g., "Banach-Steinhaus theorem", "Heine-Borel compactness", "order of element divides group order")
using the LeanSearch REST API (https://leansearch.net).
Uses only the Python 3 standard library.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_API_URL = "https://leansearch.net/search"
USER_AGENT = "LeanMathlibSearchAgent/1.0 (Autonomous Theorem Prover; LeanSearch Client)"


def search_leansearch(
    query: str,
    api_url: str = DEFAULT_API_URL,
    limit: int = 10,
    timeout: float = 15.0,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Execute natural language search using the LeanSearch REST API."""
    payload = json.dumps({"query": [query], "num_results": limit}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw_data = response.read().decode("utf-8")
                parsed = json.loads(raw_data)

                # The API returns a list of result lists (one list per query string in batch)
                result_batch = parsed[0] if (isinstance(parsed, list) and len(parsed) > 0) else []
                hits: list[dict[str, Any]] = []

                for item in result_batch:
                    res_obj = item.get("result", {})
                    name_parts = res_obj.get("name", [])
                    name = ".".join(name_parts) if isinstance(name_parts, list) else str(name_parts)

                    module_parts = res_obj.get("module_name", [])
                    module = ".".join(module_parts) if isinstance(module_parts, list) else str(module_parts)

                    hits.append({
                        "name": name,
                        "module": module,
                        "kind": res_obj.get("kind", ""),
                        "type": res_obj.get("type", "").strip(),
                        "signature": res_obj.get("signature", "").strip(),
                        "informal_name": res_obj.get("informal_name"),
                        "informal_description": res_obj.get("informal_description"),
                        "distance": item.get("distance"),
                    })

                if limit > 0:
                    hits = hits[:limit]

                return {
                    "success": True,
                    "source": "leansearch",
                    "query": query,
                    "count": len(hits),
                    "hits": hits,
                    "error": None,
                }
        except urllib.error.HTTPError as http_err:
            if http_err.code == 503 and attempt < max_retries - 1:
                continue
            return {
                "success": False,
                "source": "leansearch",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"HTTP {http_err.code}: {http_err.reason}",
            }
        except urllib.error.URLError as url_err:
            return {
                "success": False,
                "source": "leansearch",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"Network error: {url_err.reason}",
            }
        except json.JSONDecodeError as json_err:
            return {
                "success": False,
                "source": "leansearch",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"Invalid JSON response from server: {json_err}",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "source": "leansearch",
                "query": query,
                "count": 0,
                "hits": [],
                "error": f"Unexpected error during search: {exc}",
            }

    return {
        "success": False,
        "source": "leansearch",
        "query": query,
        "count": 0,
        "hits": [],
        "error": f"Failed after {max_retries} retry attempts.",
    }


def format_text_output(result: dict[str, Any]) -> str:
    """Format LeanSearch results into human and LLM-friendly plain text."""
    lines: list[str] = []
    query = result.get("query", "")
    source = result.get("source", "leansearch").upper()

    if not result.get("success"):
        lines.append(f"LeanSearch Query Failed ({source}):")
        lines.append(f"  Query: {query}")
        lines.append(f"  Error: {result.get('error')}")
        return "\n".join(lines)

    total_count = result.get("count", 0)
    hits = result.get("hits", [])

    lines.append(f"LeanSearch Results [{source}] for: \"{query}\"")
    lines.append(f"Matched {total_count} declaration(s):")
    lines.append("=" * 70)

    if not hits:
        lines.append("No matching declarations found.")
        return "\n".join(lines)

    for idx, hit in enumerate(hits, start=1):
        name = hit.get("name", "")
        module = hit.get("module", "")
        kind = hit.get("kind", "")
        decl_type = hit.get("type", "")
        informal_name = hit.get("informal_name")
        informal_desc = hit.get("informal_description")
        distance = hit.get("distance")

        score_str = f" [Distance: {distance:.4f}]" if isinstance(distance, (int, float)) else ""
        lines.append(f"{idx}. {name} ({kind}){score_str}")
        if module:
            lines.append(f"   Module  : {module}  (use `import {module}`)")
        if decl_type:
            # Wrap or truncate multiline types if excessively long
            lines.append(f"   Type    : {decl_type}")
        if informal_name:
            lines.append(f"   Concept : {informal_name}")
        if informal_desc:
            clean_desc = informal_desc.strip().replace("\n", " ")
            if len(clean_desc) > 160:
                clean_desc = clean_desc[:157] + "..."
            lines.append(f"   Summary : {clean_desc}")
        lines.append("-" * 70)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search Mathlib declarations by natural language mathematical concepts via LeanSearch REST API."
    )
    parser.add_argument("query", type=str, help="Natural language query (e.g., 'Heine-Borel theorem')")
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
        "--api-url",
        type=str,
        default=DEFAULT_API_URL,
        help=f"Base URL for LeanSearch API (default: {DEFAULT_API_URL}).",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=15.0,
        help="Query timeout in seconds (default: 15.0).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Max retries on HTTP 503 or transient network failure (default: 3).",
    )

    args = parser.parse_args()

    result = search_leansearch(
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
