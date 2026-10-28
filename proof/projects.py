"""
projects.py - which projects you're working on, and how to run their tests.

Your projects are listed in proof_output/projects.txt, one folder per line (# comments).
`proof status D:\\MyAIProjects` adds every git repo in that folder; `proof new` adds the
projects it creates. Edit the file by hand to drop one.
"""

import json
import re
import sys
from pathlib import Path

from .scan import SKIP_DIRS, git, list_files


def projects_file(out_dir):
    return Path(out_dir) / "projects.txt"


def load_projects(out_dir):
    """The folders in projects.txt that still exist."""
    path = projects_file(out_dir)
    if not path.exists():
        return []
    folders = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and Path(line).expanduser().is_dir():
            folders.append(Path(line).expanduser().resolve())
    return folders


def add_projects(out_dir, folders):
    """Add folders to projects.txt (each once). Returns the ones that were new."""
    known = {str(f) for f in load_projects(out_dir)}
    new = [f for f in folders if str(f) not in known]
    if new:
        path = projects_file(out_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        before = path.read_text(encoding="utf-8") if path.exists() else \
            "# Projects proof keeps an eye on (one folder per line; # for comments)\n"
        path.write_text(before + "".join(f"{f}\n" for f in new), encoding="utf-8")
    return new


def uncommitted(repo):
    """Changed or new files git would commit (`git status`), leaving out build junk a
    repo forgot to .gitignore (__pycache__, node_modules ...)."""
    paths = [line[3:].strip('"') for line in git(repo, "status", "--porcelain").splitlines()
             if line.strip()]
    return [path for path in paths if not SKIP_DIRS & set(path.rstrip("/").split("/"))]


def find_repos(folder):
    """A git repo, or the git repos directly inside a folder (D:\\MyAIProjects)."""
    folder = Path(folder).expanduser().resolve()
    if (folder / ".git").exists():
        return [folder]
    return sorted(child for child in folder.iterdir()
                  if child.is_dir() and (child / ".git").exists())


def find_project(out_dir, name_or_path):
    """A project by folder name ("doppel") or path. Stops with a clear message if unknown."""
    path = Path(name_or_path).expanduser()
    if path.is_dir():
        return path.resolve()
    projects = load_projects(out_dir)
    matches = [p for p in projects if p.name.lower() == name_or_path.lower()]
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(p.name for p in projects) or "none yet (proof status <folder> adds them)"
    raise SystemExit(f"No project called '{name_or_path}'. Your projects: {names}")


# ---------------------------------------------------------------------------
# How to run a project's tests: what a coding agent should run, and what
# `proof task check` runs. Read from the files, never guessed by a model.
# ---------------------------------------------------------------------------

def test_command(repo):
    """The command that runs this project's tests, or None if we can't tell."""
    names = {f.as_posix() for f in list_files(repo)}
    if "package.json" in names:
        scripts = package_scripts(repo)
        if "test" in scripts and "no test specified" not in scripts["test"]:
            return "npm test"
    if "pyproject.toml" in names or "requirements.txt" in names or "setup.py" in names:
        has_tests = any(re.search(r"(^|/)(tests?/|test_[^/]+\.py$)|_test\.py$", n) for n in names)
        if has_tests:
            return f'"{python_for(repo)}" -m pytest -q'
    if "go.mod" in names:
        return "go test ./..."
    if "Cargo.toml" in names:
        return "cargo test"
    if "pom.xml" in names:
        return "mvn -q test"
    if "gradlew" in names:
        return "./gradlew test"
    return None


def python_for(repo):
    """The project's own virtual environment if it has one (that's where its packages
    are), else the Python running proof. Plain "python" can be the wrong one (on Windows
    it may not even run)."""
    for venv in (".venv", "venv", "env"):
        for program in ("Scripts/python.exe", "bin/python"):
            if (Path(repo) / venv / program).exists():
                return Path(repo) / venv / program
    return sys.executable


def check_commands(repo):
    """Commands a change should pass: lint and type checks from package.json, then tests."""
    commands = []
    scripts = package_scripts(repo)
    for name in ("lint", "typecheck", "type-check"):
        if name in scripts:
            commands.append(f"npm run {name}")
    tests = test_command(repo)
    if tests:
        commands.append(tests)
    return commands


def package_scripts(repo):
    try:
        data = json.loads((Path(repo) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


def github_repo(repo):
    """'owner/name' if the project's origin is on GitHub, else None."""
    url = git(repo, "remote", "get-url", "origin")
    match = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{match.group(1)}/{match.group(2)}" if match else None
