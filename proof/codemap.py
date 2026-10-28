"""
codemap.py - which of the project's own files use which (from imports, no LLM).

This is the skeleton of the architecture diagram. Giving it to the LLM as a fact keeps
the diagram true to the code, instead of a guess from file names.

Handles Python (import x / from .x import y), JavaScript/TypeScript ("./x", "@/x"),
Go (packages of the module in go.mod), Java/Kotlin (imports, and classes used from the
same package) and Rust (mod x; use crate::x; other crates of the same workspace).
"""

import re
from pathlib import PurePosixPath

# "from x import a, b" / "from x import (a,\n b)" / "import x"
PY_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n]+)"
                       r"|import[ \t]+([\w.]+))", re.MULTILINE)
JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(?\s*|\brequire\s*\(\s*)["']([^"']+)["']""")
JS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs"]
GO_IMPORTS = re.compile(r'^import\s*\((.*?)\)|^import\s+(?:[\w.]+\s+)?("[^"]+")',
                        re.MULTILINE | re.DOTALL)
JVM_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.MULTILINE)
JVM_SOURCE_ROOTS = {"java", "kotlin", "scala"}
RUST_MOD = re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?mod\s+(\w+)\s*;", re.MULTILINE)
RUST_PATH = re.compile(r"\b(\w+)::(\w+)")

MAX_EDGES = 120  # above this, the list is noise for a 5-10 box diagram


def python_modules(files):
    """Map every importable dotted name to its file.
    'src/app/db.py' can be imported as 'src.app.db', 'app.db' or 'db', depending on
    where the project puts itself on the path - so we record all of them."""
    modules = {}
    for f in files:
        if f.suffix != ".py":
            continue
        parts = list(f.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for start in range(len(parts)):
            modules.setdefault(".".join(parts[start:]), f)
    return modules


def python_targets(f, code, modules):
    """Local files that Python file `f` imports."""
    targets = set()
    for match in PY_IMPORT.finditer(code):
        source, names, plain = match.groups()
        if plain:
            candidates = [plain]
        else:
            names = names.split("#")[0].strip("() \n")
            names = [n.split(" as ")[0].strip() for n in names.split(",")]
            if source.startswith("."):
                source = resolve_relative(f, source)
            # "from pkg import mod" may import a module, or just a name from pkg
            candidates = [f"{source}.{n}" for n in names if n] + [source]
        for name in candidates:
            if name in modules and modules[name] != f:
                targets.add(modules[name].as_posix())
                break
    return targets


def resolve_relative(f, source):
    """'from ..util import x' inside 'pkg/sub/mod.py' -> 'pkg.util'."""
    dots = len(source) - len(source.lstrip("."))
    folder = list(f.parent.parts)
    package = folder[:len(folder) - (dots - 1)]       # one dot = f's own folder
    rest = source.lstrip(".")
    return ".".join(package + [rest]) if rest else ".".join(package)


def js_targets(f, code, file_set):
    """Local files that a JS/TS file imports: "./x", "../x", and the "@/x" or "~/x"
    alias, which points at the package's src/ folder or at the package root."""
    targets = set()
    for spec in JS_IMPORT.findall(code):
        if spec.startswith(("@/", "~/")):
            root = PurePosixPath(package_root(f, file_set))
            bases = [root / "src" / spec[2:], root / spec[2:]]
        elif spec.startswith("."):
            bases = [PurePosixPath(f.parent.as_posix()) / spec]
        else:
            continue                          # a package from node_modules
        for base in bases:
            target = js_file(PurePosixPath(normalise(base)), file_set)
            if target and target != f.as_posix():
                targets.add(target)
                break
    return targets


def js_file(base, file_set):
    """'src/lib/db' -> 'src/lib/db.ts' (or .tsx, /index.ts ...) if that file exists."""
    options = [base] + [PurePosixPath(f"{base}{ext}") for ext in JS_EXTENSIONS] \
        + [base / f"index{ext}" for ext in JS_EXTENSIONS]
    for option in options:
        if option.suffix in JS_EXTENSIONS and option.as_posix() in file_set:   # not CSS, JSON
            return option.as_posix()
    return None


def package_root(f, file_set):
    """The nearest folder above f with a package.json or tsconfig.json ('' = repo root).
    In a monorepo, frontend/'s "@/x" means frontend/src/x."""
    for folder in f.parents:
        prefix = "" if folder.as_posix() == "." else folder.as_posix() + "/"
        if f"{prefix}package.json" in file_set or f"{prefix}tsconfig.json" in file_set:
            return folder.as_posix()
    return "."


# ---------------------------------------------------------------------------
# Go: imports name packages (folders) of the module declared in go.mod
# ---------------------------------------------------------------------------

def go_modules(files, read):
    """{"github.com/you/app": "path/of/go.mod/folder"} for every go.mod in the repo."""
    modules = {}
    for f in files:
        if f.name == "go.mod":
            match = re.search(r"^module\s+(\S+)", read(f), flags=re.MULTILINE)
            if match:
                modules[match.group(1)] = f.parent.as_posix()
    return modules


def go_targets(code, modules, go_folders):
    """Local package folders ("ui/") that a Go file imports."""
    targets = set()
    for block, single in GO_IMPORTS.findall(code):
        for path in re.findall(r'"([^"]+)"', block or single):
            for module, root in modules.items():
                if path.startswith(module + "/"):
                    folder = normalise(PurePosixPath(root) / path[len(module) + 1:])
                    if folder in go_folders:
                        targets.add(folder + "/")
    return targets


# ---------------------------------------------------------------------------
# Java / Kotlin: class names from the path under src/main/java (or kotlin)
# ---------------------------------------------------------------------------

def jvm_classes(files):
    """{"com.acme.owner.Owner": "src/main/java/com/acme/owner/Owner.java"}"""
    classes = {}
    for f in files:
        if f.suffix in (".java", ".kt") and JVM_SOURCE_ROOTS & set(f.parts):
            parts = f.with_suffix("").parts
            start = max(i for i, part in enumerate(parts) if part in JVM_SOURCE_ROOTS) + 1
            classes[".".join(parts[start:])] = f.as_posix()
    return classes


def jvm_targets(f, code, classes):
    """Classes a Java/Kotlin file imports, plus classes of its own package it mentions
    (those need no import, so they'd be missed otherwise)."""
    targets = set()
    for name in JVM_IMPORT.findall(code):
        while name and name not in classes:        # com.acme.Util.helper -> com.acme.Util
            name = name.rpartition(".")[0]
        if name:
            targets.add(classes[name])
    folder = f.parent.as_posix()
    for path in classes.values():
        neighbour = PurePosixPath(path)
        if neighbour.parent.as_posix() == folder and re.search(rf"\b{neighbour.stem}\b", code):
            targets.add(path)
    return targets


# ---------------------------------------------------------------------------
# Rust: mod declarations, use crate::..., and other crates in the same workspace
# ---------------------------------------------------------------------------

def rust_crates(files, read):
    """{"grep_searcher": "crates/searcher/src/lib.rs"} for every crate in the repo."""
    crates = {}
    file_set = {f.as_posix() for f in files}
    for f in files:
        if f.name != "Cargo.toml":
            continue
        match = re.search(r'^\[package\][^\[]*?^name\s*=\s*"([^"]+)"', read(f),
                          flags=re.MULTILINE | re.DOTALL)
        root = "" if f.parent.as_posix() == "." else f.parent.as_posix() + "/"
        entries = [root + e for e in ("src/lib.rs", "src/main.rs") if root + e in file_set]
        entry = entries[0] if entries else None
        if match and entry:
            crates[match.group(1).replace("-", "_")] = entry
    return crates


def rust_targets(f, code, file_set, crates):
    targets = set()
    # "mod x;" in main.rs/lib.rs/mod.rs means a sibling x.rs; in a.rs it means a/x.rs
    folder = f.parent if f.name in ("main.rs", "lib.rs", "mod.rs") else f.parent / f.stem
    for name in RUST_MOD.findall(code):
        for option in (folder / f"{name}.rs", folder / name / "mod.rs"):
            if option.as_posix() in file_set:
                targets.add(option.as_posix())
    src = rust_src_root(f, file_set)
    for first, second in RUST_PATH.findall(code):
        if first == "crate" and src is not None:
            for option in (f"{src}{second}.rs", f"{src}{second}/mod.rs"):
                if option in file_set:
                    targets.add(option)
        elif first in crates:
            targets.add(crates[first])
    return targets


def rust_src_root(f, file_set):
    """'crates/core/flags/mod.rs' -> 'crates/core/' (the folder holding main.rs/lib.rs)."""
    for folder in f.parents:
        prefix = "" if folder.as_posix() == "." else folder.as_posix() + "/"
        if f"{prefix}main.rs" in file_set or f"{prefix}lib.rs" in file_set:
            return prefix
    return None


def normalise(path):
    """'src/app/../lib/db' -> 'src/lib/db' (PurePath doesn't resolve '..')."""
    out = []
    for part in PurePosixPath(path).parts:
        if part == "..":
            if out:
                out.pop()
        elif part != ".":
            out.append(part)
    return "/".join(out)


def internal_imports(repo, files, read_text):
    """Return sorted (from, to) pairs between the project's own main files.
    `to` is a file, or for Go a package folder ("ui/")."""
    def read(f):
        return read_text(repo / f, limit=200_000)

    file_set = {f.as_posix() for f in files}
    py_modules = python_modules(files)
    go_mods = go_modules(files, read)
    go_folders = {f.parent.as_posix() for f in files if f.suffix == ".go"}
    classes = jvm_classes(files)
    crates = rust_crates(files, read)

    edges = set()
    for f in files:
        if f.suffix == ".py":
            targets = python_targets(f, read(f), py_modules)
        elif f.suffix in JS_EXTENSIONS:
            targets = js_targets(f, read(f), file_set)
        elif f.suffix == ".go":
            targets = go_targets(read(f), go_mods, go_folders) - {f.parent.as_posix() + "/"}
        elif f.suffix in (".java", ".kt"):
            targets = jvm_targets(f, read(f), classes)
        elif f.suffix == ".rs":
            targets = rust_targets(f, read(f), file_set, crates)
        else:
            continue
        edges |= {(f.as_posix(), target) for target in targets if target != f.as_posix()}
    return sorted(edges)


def describe_imports(edges):
    """Edges as text for the LLM, one line per file: 'a.py -> b.py, c.py'.
    Big web apps have hundreds of file-level edges. Then we group files by folder
    (src/app/actions/ -> src/lib/), using the deepest folder level that's readable.
    A folder every path shares (src/main/java/com/acme/) is said once, not on every line."""
    if not edges:
        return ""
    prefix = common_folder(edges)
    if prefix:
        edges = [(a[len(prefix):], b[len(prefix):]) for a, b in edges]
    header = f"(all paths are under {prefix})\n" if prefix else ""
    if len(edges) > MAX_EDGES:
        deepest = max(len(path.split("/")) for edge in edges for path in edge)
        for depth in range(deepest - 1, 0, -1):
            grouped = folder_edges(edges, depth)
            if 0 < len(grouped) <= MAX_EDGES:
                return header + "(grouped by folder)\n" + edge_lines(grouped)
    lines = edge_lines(edges[:MAX_EDGES])
    if len(edges) > MAX_EDGES:
        lines += f"\n... and {len(edges) - MAX_EDGES} more"
    return header + lines


def common_folder(edges):
    """The folder all paths start with ('src/main/java/org/acme/'), or ''."""
    paths = [path for edge in edges for path in edge]
    first = paths[0].split("/")[:-1]
    shared = 0
    while shared < len(first) and all(p.split("/")[:-1][shared:shared + 1] == [first[shared]]
                                      for p in paths):
        shared += 1
    prefix = "/".join(first[:shared]) + "/" if shared else ""
    return prefix if len(prefix) > 12 else ""      # "src/" isn't worth a header


def folder_edges(edges, depth):
    """File edges -> folder edges, cutting paths to `depth` folders. Root files keep their name."""
    def folder(path):
        parts = path.split("/")
        if len(parts) == 1:
            return path
        return "/".join(parts[:min(depth, len(parts) - 1)]) + "/"
    return sorted({(folder(a), folder(b)) for a, b in edges if folder(a) != folder(b)})


def edge_lines(edges):
    by_source = {}
    for source, target in edges:
        by_source.setdefault(source, []).append(target)
    return "\n".join(f"{source} -> {', '.join(targets)}" for source, targets in by_source.items())
