"""
codemap.py - which of the project's own files use which (from imports, no LLM).

This is the skeleton of the architecture diagram. Giving it to the LLM as a fact keeps
the diagram true to the code, instead of a guess from file names.

Handles Python (import x / from .x import y) and JavaScript/TypeScript
(import ... from "./x", require("./x"), and the "@/x" alias for src/).
"""

import re
from pathlib import PurePosixPath

# "from x import a, b" / "from x import (a,\n b)" / "import x"
PY_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n]+)"
                       r"|import[ \t]+([\w.]+))", re.MULTILINE)
JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(?\s*|\brequire\s*\(\s*)["']([^"']+)["']""")
JS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs"]

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
                targets.add(modules[name])
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
    """Local files that a JS/TS file imports ("./x", "../x", "@/x")."""
    targets = set()
    for spec in JS_IMPORT.findall(code):
        if spec.startswith("@/"):
            base = PurePosixPath("src") / spec[2:]
        elif spec.startswith("."):
            base = PurePosixPath(f.parent.as_posix()) / spec
        else:
            continue                          # a package from node_modules
        base = PurePosixPath(normalise(base))
        options = [base] + [PurePosixPath(f"{base}{ext}") for ext in JS_EXTENSIONS] \
            + [base / f"index{ext}" for ext in JS_EXTENSIONS]
        for option in options:
            is_code = option.suffix in JS_EXTENSIONS          # skip CSS, JSON, images
            if is_code and option.as_posix() in file_set and option.as_posix() != f.as_posix():
                targets.add(option.as_posix())
                break
    return targets


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
    """Return sorted (from_file, to_file) pairs between the project's own main files."""
    modules = python_modules(files)
    file_set = {f.as_posix() for f in files}
    edges = set()
    for f in files:
        if f.suffix == ".py":
            code = read_text(repo / f, limit=200_000)
            edges |= {(f.as_posix(), t.as_posix()) for t in python_targets(f, code, modules)}
        elif f.suffix in JS_EXTENSIONS:
            code = read_text(repo / f, limit=200_000)
            edges |= {(f.as_posix(), t) for t in js_targets(f, code, file_set)}
    return sorted(edges)


def describe_imports(edges):
    """Edges as text for the LLM, one line per file: 'a.py -> b.py, c.py'.
    Big web apps have hundreds of file-level edges. Then we group files by folder
    (src/app/actions/ -> src/lib/), using the deepest folder level that's readable."""
    if len(edges) > MAX_EDGES:
        deepest = max(len(path.split("/")) for edge in edges for path in edge)
        for depth in range(deepest - 1, 0, -1):
            grouped = folder_edges(edges, depth)
            if 0 < len(grouped) <= MAX_EDGES:
                return "(grouped by folder)\n" + edge_lines(grouped)
    lines = edge_lines(edges[:MAX_EDGES])
    if len(edges) > MAX_EDGES:
        lines += f"\n... and {len(edges) - MAX_EDGES} more"
    return lines


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
