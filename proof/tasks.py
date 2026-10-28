"""
tasks.py - a task list per project, and handing tasks to a coding agent.

Tasks live in proof_output/<project>/tasks.json. They come from you (`proof task add`)
or from what proof already knows (`proof task import`): ideas from `proof suggest`,
unticked client-ready checklist items, TODO/FIXME comments, open GitHub issues, and
failing CI.

The coding is done by an agent (Claude Code, Codex, aider) or by you; proof does the
parts around it that an agent gets wrong or skips:
  brief   a precise, self-contained description: what, where to look, the project's
          stack, how to check the work (the real lint/test commands), and the rules
  start   a clean git branch for the task, the brief saved, optionally the agent started
  check   what changed since the start, every check command run, deleted tests flagged
  done    marked done with its commit; merging the branch stays your decision
"""

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from .github import GitHubError, gh_get
from .match import STOPWORDS
from .projects import check_commands, github_repo, uncommitted
from .scan import SKIP_DIRS, detect_stack, git, is_side_folder, list_files
from .stack import LANGUAGES
from .suggest import checklist, parse_ideas

STATUSES = ["todo", "doing", "done", "dropped"]
MAX_TODO_TASKS = 15          # a repo with 200 TODOs shouldn't bury everything else
# Words that say nothing about where the work is
GENERIC_WORDS = {"add", "fix", "make", "update", "change", "remove", "support", "new",
                 "client", "ready", "todo", "fixme", "feature", "better", "improve"}
# Files worth pointing an agent at (config like .yml/.toml is rarely where a task lives)
TASK_CODE_EXTENSIONS = (set(LANGUAGES) | {".prisma", ".graphql", ".sql"}) - {".md"}
AGENTS = ["claude", "codex", "aider"]


# ---------------------------------------------------------------------------
# The task list
# ---------------------------------------------------------------------------

def tasks_file(out_dir, project):
    return Path(out_dir) / project / "tasks.json"


def load_tasks(out_dir, project):
    path = tasks_file(out_dir, project)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_tasks(out_dir, project, tasks):
    path = tasks_file(out_dir, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def add_task(tasks, title, details="", where="", done_when="", source="you"):
    """Add a task unless one with the same title exists. Returns the new task or None."""
    if any(t["title"].lower() == title.lower() for t in tasks):
        return None
    task = {"id": max((t["id"] for t in tasks), default=0) + 1, "title": title,
            "details": details, "where": where, "done_when": done_when, "source": source,
            "status": "todo", "added": date.today().isoformat()}
    tasks.append(task)
    return task


def find_task(tasks, task_id):
    for task in tasks:
        if str(task["id"]) == str(task_id).lstrip("Tt#"):
            return task
    ids = ", ".join(str(t["id"]) for t in tasks) or "none yet"
    raise SystemExit(f"No task {task_id}. Task ids: {ids}")


def task_lines(tasks, show_closed=False):
    """'  3  [todo ]  Add a Results section   (checklist)'"""
    lines = []
    for task in tasks:
        if task["status"] in ("done", "dropped") and not show_closed:
            continue
        lines.append(f"  {task['id']:>3}  [{task['status']:<5}]  {task['title'][:70]}"
                     f"   ({task['source']})")
    return lines


# ---------------------------------------------------------------------------
# Import: tasks from what proof already knows about the project
# ---------------------------------------------------------------------------

def candidates(repo, out_dir, offline=False):
    """Possible tasks, as dicts for add_task. Most useful sources first."""
    found = []
    gh = github_repo(repo)
    if gh and not offline:
        found += github_tasks(gh)
    found += idea_tasks(Path(out_dir) / repo.name / "suggestions.md")
    for passed, what, why, fix in checklist(repo, list_files(repo), Path(out_dir)):
        # Facts live in proof_output, not the repo: a job for you, not a coding agent
        if not passed and not what.startswith("Case study facts"):
            found.append({"title": f"Client-ready: {what}", "details": f"{fix[0].upper()}"
                          f"{fix[1:]} ({why}).", "source": "checklist"})
    found += todo_tasks(repo)
    return found


def github_tasks(full_name):
    """Failing CI on the main branch, then open issues (pull requests left out)."""
    found = []
    try:
        repo = gh_get(f"/repos/{full_name}") or {}
        runs = gh_get(f"/repos/{full_name}/actions/runs?branch={repo.get('default_branch', 'main')}"
                      "&per_page=1") or {}
        latest = (runs.get("workflow_runs") or [{}])[0]
        if latest.get("conclusion") in ("failure", "timed_out"):
            found.append({"title": f"Fix failing CI ({latest.get('name', 'workflow')})",
                          "details": f"The last run on the main branch failed: "
                                     f"{latest.get('html_url', '')}. Read its log, fix the "
                                     "cause, and make it pass.", "source": "CI"})
        for issue in gh_get(f"/repos/{full_name}/issues?state=open&per_page=30") or []:
            if "pull_request" in issue:
                continue
            found.append({"title": f"#{issue['number']} {issue['title']}",
                          "details": (issue.get("body") or "")[:1500],
                          "source": f"issue #{issue['number']}"})
    except GitHubError as error:
        print(f"  (GitHub skipped: {error})")       # the other sources still work
    return found


def idea_tasks(suggestions_file):
    """The ideas `proof suggest` wrote, with their Where and Done when."""
    if not suggestions_file.exists():
        return []
    text = suggestions_file.read_text(encoding="utf-8")
    ideas = text.split("## Ideas", 1)[1] if "## Ideas" in text else ""
    ideas = ideas.split("## Tasks for a coding assistant")[0]
    return [{"title": idea["title"], "details": idea.get("What", ""),
             "where": idea.get("Where", ""), "done_when": idea.get("Done when", ""),
             "source": "suggest"} for idea in parse_ideas(ideas)]


def todo_tasks(repo):
    """TODO / FIXME comments: 'src/app.py:42: # TODO handle timeouts'."""
    output = git(repo, "grep", "-n", "-I", "-E", r"\b(TODO|FIXME)\b", "--", ".", ":!*.md")
    found = []
    for line in output.splitlines()[:MAX_TODO_TASKS]:
        path, line_no, text = (line.split(":", 2) + ["", ""])[:3]
        comment = re.split(r"\b(?:TODO|FIXME)\b[:\s-]*", text, maxsplit=1)[-1].strip(" */#-")
        found.append({"title": f"{comment[:60] or 'TODO'} ({path}:{line_no})",
                      "details": f"A comment in {path} line {line_no} says: {text.strip()}",
                      "where": path, "source": "TODO"})
    return found


# ---------------------------------------------------------------------------
# The brief: everything an agent needs, and nothing it has to guess
# ---------------------------------------------------------------------------

def brief(task, repo, branch=None):
    """Markdown brief for a coding agent (or for you)."""
    checks = check_commands(repo)
    related = related_files(repo, task)
    stack = ", ".join(detect_stack(repo)) or "see the README"
    lines = [f"# Task {task['id']} in {repo.name}: {task['title']}", "",
             "## What to do", task["details"] or task["title"], "",
             "## Where to look"]
    if task.get("where"):
        lines.append(f"- {task['where']} (named in the task)")
    if related:
        lines.append(f"- Files that mention this task's words (found by proof - check them): "
                     f"{', '.join(related)}")
    lines.append("- The README, for what the project does and how it's run")
    lines += ["", "## The project",
              f"- Folder: {repo}",
              f"- Stack: {stack}"]
    if branch:
        lines.append(f"- Work on the branch `{branch}` (already created and checked out)")
    lines += ["", "## Done when"]
    lines.append(f"- {task['done_when']}" if task.get("done_when") else
                 "- The task above works, and you've shown it (a test, or the command you ran)")
    if checks:
        lines.append("- These pass: " + ", ".join(f"`{c}`" for c in checks))
    else:
        lines.append("- (proof found no test command - add a test that shows the change works)")
    lines += ["", "## Rules",
              "- Keep the change small and about this task only: no unrelated refactors, "
              "renames or reformatting.",
              "- Match the existing code style. Add or update tests for what you change.",
              "- Never delete, skip or weaken a test to make it pass.",
              "- No keys or passwords in code: read them from environment variables.",
              "- When finished, commit on this branch with a clear message, and say what "
              "you didn't do or aren't sure about."]
    return "\n".join(lines) + "\n"


def related_files(repo, task, most=5):
    """Code files most related to the task's words (git grep, no model). A word in a
    file's name counts double ("CLI" -> cli.py), a word in its text once. The project's
    own name is left out: it's in every file."""
    own_name = set(re.split(r"[-_. ]+", repo.name.lower()))
    keywords = {w for w in re.findall(r"[a-z][a-z0-9_]{2,}", task["title"].lower())
                if w not in STOPWORDS and w not in GENERIC_WORDS and w not in own_name}
    code = {f.as_posix(): f for f in list_files(repo) if f.suffix in TASK_CODE_EXTENSIONS}
    scores = {}
    for path, f in code.items():
        in_name = keywords & set(re.findall(r"[a-z0-9]+", f.stem.lower()))
        if in_name:
            scores[path] = 2 * len(in_name)
    for word in sorted(keywords)[:8]:
        for path in git(repo, "grep", "-l", "-i", "-I", "-w", word).splitlines():
            if path in code:
                scores[path] = scores.get(path, 0) + 1
    ranked = sorted((path for path in scores if scores[path] >= 2),
                    key=lambda path: (-scores[path], is_side_folder(code[path]), path))
    return ranked[:most]


def brief_file(out_dir, project, task):
    return Path(out_dir) / project / "tasks" / f"T{task['id']}.md"


def agent_prompt(path):
    return (f"Do the task described in {path.resolve()}. Read the whole file first, then "
            "follow its rules. When you're done, tell me what you changed and how you "
            "checked it.")


def start_agent(agent, prompt, repo):
    """Run the agent in the project folder, in this terminal. Returns False if it isn't
    installed (then the person runs it themselves)."""
    program = shutil.which(agent)
    if not program:
        return False
    if agent == "aider":
        command = [program, "--message", prompt]
    else:                                         # claude, codex: the prompt is the first message
        command = [program, prompt]
    subprocess.run(command, cwd=repo)
    return True


# ---------------------------------------------------------------------------
# Start / check / done
# ---------------------------------------------------------------------------

def branch_name(task):
    words = re.findall(r"[a-z0-9]+", task["title"].lower())[:5]
    return f"task/{task['id']}-{'-'.join(words) or 'work'}"


def start(task, repo, new_branch=True):
    """Mark the task as started from a clean working tree, on its own branch.
    Returns the branch name. Stops if there are uncommitted changes: they would get
    mixed into the task's diff."""
    if uncommitted(repo):
        raise SystemExit(f"{repo.name} has uncommitted changes. Commit or stash them first, "
                         "so this task's changes stay separate.")
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if new_branch:
        branch = branch_name(task)
        if git(repo, "rev-parse", "--verify", "--quiet", branch):
            git(repo, "switch", branch)                # started before: carry on there
        elif not git_ok(repo, "switch", "-c", branch):
            raise SystemExit(f"Couldn't create the branch {branch} in {repo}.")
    task.update(status="doing", started=date.today().isoformat(), branch=branch)
    task.setdefault("base_commit", git(repo, "rev-parse", "HEAD"))
    return branch


def git_ok(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode == 0


def changes(task, repo):
    """(commits since the task started, files changed - committed or not, deleted tests)."""
    base = task.get("base_commit")
    if not base:
        return [], [], []
    commits = git(repo, "log", "--oneline", f"{base}..HEAD").splitlines()
    status = git(repo, "diff", "--name-status", base).splitlines()
    status += [f"A\t{path}" for path in
               git(repo, "ls-files", "--others", "--exclude-standard").splitlines()]
    # Build junk a repo forgot to .gitignore (__pycache__, node_modules ...) isn't a change
    status = [line for line in status
              if line.strip() and not SKIP_DIRS & set(line.split("\t")[-1].split("/"))]
    files = [line.split("\t")[-1] for line in status]
    deleted_tests = [line.split("\t")[-1] for line in status
                     if line.startswith("D") and re.search(r"test", line, re.IGNORECASE)]
    return commits, files, deleted_tests


def run_checks(repo, commands, say=print, timeout=900):
    """Run each check command in the project. Returns [(command, passed)].
    The commands come from projects.check_commands - fixed strings like "npm test", never
    text from a person or a model. shell=True lets Windows find npm.cmd and friends."""
    results = []
    for command in commands:
        say(f"  running: {command}")
        try:
            done = subprocess.run(command, shell=True, cwd=repo, capture_output=True,
                                  text=True, errors="replace", timeout=timeout)
            passed, output = done.returncode == 0, done.stdout + done.stderr
        except subprocess.TimeoutExpired:
            passed, output = False, f"(stopped after {timeout // 60} minutes)"
        say(f"    {'passed' if passed else 'FAILED'}")
        if not passed:
            say(failure_summary(output))
        results.append((command, passed))
    return results


ERROR_LINE = re.compile(r"^(E\s+)?[\w.]*(Error|Exception)\b.*:|error TS\d+|npm ERR!|"
                        r"Cannot find module|not recognized as|command not found")


def failure_summary(output, most=6):
    """What a failed check said, shortest useful form: the distinct error lines (the
    cause is usually there, not at the end), the last lines, and a hint for the common
    "not installed" case."""
    lines = output.strip().splitlines()
    errors = list(dict.fromkeys(line.strip() for line in lines if ERROR_LINE.search(line.strip())))
    shown = [f"      {line}" for line in errors[:most]]
    shown += ["      ..."] + [f"      {line}" for line in lines[-8:]]
    if re.search(r"No module named|ModuleNotFoundError", output):
        shown.append("    Hint: a package isn't installed in the Python running the tests. "
                     "Install the project's dependencies (pip install -e . or pip install -r "
                     "requirements.txt), best in a .venv inside the project: proof uses it.")
    elif re.search(r"Cannot find module|not recognized as|command not found", output):
        shown.append("    Hint: a tool or package is missing - run `npm install` (or the "
                     "project's install step) in the project first.")
    return "\n".join(shown)


def finish(task, repo):
    task.update(status="done", done=date.today().isoformat(),
                commit=git(repo, "rev-parse", "--short", "HEAD"))
