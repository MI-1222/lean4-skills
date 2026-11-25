#!/usr/bin/env python3
"""
Check the direction of imports between the libraries of a Lake package.

Lake resolves imports module by module. It builds libraries that import each other without
a warning, and it has no library setting that restricts which libraries a library may import
(checked on Lean v4.33.1, v4.35.0 and v4.36.0), so an intended order between `[[lean_lib]]`
blocks holds only if something checks it.

The script reads the libraries (`name`, `srcDir`, `roots`, `globs`) from `lakefile.toml`,
assigns every source file to the library that Lake builds it in, and reads the `import` lines
with `import_depth.py`, so it needs no build.

- Without `--allow`, it fails if libraries depend on each other in a cycle.
- With `--allow FILE`, it fails on every import that the file does not allow. The file is a
  JSON object with one entry per library: the other libraries that its modules may import.
  Imports within a library are always allowed. The lists are not transitive, and the graph
  they describe must have no cycle:

      {"Core": [], "Fields": ["Core"], "Main": ["Core", "Fields"]}

Usage:

    python3 library_dag.py                              # the package in the current directory
    python3 library_dag.py . --allow library-dag.json   # exit code 1 on a forbidden import
    python3 library_dag.py . --json                     # structured output

For a `lakefile.lean`, translate the configuration first and pass the result:

    lake translate-config toml /tmp/lakefile.toml
    python3 library_dag.py . --lakefile /tmp/lakefile.toml

Only the libraries of one package are checked: imports from dependencies and the modules of
`lean_exe` targets are not.

Exit codes: 0 on success, 1 on a forbidden import (or, without `--allow`, a cycle between
libraries), 2 on usage or configuration errors. Requires Python 3.11+.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass

try:
    import tomllib
except ModuleNotFoundError:
    print("error: library_dag.py needs Python 3.11 or later (tomllib)", file=sys.stderr)
    sys.exit(2)

# `python3 -I` and `-P` leave the script's directory out of the search path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import import_depth  # noqa: E402

# Number of modules named in a warning.
WARNING_EXAMPLES = 5


class ConfigError(Exception):
    """A lakefile or a list of allowed imports that cannot be used."""


@dataclass
class Library:
    """
    A `lean_lib` of the lakefile.

    :param name: Library name as written in the lakefile.
    :param source_dir: Directory that its module names are relative to.
    :param roots: Root module names.
    :param globs: Pairs of a module name and a suffix: `""` (that module), `"+"` (its
        submodules) or `"*"` (the module and its submodules).
    """

    name: str
    source_dir: str
    roots: list[str]
    globs: list[tuple[str, str]]

    def matches_glob(self, module: str) -> bool:
        """
        Returns true if one of the globs matches a module.

        :param module: Module name.
        :return: True for a match.
        """
        for name, kind in self.globs:
            if module == name and kind != "+":
                return True
            if kind and module.startswith(name + "."):
                return True
        return False

    def builds(self, module: str) -> bool:
        """
        Mirrors Lake's `isBuildableModule`.

        A module belongs to the library if a glob matches it, or if it lies under a root
        that a glob matches.

        :param module: Module name.
        :return: True if the library can build the module.
        """
        return self.matches_glob(module) or any(
            (module == root or module.startswith(root + ".")) and self.matches_glob(root)
            for root in self.roots
        )


@dataclass
class Workspace:
    """
    The source modules of a package, assigned to its libraries.

    :param owner: For each module that a library builds, the name of that library.
    :param modules: The same modules with their paths and imports.
    :param overlapping: Modules that more than one library matches.
    :param unowned: Source files under a library's source directory that no library matches.
    """

    owner: dict[str, str]
    modules: dict[str, import_depth.Module]
    overlapping: dict[str, list[str]]
    unowned: set[str]


def lean_name(text: str) -> str:
    """
    Normalizes a name from the lakefile to the form of the names read from sources.

    :param text: A dotted name, or a single name that is not an identifier (`my-lib`).
    :return: The name with non-identifier components escaped as `«...»`.
    """
    parser = import_depth.HeaderParser(text)
    name = parser.read_module_name()
    if name is not None and parser.pos == len(text):
        return name
    return import_depth.join_components([text])


def parse_glob(text: str) -> tuple[str, str]:
    """
    Parses a module glob of the lakefile.

    :param text: `A.B`, `A.B.+` or `A.B.*`.
    :return: The module name and the suffix `""`, `"+"` or `"*"`.
    """
    if text.endswith((".+", ".*")):
        return lean_name(text[:-2]), text[-1]
    return lean_name(text), ""


def string_list(value: object, what: str) -> list[str]:
    """
    Reads a TOML or JSON value that holds a string or a list of strings.

    :param value: The decoded value.
    :param what: Description used in the error message.
    :return: The strings.
    :raises ConfigError: If the value has another type.
    """
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ConfigError(f"{what} must be a string or a list of strings")
    return items


def read_libraries(package_dir: str, lakefile: str) -> list[Library]:
    """
    Reads the libraries of a `lakefile.toml`.

    :param package_dir: Directory of the package, which `srcDir` is relative to.
    :param lakefile: Path of the TOML configuration.
    :return: The libraries in the order of declaration.
    :raises ConfigError: If the file cannot be read or declares no library.
    """
    try:
        with open(lakefile, "rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read {lakefile}: {error}") from error
    package_source = os.path.join(package_dir, config.get("srcDir", "."))
    libraries = []
    for table in config.get("lean_lib", []):
        name = table.get("name")
        if not isinstance(name, str):
            raise ConfigError(f"{lakefile}: a [[lean_lib]] block has no name")
        roots = [lean_name(r) for r in string_list(table.get("roots", [name]), f"{name}.roots")]
        if "globs" in table:
            globs = [parse_glob(g) for g in string_list(table["globs"], f"{name}.globs")]
        else:
            globs = [(root, "") for root in roots]
        source_dir = os.path.normpath(os.path.join(package_source, table.get("srcDir", ".")))
        libraries.append(Library(name, source_dir, roots, globs))
    if not libraries:
        raise ConfigError(f"{lakefile}: no [[lean_lib]] blocks")
    return libraries


def list_sources(source_dir: str) -> dict[str, str]:
    """
    Lists the `.lean` files under a source directory.

    :param source_dir: Source directory of a library.
    :return: Paths by module name.
    """
    sources: dict[str, str] = {}
    for directory, subdirs, files in os.walk(source_dir):
        subdirs[:] = sorted(d for d in subdirs if d not in import_depth.EXCLUDED_DIRS)
        for filename in sorted(files):
            if filename.endswith(".lean"):
                path = os.path.join(directory, filename)
                sources[import_depth.module_name(source_dir, path)] = path
    return sources


def collect_workspace(libraries: list[Library]) -> Workspace:
    """
    Assigns source files to libraries and reads their imports.

    As in Lake, a module that several libraries match belongs to the one declared last.

    :param libraries: Libraries in the order of declaration.
    :return: The assigned modules.
    """
    listings: dict[str, dict[str, str]] = {}
    owner: dict[str, str] = {}
    paths: dict[str, str] = {}
    matched: dict[str, list[str]] = {}
    for library in libraries:
        if library.source_dir not in listings:
            listings[library.source_dir] = list_sources(library.source_dir)
        for name, path in listings[library.source_dir].items():
            if library.builds(name):
                owner[name] = library.name
                paths[name] = path
                matched.setdefault(name, []).append(library.name)
    modules = {
        name: import_depth.Module(name, path, import_depth.read_imports(path))
        for name, path in paths.items()
    }
    overlapping = {name: libs for name, libs in matched.items() if len(libs) > 1}
    unowned = {name for listing in listings.values() for name in listing} - owner.keys()
    return Workspace(owner, modules, overlapping, unowned)


def library_edges(workspace: Workspace) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """
    Groups the imports between different libraries by pair of libraries.

    :param workspace: Result of `collect_workspace`.
    :return: For each pair (importing library, imported library), the pairs (importing
        module, imported module), sorted.
    """
    edges: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for name in sorted(workspace.modules):
        source = workspace.owner[name]
        for imported in workspace.modules[name].imports:
            target = workspace.owner.get(imported)
            if target is not None and target != source:
                edges.setdefault((source, target), []).append((name, imported))
    return edges


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """
    Finds the groups of libraries that depend on each other.

    :param graph: For each library, the libraries it depends on.
    :return: The strongly connected components with more than one library, members in the
        order of the keys of `graph`.
    """
    reachable: dict[str, set[str]] = {}
    for start in graph:
        seen: set[str] = set()
        stack = list(graph[start])
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(graph.get(node, ()))
        reachable[start] = seen
    cycles: list[list[str]] = []
    assigned: set[str] = set()
    for name in graph:
        if name in assigned:
            continue
        group = [o for o in graph if o == name or (o in reachable[name] and name in reachable[o])]
        assigned.update(group)
        if len(group) > 1:
            cycles.append(group)
    return cycles


def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """
    Builds a JSON object and rejects repeated keys, which `json` would silently overwrite.

    :param pairs: Key and value pairs of one object.
    :return: The object.
    :raises ConfigError: If a key occurs twice.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"entry {key!r} occurs twice")
        result[key] = value
    return result


def read_allowed(path: str, libraries: list[Library]) -> dict[str, set[str]]:
    """
    Reads and validates the list of allowed imports between libraries.

    :param path: Path of the JSON file.
    :param libraries: Libraries of the lakefile.
    :return: For each library, the libraries it may import.
    :raises ConfigError: If the file does not have exactly one entry per library, names an
        unknown library, or allows a cycle. Names are compared as Lean names, so `my-lib`
        and `«my-lib»` are the same library.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle, object_pairs_hook=unique_keys)
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    names = [library.name for library in libraries]
    by_lean_name = {lean_name(name): name for name in names}
    entries: dict[str, list[str]] = {}
    unknown: set[str] = set()
    for key, value in data.items():
        listed = [key, *string_list(value, f"{path}: entry {key!r}")]
        unknown.update(n for n in listed if lean_name(n) not in by_lean_name)
        if not unknown:
            library, *targets = (by_lean_name[lean_name(n)] for n in listed)
            if library in entries:
                raise ConfigError(f"{path}: library {library} has two entries")
            entries[library] = targets
    if unknown:
        listed_unknown = ", ".join(sorted(unknown))
        raise ConfigError(f"{path} names libraries not in the lakefile: {listed_unknown}")
    missing = [name for name in names if name not in entries]
    if missing:
        raise ConfigError(f"{path} has no entry for: {', '.join(missing)}")
    allowed = {name: set(entries[name]) - {name} for name in names}
    cycles = find_cycles(allowed)
    if cycles:
        raise ConfigError(f"{path} allows a cycle among: {', '.join(cycles[0])}")
    return allowed


def build_report(
    libraries: list[Library],
    workspace: Workspace,
    allowed: dict[str, set[str]] | None,
    examples: int,
) -> dict:
    """
    Builds the report printed as text or JSON.

    :param libraries: Libraries in the order of declaration.
    :param workspace: Result of `collect_workspace`.
    :param allowed: Allowed imports, or `None` to check for cycles only.
    :param examples: Number of example imports kept for each failing pair of libraries.
    :return: The report. A pair of libraries fails if it is not allowed or, without a list
        of allowed imports, if both libraries lie on the same cycle.
    """
    names = [library.name for library in libraries]
    found = library_edges(workspace)
    graph = {name: {t for s, t in found if s == name} for name in names}
    cycles = find_cycles(graph)
    group_of = {name: index for index, group in enumerate(cycles) for name in group}
    edges = []
    for source, target in sorted(found, key=lambda e: (names.index(e[0]), names.index(e[1]))):
        imports = found[(source, target)]
        if allowed is None:
            failed = source in group_of and group_of.get(source) == group_of.get(target)
        else:
            failed = target not in allowed[source]
        entry = {
            "from": source,
            "to": target,
            "import_count": len(imports),
            "module_count": len({module for module, _ in imports}),
            "failed": failed,
        }
        if failed:
            entry["examples"] = [
                {"module": m, "path": workspace.modules[m].path, "imports": i}
                for m, i in imports[:examples]
            ]
        edges.append(entry)
    unowned_imports = sorted(
        {
            (name, imported)
            for name, module in workspace.modules.items()
            for imported in module.imports
            if imported in workspace.unowned
        }
    )
    failures = [edge for edge in edges if edge["failed"]]
    counts = {name: 0 for name in names}
    for owner in workspace.owner.values():
        counts[owner] += 1
    return {
        "ok": not failures,
        "check": "cycles" if allowed is None else "allowed",
        "libraries": counts,
        "edges": edges,
        "cycles": cycles,
        "failed_import_count": sum(edge["import_count"] for edge in failures),
        "overlapping_modules": [
            {"module": name, "libraries": libs}
            for name, libs in sorted(workspace.overlapping.items())
        ],
        "unowned_imports": [{"module": m, "imports": i} for m, i in unowned_imports],
    }


def warnings_of(report: dict) -> list[str]:
    """
    Describes the conditions that make the check incomplete or ambiguous.

    :param report: Result of `build_report`.
    :return: Warning messages.
    """
    warnings = [
        f"no source file is assigned to library {name}"
        for name, count in report["libraries"].items()
        if count == 0
    ]
    overlapping = report["overlapping_modules"]
    if overlapping:
        shown = ", ".join(
            f"{e['module']} ({', '.join(e['libraries'])})" for e in overlapping[:WARNING_EXAMPLES]
        )
        warnings.append(
            f"{len(overlapping)} module(s) match several libraries, counted for the last "
            f"one: {shown}"
        )
    unowned = report["unowned_imports"]
    if unowned:
        shown = ", ".join(
            f"{e['module']} imports {e['imports']}" for e in unowned[:WARNING_EXAMPLES]
        )
        warnings.append(
            f"{len(unowned)} import(s) of source files that no library matches: {shown}"
        )
    return warnings


def print_text(report: dict) -> None:
    """
    Prints the report for a human reader.

    :param report: Result of `build_report`.
    """
    total = sum(edge["import_count"] for edge in report["edges"])
    print(
        f"Libraries: {len(report['libraries'])}, modules: "
        f"{sum(report['libraries'].values())}, imports between libraries: {total}"
    )
    marker = "CYCLE" if report["check"] == "cycles" else "NOT ALLOWED"
    for edge in report["edges"]:
        flag = f"  [{marker}]" if edge["failed"] else ""
        print(
            f"  {edge['from']} -> {edge['to']}: {edge['import_count']} import(s) in "
            f"{edge['module_count']} module(s){flag}"
        )
        for example in edge.get("examples", []):
            print(f"      {example['path']} imports {example['imports']}")
    for group in report["cycles"]:
        print(f"Cycle among {len(group)} libraries: {', '.join(group)}")
    if report["ok"]:
        passed = "no cycle between libraries" if report["check"] == "cycles" else "all allowed"
        print(f"Result: passed, {passed}")
    else:
        failed = sum(1 for edge in report["edges"] if edge["failed"])
        reason = "on a cycle" if report["check"] == "cycles" else "not allowed"
        print(
            f"Result: failed, {report['failed_import_count']} import(s) between {failed} "
            f"pair(s) of libraries are {reason}"
        )


def main() -> int:
    """
    Command-line entry point.

    :return: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Check the direction of imports between the libraries of a Lake package."
    )
    parser.add_argument("package", nargs="?", default=".", help="package directory (default: .)")
    parser.add_argument(
        "--lakefile",
        metavar="FILE",
        help="TOML configuration to read (default: lakefile.toml in the package directory)",
    )
    parser.add_argument(
        "--allow",
        metavar="FILE",
        help="JSON file of the libraries each library may import (default: check for cycles)",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=3,
        metavar="N",
        help="imports shown for each failing pair of libraries (default: 3)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    lakefile = args.lakefile or os.path.join(args.package, "lakefile.toml")
    if not os.path.exists(lakefile) and os.path.exists(os.path.join(args.package, "lakefile.lean")):
        print(
            "error: no lakefile.toml; run `lake translate-config toml <file>` and pass "
            "--lakefile <file>",
            file=sys.stderr,
        )
        return 2
    try:
        libraries = read_libraries(args.package, lakefile)
        allowed = None if args.allow is None else read_allowed(args.allow, libraries)
        workspace = collect_workspace(libraries)
        if not workspace.modules:
            raise ConfigError(f"no source file of any library found under {args.package}")
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    report = build_report(libraries, workspace, allowed, max(args.examples, 0))
    for warning in warnings_of(report):
        print(f"warning: {warning}", file=sys.stderr)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_text(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
