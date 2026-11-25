#!/usr/bin/env python3
"""
Measure the longest import chain (the critical path) of a Lean 4 project.

Lake builds a module only after every module it imports is built, so the modules on the
longest chain of imports are built one after another, however many cores the machine has.
The length of that chain is a lower bound on the number of sequential steps of every build
of the project, and each step pays at least the time to load its imports. The report also
gives the parallelism, the number of modules divided by the chain length: if all modules took
equally long, a build could keep at most about that many cores busy on average, so on a machine
with more cores the chain, not the core count, sets the build time.

The script reads only the header of each `.lean` file (`module`, `prelude` and the `import`
lines, including `public`, `meta` and `all`), so it needs no build: 9,000 files take seconds,
175,000 about a minute. Imports of modules outside the scanned source directories (Mathlib,
`Init`, other dependencies) are not part of the chain, because a cache provides them.

Usage:

    python3 import_depth.py src                       # every module under src/
    python3 import_depth.py src --to Main             # only the import closure of Main
    python3 import_depth.py src --max-depth 40        # exit code 1 if the chain is longer
    python3 import_depth.py src --json                # structured output

Each positional argument is a source directory, i.e. the `srcDir` of a Lake package or the
directory that contains the top-level module folders. Module names are the file paths relative
to it (`src/MyProject/Basic.lean` is `MyProject.Basic` when the argument is `src`).

Exit codes: 0 on success, 1 when `--max-depth` is exceeded, 2 on usage errors or when the
sources contain an import cycle.
"""

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field

# Directory names skipped while collecting source files.
EXCLUDED_DIRS = {".lake", ".git", "lake-packages", "__pycache__"}

# Characters that may appear in an unescaped identifier component (besides letters and digits).
IDENT_EXTRA_CHARS = "_'!?"

# Bytes read at a time from a source file; the header is usually in the first chunk.
READ_CHUNK = 16384

# Characters that must follow the end of the header in the prefix read so far; otherwise the
# prefix may end inside the header and more of the file is read.
HEADER_MARGIN = 1024

# Number of chain modules shown in text output before the middle is elided.
TEXT_CHAIN_ROWS = 400


@dataclass
class Module:
    """
    A module found in a scanned source directory.

    :param name: Module name, e.g. `MyProject.Basic`.
    :param path: Path of the source file.
    :param imports: Names of all imported modules, in source order, without duplicates.
    """

    name: str
    path: str
    imports: list[str] = field(default_factory=list)


@dataclass
class DepthResult:
    """
    Longest import chains of a set of modules.

    :param depth: Number of modules on the longest chain that ends at each module (1 if it
        imports no scanned module).
    :param previous: For each module, the imported module that precedes it on its longest
        chain, or `None`.
    :param cycle: Modules that lie on or behind an import cycle; empty for a valid project.
    """

    depth: dict[str, int]
    previous: dict[str, str | None]
    cycle: list[str]


def is_ident_start(char: str) -> bool:
    """
    Returns true if `char` may start an unescaped identifier component.

    :param char: One character.
    :return: True for letters (including non-ASCII letters such as Greek) and `_`.
    """
    return char.isalpha() or char == "_"


def is_ident_rest(char: str) -> bool:
    """
    Returns true if `char` may continue an unescaped identifier component.

    :param char: One character.
    :return: True for letters, digits, subscripts and `_ ' ! ?`.
    """
    return char.isalnum() or char in IDENT_EXTRA_CHARS or "₀" <= char <= "ₜ"


def join_components(components: list[str]) -> str:
    """
    Joins name components into a module name, escaping the ones that are not identifiers.

    Both the names read from `import` lines and the names derived from file paths go through
    this function, so `import P.«my-dir».B` matches the file `P/my-dir/B.lean`.

    :param components: Unescaped name components.
    :return: The module name as Lean prints it, e.g. `P.«my-dir».B`.
    """
    escaped = []
    for component in components:
        plain = (
            component
            and is_ident_start(component[0])
            and all(map(is_ident_rest, component))
        )
        escaped.append(component if plain else f"«{component}»")
    return ".".join(escaped)


class HeaderParser:
    """
    Reads the header of a Lean 4 source file: `module`, `prelude` and the `import` commands.

    Comments are skipped, including nested block comments. Parsing stops at the first token
    that cannot belong to the header, as Lean's own header parser does.
    """

    def __init__(self, text: str):
        """
        :param text: Source text, or a prefix of it that contains the whole header.
        """
        self.text = text
        self.pos = 0

    def skip_trivia(self) -> bool:
        """
        Skips whitespace and comments.

        :return: False if the text ends inside a block comment, i.e. more text is needed.
        """
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char.isspace():
                self.pos += 1
            elif text.startswith("--", self.pos):
                newline = text.find("\n", self.pos)
                self.pos = len(text) if newline < 0 else newline + 1
            elif text.startswith("/-", self.pos):
                level = 1
                self.pos += 2
                while level > 0:
                    if self.pos >= len(text):
                        return False
                    if text.startswith("/-", self.pos):
                        level += 1
                        self.pos += 2
                    elif text.startswith("-/", self.pos):
                        level -= 1
                        self.pos += 2
                    else:
                        self.pos += 1
            else:
                break
        return True

    def read_word(self) -> str | None:
        """
        Reads an unescaped identifier component at the current position.

        :return: The word, or `None` if no identifier starts here.
        """
        start = self.pos
        text = self.text
        if start >= len(text) or not is_ident_start(text[start]):
            return None
        end = start + 1
        while end < len(text) and is_ident_rest(text[end]):
            end += 1
        self.pos = end
        return text[start:end]

    def peek_word(self) -> str | None:
        """
        Returns the word after the trivia at the current position without consuming it.

        :return: The next word, or `None`.
        """
        saved = self.pos
        self.skip_trivia()
        word = self.read_word()
        self.pos = saved
        return word

    def at_module_name(self) -> bool:
        """
        Returns true if a module name starts at the current position.

        :return: True if the next character starts an identifier or a `«...»` escape.
        """
        if self.pos >= len(self.text):
            return False
        char = self.text[self.pos]
        return char == "«" or is_ident_start(char)

    def read_module_name(self) -> str | None:
        """
        Reads a dotted module name.

        :return: The module name in the form of `join_components`, or `None` if no name
            starts here.
        """
        text = self.text
        parts: list[str] = []
        while True:
            if text.startswith("«", self.pos):
                close = text.find("»", self.pos + 1)
                if close < 0:
                    return None
                parts.append(text[self.pos + 1 : close])
                self.pos = close + 1
            else:
                word = self.read_word()
                if word is None:
                    break
                parts.append(word)
            if text.startswith(".", self.pos) and self.pos + 1 < len(text):
                following = text[self.pos + 1]
                if following == "«" or is_ident_start(following):
                    self.pos += 1
                    continue
            break
        return join_components(parts) if parts else None

    def parse(self) -> tuple[list[str], bool]:
        """
        Parses the header.

        :return: The imported module names in source order, and false if the text ended
            before the header did (so a longer prefix must be parsed).
        """
        imports: list[str] = []
        while True:
            if not self.skip_trivia() or self.pos >= len(self.text):
                return imports, False
            start = self.pos
            word = self.read_word()
            if word in ("module", "prelude") and not imports:
                continue
            # `public`, `meta` and `public meta` belong to the header only before `import`.
            if word == "public" and self.peek_word() == "meta":
                self.skip_trivia()
                word = self.read_word()
            if word in ("public", "meta") and self.peek_word() == "import":
                self.skip_trivia()
                word = self.read_word()
            if word != "import":
                self.pos = start
                return imports, True
            if not self.skip_trivia():
                return imports, False
            # `import all M` (module system) or `import runtime M` (older Lean versions).
            # The word is a modifier only if a module name follows it.
            before_modifier = self.pos
            if self.read_word() in ("all", "runtime"):
                if not self.skip_trivia():
                    return imports, False
                if not self.at_module_name():
                    self.pos = before_modifier
            else:
                self.pos = before_modifier
            name = self.read_module_name()
            if name is None:
                return imports, True
            if self.pos >= len(self.text):
                # The name may continue beyond this prefix.
                return imports, False
            imports.append(name)


def read_imports(path: str) -> list[str]:
    """
    Reads the imported module names from the header of a source file.

    :param path: Path of a `.lean` file.
    :return: The imported module names in source order, without duplicates.
    """
    text = ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        while True:
            chunk = handle.read(READ_CHUNK)
            text += chunk
            parser = HeaderParser(text)
            imports, complete = parser.parse()
            # A header that seems to end near the end of the prefix may be cut inside a word
            # (`publ`), so it is parsed again with more text unless the file has ended.
            if not chunk or (complete and parser.pos + HEADER_MARGIN < len(text)):
                return list(dict.fromkeys(imports))


def module_name(root: str, path: str) -> str:
    """
    Converts a source path into its module name.

    :param root: Source directory the module name is relative to.
    :param path: Path of a `.lean` file under `root`.
    :return: The module name, e.g. `MyProject.Basic`.
    """
    relative = os.path.relpath(path, root)
    return join_components(os.path.splitext(relative)[0].split(os.sep))


def collect_modules(roots: list[str]) -> tuple[dict[str, Module], list[str]]:
    """
    Collects every `.lean` file under the given source directories.

    :param roots: Source directories.
    :return: Modules by name, and warnings about module names found under two roots.
    """
    modules: dict[str, Module] = {}
    warnings: list[str] = []
    for root in roots:
        for directory, subdirs, files in os.walk(root):
            subdirs[:] = sorted(d for d in subdirs if d not in EXCLUDED_DIRS)
            for filename in sorted(files):
                if not filename.endswith(".lean"):
                    continue
                path = os.path.join(directory, filename)
                name = module_name(root, path)
                if name in modules:
                    warnings.append(
                        f"module {name} found twice: {modules[name].path} and {path}; "
                        "keeping the first"
                    )
                    continue
                modules[name] = Module(name, path, read_imports(path))
    return modules, warnings


def import_closure(modules: dict[str, Module], targets: list[str]) -> set[str]:
    """
    Computes the scanned modules that the targets import, directly or transitively.

    :param modules: Modules by name.
    :param targets: Names of the target modules, which must be in `modules`.
    :return: The targets and every scanned module they depend on.
    """
    closure: set[str] = set()
    stack = list(targets)
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        closure.add(name)
        stack.extend(i for i in modules[name].imports if i in modules)
    return closure


def longest_chains(modules: dict[str, Module], names: set[str]) -> DepthResult:
    """
    Computes the longest import chain that ends at each module, in topological order.

    :param modules: Modules by name.
    :param names: Modules to consider; imports outside this set are ignored.
    :return: Depths, predecessors on the longest chains, and the modules left by a cycle.
    """
    importers: dict[str, list[str]] = {name: [] for name in names}
    pending: dict[str, int] = {}
    for name in names:
        local = [i for i in modules[name].imports if i in names]
        pending[name] = len(local)
        for imported in local:
            importers[imported].append(name)
    depth: dict[str, int] = {}
    previous: dict[str, str | None] = {}
    ready = sorted(name for name, count in pending.items() if count == 0)
    for name in ready:
        depth[name] = 1
        previous[name] = None
    while ready:
        name = ready.pop()
        for importer in importers[name]:
            if depth[name] + 1 > depth.get(importer, 0):
                depth[importer] = depth[name] + 1
                previous[importer] = name
            pending[importer] -= 1
            if pending[importer] == 0:
                ready.append(importer)
    cycle = sorted(name for name, count in pending.items() if count > 0)
    return DepthResult(depth, previous, cycle)


def chain_to(result: DepthResult, last: str) -> list[str]:
    """
    Reconstructs the longest chain that ends at a module.

    :param result: Result of `longest_chains`.
    :param last: Module at the end of the chain.
    :return: Module names from the start of the chain to `last`.
    """
    chain = [last]
    while (before := result.previous[chain[-1]]) is not None:
        chain.append(before)
    return chain[::-1]


def build_report(
    modules: dict[str, Module], names: set[str], result: DepthResult, top: int
) -> dict:
    """
    Builds the report printed as text or JSON.

    :param modules: Modules by name.
    :param names: Modules that were measured.
    :param result: Result of `longest_chains`.
    :param top: Number of deepest modules to list.
    :return: The report.
    """
    edges = sum(1 for name in names for i in modules[name].imports if i in names)
    external = Counter(
        i.split(".")[0]
        for name in names
        for i in modules[name].imports
        if i not in modules
    )
    if not result.depth:
        return {"module_count": len(names), "max_depth": 0, "chain": []}
    last = max(result.depth, key=lambda name: (result.depth[name], name))
    chain = chain_to(result, last)
    per_depth = Counter(result.depth.values())
    deepest = sorted(result.depth, key=lambda name: (-result.depth[name], name))[:top]
    return {
        "module_count": len(names),
        "import_edge_count": edges,
        "external_import_roots": dict(external.most_common()),
        "max_depth": len(chain),
        "parallelism": round(len(names) / len(chain), 1),
        "modules_per_depth": {str(d): per_depth[d] for d in sorted(per_depth)},
        "chain": [{"module": name, "path": modules[name].path} for name in chain],
        "deepest_modules": [
            {"module": name, "depth": result.depth[name]} for name in deepest
        ],
    }


def print_text(report: dict, max_depth: int | None) -> None:
    """
    Prints the report for a human reader.

    :param report: Result of `build_report`.
    :param max_depth: Limit given with `--max-depth`, or `None`.
    """
    edges = report.get("import_edge_count", 0)
    print(f"Modules: {report['module_count']}, imports between them: {edges}")
    external = report.get("external_import_roots", {})
    if external:
        roots = ", ".join(
            f"{root} ({count})" for root, count in list(external.items())[:8]
        )
        print(f"Imports outside the scanned directories (not counted): {roots}")
    depth = report["max_depth"]
    print(f"Longest import chain: {depth} module(s)")
    if depth:
        print(f"Parallelism (modules / chain length): {report['parallelism']}")
        chain = report["chain"]
        half = TEXT_CHAIN_ROWS // 2
        for index, entry in enumerate(chain, start=1):
            if len(chain) > TEXT_CHAIN_ROWS and half < index <= len(chain) - half:
                if index == half + 1:
                    print(
                        f"  ... {len(chain) - TEXT_CHAIN_ROWS} modules omitted (use --json)"
                    )
                continue
            print(f"  {index:>4}. {entry['module']}")
    if max_depth is not None:
        verdict = "over" if depth > max_depth else "within"
        print(f"Limit: {max_depth} modules, chain is {verdict} the limit")


def main() -> int:
    """
    Command-line entry point.

    :return: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Measure the longest import chain (critical path) of a Lean 4 project."
    )
    parser.add_argument(
        "roots", nargs="*", default=["."], help="source directories (default: .)"
    )
    parser.add_argument(
        "--to",
        action="append",
        default=[],
        metavar="MODULE",
        help="measure only the import closure of this module (repeatable)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        metavar="N",
        help="exit with code 1 if the longest chain has more than N modules",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        metavar="N",
        help="deepest modules listed in JSON (default: 20)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    for root in args.roots:
        if not os.path.isdir(root):
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 2
    modules, warnings = collect_modules(args.roots)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    missing = [name for name in args.to if name not in modules]
    if missing:
        print(
            f"error: module not found under the source directories: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2
    names = import_closure(modules, args.to) if args.to else set(modules)
    result = longest_chains(modules, names)
    if result.cycle:
        print(
            f"error: import cycle among {len(result.cycle)} module(s), e.g. "
            + ", ".join(result.cycle[:5]),
            file=sys.stderr,
        )
        return 2
    report = build_report(modules, names, result, args.top)
    if args.json:
        if args.max_depth is not None:
            report["limit"] = args.max_depth
            report["within_limit"] = report["max_depth"] <= args.max_depth
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_text(report, args.max_depth)
    if args.max_depth is not None and report["max_depth"] > args.max_depth:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
