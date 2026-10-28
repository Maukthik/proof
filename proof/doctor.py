"""
doctor.py - `proof doctor`: check that everything proof needs works, in one go.

Checks your setup (Python, git, the output folder), the model (reachable, installed,
answers a test prompt), every job board (reachable, and its reader still finds jobs -
boards change their formats), your case studies and your pitch log. Each check says
what's wrong and how to fix it, and the whole output is made to be pasted when asking
for help.

  proof doctor               everything
  proof doctor --offline     no network: skips the model test and the job boards
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from . import __version__
from .feeds import DEFAULT_BOARDS, FeedError, read_board
from .apply import board_name
from .llm import ask_llm, ollama_num_ctx, scan_budget
from .portfolio import load_case_studies
from .tracker import load_log, to_do

OK, WARN, FAIL = "ok", "warn", "FAIL"


def run(out_dir, provider, model, boards=None, offline=False, say=print):
    """Print every check, grouped. Returns the number of failures."""
    say(f"proof doctor  (proof {__version__}{proof_commit()}, Python "
        f"{platform.python_version()}, {platform.system()})")
    groups = [("Setup", setup_checks(out_dir)),
              (f"Model ({provider} / {model or 'no model chosen'})",
               model_checks(provider, model, offline))]
    if offline:
        groups.append(("Job boards", [(WARN, "skipped (--offline)")]))
    else:
        groups.append(("Job boards", board_checks(boards or DEFAULT_BOARDS)))
    groups += [("Your projects", project_checks(out_dir)),
               ("Pitch log", log_checks(out_dir))]

    counts = {OK: 0, WARN: 0, FAIL: 0}
    for title, checks in groups:
        say(f"\n{title}")
        for level, text in checks:
            say(f"  {level:<5} {text}")
            counts[level] += 1
    say(f"\n{counts[FAIL]} problem(s), {counts[WARN]} warning(s). "
        "Asking for help? Paste this whole output.")
    return counts[FAIL]


def proof_commit():
    """', commit abc1234' when proof runs from a git clone - says exactly which code ran."""
    folder = Path(__file__).resolve().parent.parent
    if not (folder / ".git").exists() or not shutil.which("git"):
        return ""
    result = subprocess.run(["git", "-C", str(folder), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True)
    return f", commit {result.stdout.strip()}" if result.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_checks(out_dir):
    checks = []
    if sys.version_info >= (3, 10):
        checks.append((OK, f"Python {platform.python_version()}"))
    else:
        checks.append((FAIL, f"Python {platform.python_version()} - proof needs 3.10 or newer"))

    if shutil.which("git"):
        version = subprocess.run(["git", "--version"], capture_output=True, text=True)
        checks.append((OK, version.stdout.strip() or "git"))
    else:
        checks.append((FAIL, "git not found - install it from git-scm.com, then open a new "
                             "terminal"))

    out = Path(out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=out):
            pass
        checks.append((OK, f"output folder {out} (writable)"))
    except OSError as error:
        checks.append((FAIL, f"can't write to {out}: {error}"))
    return checks


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def model_checks(provider, model, offline):
    """Is the model set up, and does it answer? Each provider has its own first check;
    then one short test prompt shows the whole path works (and how long it takes)."""
    if provider == "mock":
        return [(OK, "mock: no model needed (for trying proof out, not real output)")]
    if not model:
        return [(FAIL, "no model chosen - pass --model or set PROOF_MODEL")]

    if provider == "ollama":
        checks = ollama_checks(model)
    elif provider == "anthropic":
        checks = [(OK, "ANTHROPIC_API_KEY is set")] if os.environ.get("ANTHROPIC_API_KEY") \
            else [(FAIL, "ANTHROPIC_API_KEY isn't set")]
    else:                                                  # openai-compatible
        base = os.environ.get("OPENAI_BASE_URL")
        checks = [(OK, f"OPENAI_BASE_URL = {base}")] if base else \
            [(FAIL, "OPENAI_BASE_URL isn't set (e.g. https://api.groq.com/openai/v1)")]
        if base and not os.environ.get("OPENAI_API_KEY"):
            checks.append((WARN, "OPENAI_API_KEY isn't set - most hosted APIs need one"))

    if any(level == FAIL for level, _ in checks):
        return checks
    if offline:
        return checks + [(WARN, "test prompt skipped (--offline)")]
    return checks + [test_prompt(provider, model)]


def ollama_checks(model):
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        response = requests.get(f"{url}/api/tags", timeout=10)
        installed = [m.get("name", "") for m in response.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return [(FAIL, f"Ollama doesn't answer at {url} - start the Ollama app, or run "
                       "`ollama serve`")]
    checks = [(OK, f"Ollama answers at {url}")]
    if model in installed or f"{model}:latest" in installed:
        checks.append((OK, f"model installed; context {ollama_num_ctx()} tokens -> about "
                           f"{scan_budget('ollama') // 1000}K characters of each repo per prompt"))
    else:
        choices = ", ".join(installed) or "none - run `ollama pull <model>`"
        checks.append((FAIL, f"model '{model}' isn't installed. Installed: {choices}"))
    return checks


def test_prompt(provider, model):
    """One tiny prompt. ask_llm stops the program on errors (sys.exit), so catch that
    and report it as a failed check instead."""
    start = time.monotonic()
    try:
        reply = ask_llm("Reply with the single word: ready", provider, model)
    except SystemExit as error:
        return (FAIL, f"test prompt failed: {error}")
    seconds = time.monotonic() - start
    if not reply.strip():
        return (WARN, f"test prompt got an empty reply after {seconds:.1f}s")
    slow = " (the first answer includes loading the model)" if provider == "ollama" else ""
    return (OK, f"test prompt answered in {seconds:.1f}s{slow}")


# ---------------------------------------------------------------------------
# Job boards
# ---------------------------------------------------------------------------

def board_checks(boards):
    """Read each board fresh. A board that answers but yields no jobs, or jobs with no
    title, link or text, has probably changed its format: the reader needs fixing."""
    checks = []
    with tempfile.TemporaryDirectory(prefix="proof_doctor_") as cache:   # don't touch apply's
        for board in boards:
            name = board_name(board)
            try:
                jobs, _ = read_board(board, cache, refresh=True)
            except FeedError as error:
                checks.append((FAIL, f"{name}: {error}"))
                continue
            complete = [j for j in jobs if j["title"] and j["url"] and j["text"]]
            if not jobs:
                checks.append((WARN, f"{name}: answered, but no jobs found - quiet day, or "
                                     "its format changed (feeds.py)"))
            elif len(complete) < len(jobs) * 0.8:
                checks.append((WARN, f"{name}: {len(jobs)} jobs, but only {len(complete)} have "
                                     "a title, link and text - its format may have changed"))
            else:
                checks.append((OK, f"{name}: {len(jobs)} jobs"))
    return checks


# ---------------------------------------------------------------------------
# Your projects and pitch log
# ---------------------------------------------------------------------------

def project_checks(out_dir):
    projects = load_case_studies(out_dir)
    if not projects:
        return [(WARN, f"no case studies in {out_dir} yet - run `proof case <repo>`")]
    summary = ", ".join(f"{p['slug']} ({p['placeholders']} gaps)" for p in projects)
    checks = [(OK, f"{len(projects)} case studies: {summary}")]
    for project in projects:
        folder = Path(out_dir) / project["slug"]
        meta = read_json(folder / "meta.json")
        problems = meta.get("problems", []) if isinstance(meta, dict) else []
        if problems:
            checks.append((WARN, f"{project['slug']}: {len(problems)} problem(s) left by the "
                                 f"checks, first: {problems[0]}"))
        if (folder / "case_study.new.md").exists():
            checks.append((WARN, f"{project['slug']}: case_study.new.md is waiting - you "
                                 "edited case_study.md, so the new version was put next to it"))
    gaps = sum(p["placeholders"] for p in projects)
    if gaps:
        checks.append((WARN, f"{gaps} [add: ...] gaps in total - fill them in each project's "
                             "facts.md, then run `proof case` again"))
    return checks


def log_checks(out_dir):
    path = Path(out_dir) / "pitches" / "log.json"
    if not path.exists():
        return [(OK, "no pitches yet")]
    try:
        log = load_log(out_dir)
    except json.JSONDecodeError as error:
        return [(FAIL, f"{path} is damaged ({error}) - fix it by hand or restore a copy")]
    statuses = {}
    for entry in log.values():
        statuses[entry.get("status", "?")] = statuses.get(entry.get("status", "?"), 0) + 1
    checks = [(OK, f"pitches in the log: {len(log)} (" +
               ", ".join(f"{count} {status}" for status, count in sorted(statuses.items())) + ")")]
    follow_up, give_up = to_do(log)
    if follow_up:
        checks.append((WARN, f"{len(follow_up)} due a follow-up: " +
                             ", ".join(f"proof followup {name}" for name, _ in follow_up)))
    if give_up:
        checks.append((WARN, f"{len(give_up)} with no reply 10+ days after the follow-up: " +
                             ", ".join(f"proof log {name} ignored" for name, _ in give_up)))
    return checks


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
