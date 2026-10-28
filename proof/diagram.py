"""
diagram.py - check the model's Mermaid diagram against the code, and link its boxes.

An idea from gitdiagram: an arrow in an architecture diagram should be backed by
evidence. Here the evidence is the import map (codemap.py). For every arrow between two
boxes that name real files, we look for an import between them, in either direction
(a diagram arrow can mean "calls" or "sends data to"). An arrow with no import behind it
is redrawn dashed - "not shown by the code" - instead of being deleted, since it may be a
real HTTP call or a README-documented flow.

Each box that names a real file also gets a `click` line pointing at that file on GitHub.
The portfolio page turns those into links (see portfolio.py).
"""

import re

MERMAID_BLOCK = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
# A box: Id["label"] (quoted, may contain brackets) or Id[label], Id(label), Id{label}
QUOTED_NODE = re.compile(r'\b([A-Za-z]\w*)\s*[\[({]+"([^"]*)"')
PLAIN_NODE = re.compile(r'\b([A-Za-z]\w*)\s*[\[({]+([^\]\)}"]*)[\])}]+')
# An arrow, with an optional |label|: -->, ---, ==>, -.->  (kept whole when we split a line)
ARROW = re.compile(r"(\s*(?:-->|---|==>|-\.->)(?:\s*\|[^|]*\|)?\s*)")
FIRST_ID = re.compile(r"^\s*([A-Za-z]\w*)")
PATH_IN_LABEL = re.compile(r"\(([\w./\-\[\]()@]+(?:\.\w+|/))\)\s*$|^([\w./\-\[\]@]+\.\w+)$")


def check_and_link(case_study, files, edges, repo_url=None, commit=None):
    """Return (case study with arrows checked and boxes linked, number of dashed arrows)."""
    dashed_total = 0

    def fix_block(match):
        nonlocal dashed_total
        block, dashed = check_block(match.group(1), files, edges, repo_url, commit)
        dashed_total += dashed
        return f"```mermaid\n{block}```"

    return MERMAID_BLOCK.sub(fix_block, case_study), dashed_total


def check_block(block, files, edges, repo_url, commit):
    paths = node_paths(block, files)
    linked = imports_between(edges)
    dashed = 0
    lines = []
    for line in block.split("\n"):
        if line.strip().startswith("click "):
            continue                                   # we add our own below
        # "A --> B -->|x| C" splits into [A, -->, B, -->|x|, C]: check each arrow
        pieces = ARROW.split(line)
        for i in range(1, len(pieces), 2):
            left = FIRST_ID.match(last_box(pieces[i - 1]))
            right = FIRST_ID.match(pieces[i + 1])
            if not left or not right or "-.->" in pieces[i]:
                continue
            a, b = left.group(1), right.group(1)
            if a in paths and b in paths and not backed(paths[a], paths[b], linked):
                pieces[i] = re.sub(r"-->|---|==>", "-.->", pieces[i], count=1)
                dashed += 1
        lines.append("".join(pieces))
    if repo_url:
        while lines and not lines[-1].strip():
            lines.pop()
        kind = {True: "tree", False: "blob"}                # GitHub: folders are /tree/
        lines += [f'    click {node} "{repo_url}/{kind[path.endswith("/")]}/'
                  f'{commit or "HEAD"}/{path}" _blank' for node, path in paths.items()]
        lines.append("")
    return "\n".join(lines), dashed


def last_box(segment):
    """The box an arrow starts from: in 'A["x"] & B' that's the last one written."""
    return segment.split("&")[-1]


def node_paths(block, files):
    """{node id: repo path} for boxes whose label names a real file or folder."""
    paths = {}
    unquoted = re.sub(r'"[^"]*"', '""', block)     # words inside a quoted label aren't boxes
    for node, label in QUOTED_NODE.findall(block) + PLAIN_NODE.findall(unquoted):
        match = PATH_IN_LABEL.search(label.strip())
        if not match:
            continue
        found = find_path((match.group(1) or match.group(2)).strip(), files)
        if found:
            paths.setdefault(node, found)
    return paths


def find_path(path, files):
    """The repo path a label means: exact, a partial path (doppel/runner.py is
    src/doppel/runner.py), or a folder ending in '/'. None if it's not in the repo."""
    path = path.removeprefix("./")
    if path.endswith("/"):
        return next((f.rsplit(path, 1)[0] + path for f in files if path in "/" + f
                     or f.startswith(path)), None)
    return next((f for f in files if f == path or f.endswith("/" + path)), None)


def imports_between(edges):
    """Both directions of every import, plus folder-level pairs ('src/lib/' -> ...)."""
    pairs = set()
    for source, target in edges:
        pairs |= {(source, target), (target, source)}
    return pairs


def backed(a, b, pairs):
    """Is there an import between a and b (files, or files inside folders a / b)?"""
    def within(path, place):
        return path == place or (place.endswith("/") and path.startswith(place))
    return any(within(x, a) and within(y, b) for x, y in pairs)
