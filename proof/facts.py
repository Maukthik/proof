"""
facts.py - your own notes about a project: real numbers, users, clients, links.

proof_output/<project>/facts.md is written by you, never by the model. Case studies,
pitches and profiles may use these facts for claims, and proof never overwrites the file.

When a case study comes back with [add: ...] gaps, we start facts.md for you with one
empty line per gap. Fill in what you can, then run `proof case` again.
"""

import hashlib
import re

TEMPLATE = """<!-- Facts about {name}, written by you. proof never overwrites this file.
     Real numbers, users, clients, results, links: case studies and pitches use these
     (and only these) for claims. Fill in a line, delete the ones you can't,
     add your own, then run `proof case` again for this project.                     -->

{lines}
"""


def read_facts(folder):
    """Facts text for a project folder, with the instructions and empty lines removed."""
    facts_file = folder / "facts.md"
    if not facts_file.exists():
        return ""
    text = re.sub(r"<!--.*?-->", "", facts_file.read_text(encoding="utf-8"), flags=re.DOTALL)
    lines = [line for line in text.splitlines()
             if line.strip() and not re.fullmatch(r"\s*[-*]?\s*[^:]*:\s*", line)]   # "- users:"
    return "\n".join(lines).strip()


def start_facts_file(folder, name, case_study):
    """Create facts.md with one line per [add: ...] gap. Does nothing if it exists.
    Returns True if a new file was written."""
    facts_file = folder / "facts.md"
    gaps = re.findall(r"\[add:\s*([^\]]+)\]", case_study)
    if facts_file.exists() or not gaps:
        return False
    unique = list(dict.fromkeys(gap.strip() for gap in gaps))    # keep order, drop repeats
    lines = "\n".join(f"- {gap}: " for gap in unique)
    facts_file.write_text(TEMPLATE.format(name=name, lines=lines), encoding="utf-8")
    return True


def fingerprint(text):
    """Short hash, used to notice when facts or a case study changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
