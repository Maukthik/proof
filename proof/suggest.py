"""
suggest.py - `proof suggest REPO`: what to add to a project so it's stronger proof.

  1. Checklist (plain rules): what a client looks for before trusting a project -
     results in the README, a screenshot, a live demo, tests, CI ... - and how to fix each.
  2. What clients asked for: technologies in the jobs you pitched with this project
     (from the pitch log) that the project doesn't show yet.
  3. Ideas (the model): 3-5 features to build next, in this code, each turned into a
     task you can hand to a coding assistant.

Written to proof_output/<repo>/suggestions.md. --no-ai gives parts 1 and 2 only.
"""

import re

from .lint import missing_files
from .match import tech_in
from .scan import RESULT_HEADINGS, is_side_folder, readme_text
from .tracker import load_log

# Hosts that mean "you can try it": a live demo, not just more code
DEMO_HOSTS = re.compile(r"https?://[^\s)]*(vercel\.app|netlify\.app|herokuapp\.com|streamlit\.app|"
                        r"huggingface\.co/spaces|onrender\.com|fly\.dev|pages\.dev|github\.io|"
                        r"railway\.app|replit\.app|youtu\.?be|loom\.com)", re.IGNORECASE)
# Ways a project ships: a container or host config, a GitHub Action, an installable package
SHIP_FILES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "vercel.json",
              "netlify.toml", "Procfile", "fly.toml", "render.yaml", "app.yaml", "action.yml",
              "action.yaml"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "testing", "androidtest"}
# Environment variables a stranger must set: keys, tokens, passwords, service URLs.
# (RANK or DEBUG don't need an .env.example.)
ENV_NAME = re.compile(r"""(?:os\.environ(?:\.get)?\(?\[?|getenv\(|process\.env\.|env::var\(|"""
                      r"""System\.getenv\()\s*["']?([A-Z][A-Z0-9_]*)""")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|_URL|DSN|DATABASE|CREDENTIALS")


# ---------------------------------------------------------------------------
# 1. Checklist
# ---------------------------------------------------------------------------

def checklist(repo, files, out_dir):
    """[(passed, what, why a client cares, how to fix)] for one repo."""
    names = [f.as_posix() for f in files]
    readme = readme_text(repo, names)
    headings = re.findall(r"^#+\s*(.+)$", readme, flags=re.MULTILINE)
    code = [f for f in files if not is_side_folder(f)]
    needs_env = any(SECRET_NAME.search(name) for f in code[:300]
                    if f.suffix in (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".kt")
                    for name in ENV_NAME.findall(read(repo / f)))
    unfilled = unfilled_facts(out_dir / repo.name)

    return [
        (len(readme.split()) >= 150, "README that explains the project",
         "it's the first (often only) thing a client reads",
         "say what it does, for whom, and how to run it - 150+ words"),
        (any(RESULT_HEADINGS.search(h) for h in headings), "Results section in the README",
         "numbers are what make a project believable",
         "add a '## Results' section: speed, accuracy, users, tests - whatever you measured"),
        ("![" in readme or "<img" in readme, "Screenshot or demo GIF",
         "clients judge in seconds; a picture shows it works",
         "add a screenshot or a short GIF at the top of the README"),
        (DEMO_HOSTS.search(readme) is not None, "Live demo or video link",
         "trying it beats reading about it",
         "deploy it (Vercel, Render, Hugging Face Spaces...) or record a 1-minute video"),
        (any(re.search(r"install|quick ?start|getting started|usage|setup|\brun\b|\btry\b|"
                       r"how to use", h, re.I) for h in headings), "Quick-start steps",
         "shows it really runs, and that you write for other people",
         "add '## Quick start' with the exact commands"),
        (any(is_test(f) for f in files), "Automated tests", "tests are proof you work carefully",
         "add tests for the core logic (pytest, Jest, Vitest, go test...)"),
        (any(".github" in f.parts and "workflows" in f.parts for f in files), "CI on GitHub",
         "a green check on every push signals a professional workflow",
         "add a GitHub Actions workflow that runs the tests"),
        (any(f.name in SHIP_FILES for f in files) or is_package(repo, files),
         "Deploy or install setup",
         "clients want to know you can ship, not just code",
         "add a Dockerfile or deploy config, or package it so it installs in one command"),
        (not needs_env or any(f.name.startswith(".env.") for f in files), ".env.example",
         "anyone (a client's developer) can set it up without asking you",
         "list every environment variable the code reads in .env.example, without values"),
        (any(f.name.upper().startswith(("LICENSE", "LICENCE")) for f in files), "License",
         "companies can't use or evaluate code without one",
         "add a LICENSE file (MIT is the common choice)"),
        (unfilled == 0, "Case study facts filled in",
         "a case study with [add: ...] gaps can't be published",
         f"fill the {unfilled} empty line(s) in proof_output/{repo.name}/facts.md"),
    ]


def is_package(repo, files):
    """An installable tool: a pyproject.toml with a command, or a package.json with a bin."""
    for f in files:
        if f.name == "pyproject.toml" and len(f.parts) == 1:
            if re.search(r"^\[(project\.scripts|tool\.poetry\.scripts)\]", read(repo / f), re.M):
                return True
        if f.name == "package.json" and len(f.parts) == 1 and '"bin"' in read(repo / f):
            return True
    return False


def is_test(f):
    return (TEST_DIRS & {part.lower() for part in f.parts[:-1]}
            or re.search(r"^test_.+\.py$|_test\.\w+$|\.(test|spec)\.\w+$|Tests?\.\w+$", f.name))


def unfilled_facts(project_dir):
    """Empty lines ('- users: ') left in a project's facts.md."""
    facts_file = project_dir / "facts.md"
    if not facts_file.exists():
        return 0
    text = re.sub(r"<!--.*?-->", "", facts_file.read_text(encoding="utf-8"), flags=re.DOTALL)
    return len(re.findall(r"^\s*[-*]\s*[^:\n]+:\s*$", text, flags=re.MULTILINE))


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:200_000]
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 2. What clients asked for
# ---------------------------------------------------------------------------

def asked_for(out_dir, project_names, project_text):
    """{technology: how many pitches asked for it} - over the pitches that used this
    project, for technologies the project doesn't show."""
    shown = tech_in(project_text)
    counts = {}
    for entry in load_log(out_dir).values():
        if not set(entry.get("projects", [])) & set(project_names):
            continue
        for tech in set(entry.get("job_tech", [])) - shown:
            counts[tech] = counts.get(tech, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------------------
# 3. Ideas -> tasks
# ---------------------------------------------------------------------------

def parse_ideas(text):
    """'### Title' blocks with '- What:', '- Where:', '- Size:', '- Done when:' lines."""
    ideas = []
    for block in re.split(r"^### ", text, flags=re.MULTILINE)[1:]:
        title, _, body = block.partition("\n")
        fields = dict(re.findall(r"^-\s*(What|Why a client cares|Where|Size|Done when):\s*(.+)$",
                                 body, flags=re.MULTILINE))
        if "What" in fields:
            ideas.append({"title": title.strip(), **fields})
    return ideas


def unknown_files(ideas, files, sources):
    """Files an idea says to change that aren't in the repo (new ones are marked '(new)')."""
    unknown = []
    for idea in ideas:
        where = re.sub(r"[\w./\-\[\]()]+\s*\(new\)", "", idea.get("Where", ""))
        unknown += [f for f in missing_files(where, files, sources) if f not in unknown]
    return unknown


def task(idea, repo_name):
    """A self-contained request to hand to a coding assistant."""
    lines = [f"In the {repo_name} repo: {idea['What']}"]
    if idea.get("Where"):
        lines.append(f"Files: {idea['Where']}")
    if idea.get("Done when"):
        lines.append(f"Done when: {idea['Done when']}")
    lines.append("Match the existing code style, and add or update tests for what you change.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def report(repo_name, checks, wanted, ideas_text=None, ideas=(), warnings=()):
    done = sum(passed for passed, *_ in checks)
    lines = [f"# What to build next: {repo_name}", "",
             f"## Checklist ({done}/{len(checks)} done)", ""]
    for passed, what, why, fix in checks:
        lines.append(f"- [x] {what}" if passed else f"- [ ] **{what}** - {why}. *Fix:* {fix}.")
    lines += ["", "## What clients asked for", ""]
    if wanted:
        lines.append("Jobs you pitched with this project also asked for: "
                     + ", ".join(f"{tech} ({n})" for tech, n in wanted.items())
                     + ". Showing one of these here would make it a closer match.")
    else:
        lines.append("Nothing yet: write pitches with `proof pitch`, and this fills in.")
    if ideas_text:
        lines += ["", "## Ideas", "", ideas_text.strip()]
        lines += [f"\n> Check: {w}" for w in warnings]
    if ideas:
        lines += ["", "## Tasks for a coding assistant", "",
                  "Paste one into Claude Code, Cursor or similar:"]
        for idea in ideas:
            lines += ["", f"**{idea['title']}**", "```", task(idea, repo_name), "```"]
    return "\n".join(lines) + "\n"
