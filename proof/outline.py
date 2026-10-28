"""
outline.py - a file's skeleton: its classes, functions and types, without the bodies.

Files that don't fit in the model's budget used to appear as one line each. Their
outline costs a few hundred characters and shows what the file actually provides, so a
small model sees the shape of far more of the repo. (The same idea as aider's repo map
and repomix --compress, which use tree-sitter; we use Python's own parser for Python and
plain line patterns for other languages.)
"""

import ast
import re

MAX_LINES = 25          # per file: enough to show what it provides

# One pattern per language family: lines that declare something
SIGNATURES = {
    "js": re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?function\*?\s+\w+\s*\(.*"
                     r"|^\s*(export\s+)?(const|let)\s+\w+\s*=\s*(async\s*)?(\([^)]*\)|\w+)\s*=>.*"
                     r"|^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w+.*"
                     r"|^\s*(export\s+)?(interface|type|enum)\s+\w+.*"),
    "go": re.compile(r"^func\s.*|^type\s+\w+\s+(struct|interface).*"),
    "rust": re.compile(r"^\s*(pub(\([\w:]+\))?\s+)?(async\s+)?(unsafe\s+)?fn\s+\w+.*"
                       r"|^\s*(pub(\([\w:]+\))?\s+)?(struct|enum|trait|type)\s+\w+.*|^\s*impl\b.*"),
    "jvm": re.compile(r"^\s*(public|private|protected|internal|open|abstract|data|sealed|final"
                      r"|static|override|suspend|\s)*(class|interface|object|enum|record|fun)\s+\w+.*"
                      r"|^\s*(public|protected)\s+[\w<>\[\], ?]+\s+\w+\s*\(.*"),
}
FAMILY = {".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".mjs": "js",
          ".go": "go", ".rs": "rust", ".java": "jvm", ".kt": "jvm", ".scala": "jvm"}


def outline(path, text):
    """The skeleton of one file as text ('' if we can't tell)."""
    if path.suffix == ".py":
        lines = python_outline(text)
    elif path.suffix in FAMILY:
        lines = pattern_outline(text, SIGNATURES[FAMILY[path.suffix]])
    else:
        return ""
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"... and {len(lines) - MAX_LINES} more"]
    return "\n".join(lines)


def python_outline(text):
    """Classes, functions and methods with their arguments and docstring's first line."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return pattern_outline(text, re.compile(r"^\s*(async\s+)?(def|class)\s+\w+.*"))
    lines = []
    for node in tree.body:
        lines += describe(node, indent="")
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                lines += describe(child, indent="    ")
    return lines


def describe(node, indent):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("_") and node.name != "__init__":
            return []                                     # private helpers: noise here
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        line = f"{indent}{prefix} {node.name}({ast.unparse(node.args)})"
    elif isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        line = f"{indent}class {node.name}" + (f"({bases})" if bases else "")
    else:
        return []
    doc = (ast.get_docstring(node) or "").strip().split("\n")[0]
    return [shorten(line + (f"  # {doc}" if doc else ""))]


def pattern_outline(text, pattern):
    return [shorten(line.rstrip(" {")) for line in text.split("\n") if pattern.match(line)]


def shorten(line, limit=140):
    return line if len(line) <= limit else line[:limit - 3] + "..."
