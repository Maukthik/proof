"""
apply.py - `proof apply`: find new jobs that fit your projects, best first.

1. read the job boards (feeds.py)
2. leave out jobs you've already been shown, and ones older than --days
3. score each against your projects: the same explainable match as `proof pitch`
4. keep the good fits, say why each fits and what it asks for that you don't show
   -> printed, and added to proof_output/jobs/<date>.md
5. `proof apply` in cli.py then drafts pitches for the top few

It never sends anything. Mass proposals are what make clients ignore pitches, and
sending for you could break a job board's terms.

A good fit: one of your projects shares at least `min_tech` technologies with the job
(Docker, Git and other everyday tools don't count), and your projects together show at
least a third of the technologies the job names.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .feeds import BOARD_NAMES
from .match import COMMON_TOOLS, rank_projects, tech_in

MIN_COVERAGE = 1 / 3
FORGET_AFTER_DAYS = 120          # seen.json keeps job ids this long


def job_text(job):
    """What the matching reads: everything the post says."""
    return "\n".join(part for part in [job["title"], job["company"], job["text"]] if part)


def judge(job, projects, min_tech=2):
    """How well your projects fit one job. Returns None if it isn't a good fit, else
    {"score", "projects": [(name, shared tech)], "asked", "shown", "missing"}."""
    text = job_text(job)
    ranked = rank_projects(text, projects)
    best = ranked[0]
    real_tech = [t for t in best["matched"] if t not in COMMON_TOOLS]
    asked = sorted(tech_in(text) - COMMON_TOOLS)
    shown = sorted({t for p in ranked for t in p["matched"]} & set(asked))
    if len(real_tech) < min_tech or len(shown) < len(asked) * MIN_COVERAGE:
        return None
    fitting = [(p["name"], p["matched"]) for p in ranked
               if p["matched"] and p["score"] >= best["score"] / 2][:3]
    return {"score": best["score"], "projects": fitting, "asked": asked, "shown": shown,
            "missing": sorted(set(asked) - set(shown))}


def is_recent(job, days, today=None):
    """Posted in the last `days` days. A job with no date counts as recent."""
    if not job["posted"]:
        return True
    try:
        posted = date.fromisoformat(job["posted"])
    except ValueError:
        return True
    return (today or date.today()) - posted <= timedelta(days=days)


def find_fits(jobs, projects, seen, days, min_tech, today=None):
    """New, recent jobs that fit, best first, as (job, fit). A job listed twice (the same
    post on two boards, or a repost) is kept once: the copy that scores best."""
    fits = []
    for job in jobs:
        if job["id"] in seen or not is_recent(job, days, today):
            continue
        fit = judge(job, projects, min_tech)
        if fit:
            fits.append((job, fit))
    fits.sort(key=lambda pair: -pair[1]["score"])
    kept, titles = [], set()
    for job, fit in fits:
        key = (job["title"].lower(), job["company"].lower())
        if key not in titles:
            kept.append((job, fit))
            titles.add(key)
    return kept


# ---------------------------------------------------------------------------
# Jobs already shown: proof_output/jobs/seen.json  {job id: date first seen}
# ---------------------------------------------------------------------------

def seen_file(out_dir):
    return Path(out_dir) / "jobs" / "seen.json"


def load_seen(out_dir):
    path = seen_file(out_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_seen(out_dir, seen, jobs, today=None):
    """Add these jobs, and forget ids older than FORGET_AFTER_DAYS (the boards have
    dropped those posts by then)."""
    today = today or date.today()
    for job in jobs:
        seen.setdefault(job["id"], today.isoformat())
    oldest = (today - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    seen = {job_id: day for job_id, day in seen.items() if day >= oldest}
    path = seen_file(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, indent=0), encoding="utf-8")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def board_name(board):
    """'remotive' -> 'Remotive'; a feed URL -> its site, 'jobs.example.com'."""
    if board.startswith(("http://", "https://")):
        return urlparse(board).netloc
    return BOARD_NAMES.get(board, board)


def headline(job):
    return f"{job['title']} - {job['company']}" if job["company"] else job["title"]


def why(fit):
    """'client-desk: fastapi, postgres; doppel: python'"""
    return "; ".join(f"{name}: {', '.join(tech)}" for name, tech in fit["projects"])


def console_lines(fits):
    lines = []
    for job, fit in fits:
        lines.append(f"  {fit['score']:5.1f}  {headline(job)[:70]}  ({board_name(job['board'])})")
        lines.append(f"         fits: {why(fit)}")
        if fit["missing"]:
            lines.append(f"         missing: {', '.join(fit['missing'])}")
        lines.append(f"         {job['url']}")
    return lines


def digest(fits, drafts, boards_read):
    """Markdown for proof_output/jobs/<date>.md. Each job links to its post and names the
    board it came from (the boards ask for that credit). drafts: {job id: pitch file}."""
    now = datetime.now().strftime("%H:%M")
    lines = [f"## {now} - {len(fits)} new job(s) that fit",
             f"Boards: {', '.join(boards_read) or 'none could be read'}", ""]
    for number, (job, fit) in enumerate(fits, start=1):
        place = f" · {job['where']}" if job["where"] else ""
        posted = f" · posted {job['posted']}" if job["posted"] else ""
        lines += [f"### {number}. {headline(job)}  (score {fit['score']:.1f})",
                  f"[{board_name(job['board'])}]({job['url']}){posted}{place}",
                  f"- Fits: {why(fit)}",
                  f"- You show {len(fit['shown'])} of the {len(fit['asked'])} technologies "
                  f"it names" + (f"; missing: {', '.join(fit['missing'])}"
                                 if fit["missing"] else "")]
        if job["id"] in drafts:
            lines.append(f"- Pitch draft: {drafts[job['id']]}")
        lines.append("")
    return "\n".join(lines)


def save_digest(out_dir, text, today=None):
    """Add this run to today's file (several runs a day each get a section)."""
    path = Path(out_dir) / "jobs" / f"{(today or date.today()).isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_text(encoding="utf-8") if path.exists() else \
        f"# Jobs that fit your projects - {(today or date.today()).isoformat()}\n\n"
    path.write_text(before + text + "\n", encoding="utf-8")
    return path
