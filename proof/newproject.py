"""
newproject.py - `proof new`: from a one-line idea to a plan and a starter repo.

1. The plan (PLAN.md): problem, users, first version, stack, milestones, first tasks,
   and the proof to collect once it works. The model is told which technologies you
   already know (from your case studies) and which ones clients asked for (from your
   pitch log), so the plan stretches you in a direction that wins work.
2. The repo: README with "The problem" filled in and "Quick start" and "Results"
   sections ready, .gitignore, a first test, CI that runs it, an MIT license, PLAN.md,
   and a first commit. Python, Node, or plain (README and plan only).
3. The first tasks go into its task list, and the project into your projects list.
"""

import re
import subprocess
from datetime import date
from pathlib import Path

from .jobpost import slug
from .lint import section

NODE_WORDS = re.compile(r"next\.?js|react|node|typescript|express|vue|svelte|javascript",
                        re.IGNORECASE)
PYTHON_WORDS = re.compile(r"python|fastapi|django|flask|streamlit|pandas|pytorch",
                          re.IGNORECASE)


def plan_name(plan, fallback):
    """'# Fieldnotes - turn ...' -> 'fieldnotes' (a folder name)."""
    title = re.search(r"^# (.+)$", plan, flags=re.MULTILINE)
    name = title.group(1).split(" - ")[0] if title else fallback
    return slug(name, max_words=3) or slug(fallback, max_words=3) or "new-project"


def plan_tasks(plan):
    """The bullets under "## First tasks"."""
    return [re.sub(r"^[-*\d.)\s]+", "", line).strip()
            for line in section(plan, "First tasks").splitlines()
            if re.match(r"\s*([-*]|\d+[.)])\s+\S", line)]


def pick_template(plan, stack=None):
    """python, node or plain: what --stack says, else what the plan's Stack section names."""
    if stack:
        return stack
    stack_text = section(plan, "Stack")
    if NODE_WORDS.search(stack_text):
        return "node"
    if PYTHON_WORDS.search(stack_text):
        return "python"
    return "plain"


def offline_plan(idea):
    """--no-ai: the plan's shape with the idea in it and gaps to fill."""
    return (f"# {idea[:40]} - [add: one line: what it does, and for whom]\n"
            f"## The problem\n{idea}\n[add: who has this problem and what goes wrong today]\n"
            "## Who it's for\n- [add: users]\n"
            "## First version\n- [add: 3-6 features]\n"
            "## Stack\n- [add: technologies]\n"
            "## Milestones\n1. [add: first milestone] - done when: [add: a check]\n"
            "## First tasks\n- Write the README's problem and quick start\n"
            "- Build the smallest version of the main feature\n"
            "- Add a test that shows it works\n"
            "## Proof to collect\n- [add: what you'll measure]\n")


# ---------------------------------------------------------------------------
# The starter repo
# ---------------------------------------------------------------------------

def create_repo(folder, plan, template, owner=""):
    """Write the starter files and make the first commit. Returns (files written,
    committed?). The folder must not exist yet, or be empty."""
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"{folder} already exists and isn't empty - pick another --name.")
    package = folder.name.replace("-", "_")
    files = {"README.md": readme(plan, template, folder.name), "PLAN.md": plan}
    files.update(TEMPLATES[template](package))
    if owner:
        files["LICENSE"] = MIT.format(year=date.today().year, owner=owner)
    for path, text in files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    committed = run_git(folder, "init", "-q") and run_git(folder, "add", "-A") and \
        run_git(folder, "commit", "-q", "-m", f"Start {folder.name} (proof new)")
    return sorted(files), committed


def run_git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True).returncode == 0


def git_user_name():
    result = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True)
    return result.stdout.strip()


def readme(plan, template, name):
    title = re.search(r"^# (.+)$", plan, flags=re.MULTILINE)
    heading, _, tagline = (title.group(1) if title else name).partition(" - ")
    quick_start = {
        "python": "pip install pytest\npython -m pytest -q",
        "node": "npm install\nnpm test",
        "plain": "[add: the commands to run it]",
    }[template]
    return f"""# {heading.strip()}

{tagline.strip()}

## The problem
{section(plan, "The problem").strip()}

## Who it's for
{section(plan, "Who it's for").strip()}

## Status
Early days: the plan and milestones are in [PLAN.md](PLAN.md).

## Quick start
```
{quick_start}
```

## Results
_Nothing measured yet. Add numbers here as soon as you have them (speed, accuracy, users,
tests): case studies and pitches quote this section._
"""


def python_files(package):
    return {
        "pyproject.toml": f"""[project]
name = "{package.replace('_', '-')}"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[tool.pytest.ini_options]
pythonpath = ["src"]
""",
        f"src/{package}/__init__.py": f'"""{package}: see README.md."""\n',
        "tests/test_smoke.py": f"""import {package}


def test_package_imports():
    assert {package}.__doc__
""",
        ".github/workflows/ci.yml": CI.format(setup="""      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pytest
      - run: python -m pytest -q"""),
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n.pytest_cache/\ndist/\n*.egg-info/\n",
    }


def node_files(package):
    return {
        "package.json": f"""{{
  "name": "{package.replace('_', '-')}",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {{
    "test": "node --test"
  }}
}}
""",
        "src/index.js": "export function ready() {\n  return true;\n}\n",
        "test/smoke.test.js": """import { test } from "node:test";
import assert from "node:assert/strict";
import { ready } from "../src/index.js";

test("the package loads", () => {
  assert.equal(ready(), true);
});
""",
        ".github/workflows/ci.yml": CI.format(setup="""      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm install
      - run: npm test"""),
        ".gitignore": "node_modules/\n.env\n.env.local\ndist/\n.next/\ncoverage/\n",
    }


def plain_files(package):
    return {".gitignore": ".env\n"}


TEMPLATES = {"python": python_files, "node": node_files, "plain": plain_files}

CI = """name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
{setup}
"""

MIT = """MIT License

Copyright (c) {year} {owner}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
