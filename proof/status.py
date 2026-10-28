"""
status.py - `proof status`: where each of your projects stands, and what needs you.

From git, on your computer (no network):
  branch, last commit, uncommitted changes, commits not pushed (or not pulled, as of the
  last fetch), unmerged branches, TODO/FIXME comments, how far behind the case study is.
From GitHub (skipped with --offline):
  did CI pass on the main branch, open issues, open pull requests.
  Public repos need nothing; private ones need a token in GITHUB_TOKEN (60 requests an
  hour without one, about 3 per project).
From proof itself:
  open tasks (tasks.py), and the client-ready checklist score (suggest.py).

Then a short "needs you" list: CI failing, work not pushed, quiet projects, stale case
studies. Saved to proof_output/status.md as well.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .github import GitHubError, gh_get
from .projects import github_repo, uncommitted
from .scan import git, list_files
from .suggest import checklist
from .tasks import load_tasks

QUIET_DAYS = 30            # no commit for this long: is the project paused, or forgotten?
STALE_CASE_STUDY = 10      # commits since the case study was written: time to update it


# ---------------------------------------------------------------------------
# Local: git
# ---------------------------------------------------------------------------

def local_status(repo, out_dir, today=None):
    today = today or datetime.now(timezone.utc)
    last = git(repo, "log", "-1", "--format=%cI%x09%s")
    when, _, subject = last.partition("\t")
    days = (today - datetime.fromisoformat(when)).days if when else None
    changed = uncommitted(repo)
    behind, ahead = ahead_behind(repo)
    branches = [b.strip(" *") for b in git(repo, "branch", "--no-merged").splitlines() if b.strip()]
    tasks = load_tasks(out_dir, repo.name)
    checks = checklist(repo, list_files(repo), Path(out_dir))
    return {
        "name": repo.name, "path": str(repo),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "-",
        "last_commit": subject, "days_quiet": days,
        "changed": len(changed), "ahead": ahead, "behind": behind,
        "has_remote": bool(git(repo, "remote")),
        "unmerged_branches": branches,
        "todos": todo_count(repo),
        "case_study_behind": case_study_behind(repo, out_dir),
        "tasks_open": sum(t["status"] == "todo" for t in tasks),
        "tasks_doing": [t for t in tasks if t["status"] == "doing"],
        "ready": (sum(passed for passed, *_ in checks), len(checks)),
    }


def ahead_behind(repo):
    """(commits on the remote branch you don't have, commits you haven't pushed), as of
    the last fetch. (None, None) if the branch tracks nothing."""
    counts = git(repo, "rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
    if len(counts) != 2:
        return None, None
    return int(counts[0]), int(counts[1])


def todo_count(repo):
    """TODO / FIXME comments in tracked files (Markdown left out: docs talk about TODOs)."""
    output = git(repo, "grep", "-I", "-c", "-E", r"\b(TODO|FIXME)\b", "--", ".", ":!*.md")
    return sum(int(line.rsplit(":", 1)[1]) for line in output.splitlines() if ":" in line)


def case_study_behind(repo, out_dir):
    """Commits since the case study was written, or None if there's no case study."""
    meta_file = Path(out_dir) / repo.name / "meta.json"
    try:
        commit = json.loads(meta_file.read_text(encoding="utf-8")).get("commit")
    except (OSError, ValueError):
        return None
    if not commit:
        return None
    count = git(repo, "rev-list", "--count", f"{commit}..HEAD")
    return int(count) if count.isdigit() else None


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def github_status(full_name):
    """{"ci", "ci_url", "issues", "prs", "url"} for "owner/repo", or {"error": ...}."""
    repo = gh_get(f"/repos/{full_name}")
    if repo is None:
        return {"error": "not found on GitHub (private? set GITHUB_TOKEN)"}
    pulls = gh_get(f"/repos/{full_name}/pulls?state=open&per_page=100") or []
    runs = gh_get(f"/repos/{full_name}/actions/runs?branch={repo['default_branch']}"
                  f"&per_page=1") or {}
    latest = (runs.get("workflow_runs") or [None])[0]
    if latest is None:
        ci, ci_url = "none", ""
    elif latest.get("status") != "completed":
        ci, ci_url = "running", latest.get("html_url", "")
    else:
        ci, ci_url = latest.get("conclusion") or "unknown", latest.get("html_url", "")
    return {"ci": ci, "ci_url": ci_url, "prs": len(pulls),
            # GitHub counts pull requests as issues too
            "issues": max(repo.get("open_issues_count", 0) - len(pulls), 0),
            "url": repo.get("html_url", "")}


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------

def collect(repos, out_dir, offline=False):
    """Status of every project. GitHub is asked only for repos whose origin is on GitHub,
    and not at all once it can't be reached (said once, in the notes)."""
    statuses, notes, github_ok = [], [], not offline
    for repo in repos:
        status = local_status(repo, out_dir)
        full_name = github_repo(repo)
        if full_name and github_ok:
            try:
                status["github"] = github_status(full_name)
            except GitHubError as error:
                github_ok = False
                notes.append(f"{error} - CI, issues and PRs left out")
        statuses.append(status)
    return statuses, notes


def needs_you(status):
    """What needs attention in one project, most urgent first."""
    items = []
    gh = status.get("github", {})
    if gh.get("ci") in ("failure", "timed_out", "startup_failure"):
        items.append(f"CI is failing on GitHub: {gh['ci_url']}")
    if gh.get("error"):
        items.append(f"GitHub: {gh['error']}")
    if status["changed"]:
        items.append(f"{status['changed']} uncommitted change(s) - commit or stash them")
    if status["ahead"]:
        items.append(f"{status['ahead']} commit(s) not pushed - git push")
    if status["behind"]:
        items.append(f"{status['behind']} commit(s) on GitHub you don't have - git pull")
    if not status["has_remote"]:
        items.append("not on GitHub yet - nobody can see it")
    for task in status["tasks_doing"]:
        items.append(f"task {task['id']} in progress: {task['title']} "
                     f"(proof task check {status['name']} {task['id']})")
    if status["days_quiet"] is not None and status["days_quiet"] >= QUIET_DAYS:
        items.append(f"no commits for {status['days_quiet']} days - paused, or finish it?")
    behind = status["case_study_behind"]
    if behind is not None and behind >= STALE_CASE_STUDY:
        items.append(f"case study is {behind} commits old - proof case \"{status['path']}\"")
    return items


def ago(days):
    if days is None:
        return "no commits"
    return "today" if days == 0 else f"{days}d ago"


def table(statuses):
    """One line per project, plain ASCII (Windows consoles and redirects stay happy)."""
    lines = [f"{'project':<20} {'branch':<12} {'last commit':<11} {'local':<16} "
             f"{'GitHub':<22} {'tasks':<8} ready"]
    for s in statuses:
        local = ", ".join(part for part in [
            f"{s['changed']} changed" if s["changed"] else "",
            f"{s['ahead']} unpushed" if s["ahead"] else ""] if part) or "clean"
        gh = s.get("github", {})
        if gh and not gh.get("error"):
            github = f"CI {gh['ci']}, {gh['issues']} iss, {gh['prs']} PR"
        else:
            github = "-"
        tasks = f"{s['tasks_open']}" + (f"+{len(s['tasks_doing'])}>" if s["tasks_doing"] else "")
        done, total = s["ready"]
        lines.append(f"{s['name'][:20]:<20} {s['branch'][:12]:<12} {ago(s['days_quiet']):<11} "
                     f"{local[:16]:<16} {github[:22]:<22} {tasks:<8} {done}/{total}")
    return lines


def report(statuses, notes=()):
    """The whole status: table, then what needs you, project by project."""
    lines = table(statuses)
    attention = [(s["name"], needs_you(s)) for s in statuses]
    attention = [(name, items) for name, items in attention if items]
    if attention:
        lines.append("\nNeeds you:")
        for name, items in attention:
            lines += [f"  {name}: {item}" for item in items]
    else:
        lines.append("\nNothing needs you: everything is committed, pushed and green.")
    lines += [f"\nNote: {note}" for note in notes]
    lines.append("\ntasks: open (+in progress>). ready: client-ready checklist "
                 "(proof suggest <project> for the list).")
    return "\n".join(lines)


def save_report(out_dir, text):
    path = Path(out_dir) / "status.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(f"# Project status - {stamp}\n\n```\n{text}\n```\n", encoding="utf-8")
    return path
