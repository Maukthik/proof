"""
proof - turn your repos into proof of skill.

Commands:
  case    REPO [REPO ...]   write a case study for each repo (skips unchanged ones)
  pitch   JOB               match your projects to a job post and write a pitch
                            (JOB = a text file, a URL, or - to paste it)
  lint    PITCH_FILE        check a pitch for common mistakes
  profile                   Upwork/LinkedIn "about" text + resume bullets
  site                      build a portfolio page from all case studies
  log     [PITCH STATUS]    track sent pitches and replies, see what works
  apply   [BOARD ...]       new jobs from job boards that fit your projects, + pitch drafts
  followup PITCH            a short follow-up for a pitch that got no reply
  prep    PITCH|JOB         a brief for the client call: likely questions, gaps, intro

Examples:
  proof case https://github.com/you/doppel ./rag-chatbot --provider ollama
  proof pitch upwork_job.txt
  proof site --owner "Maukthik J" --contact "you@email.com"

Try the whole flow with no LLM:  add --provider mock
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

from .apply import (board_name, console_lines, digest, find_fits, headline, is_recent,
                    job_text, load_seen, save_digest, save_seen)
from .facts import fingerprint, read_facts, start_facts_file
from .feeds import BOARDS, CACHE_HOURS, DEFAULT_BOARDS, FeedError, read_board
from .jobpost import read_job, slug
from . import casestudy, dataset, evaluate, suggest
from .lint import lint_followup, lint_pitch, lint_prep, print_problems, unsupported_numbers
from .llm import DEFAULT_MODELS, ask_llm, scan_budget, strip_wrapper
from .match import COMMON_TOOLS, rank_projects, tech_in
from .portfolio import build_site, load_case_studies
from .prompts import FOLLOW_UP, PITCH, PREP, PROFILE, SUGGEST
from .scan import (detect_stack, get_repo, has_enough_to_write_about, head_commit, is_url,
                   list_files, pushed_commit, remote_head, repo_name, scan_repo, web_url)
from .tracker import STATUSES, find_pitch, load_log, record_pitch, report, update_status


# ---------------------------------------------------------------------------
# case
# ---------------------------------------------------------------------------

def expand_repo_lists(repo_args):
    """'@training/repos.txt' -> the repos listed in that file (one per line, # comments)."""
    repos = []
    for arg in repo_args:
        if not arg.startswith("@"):
            repos.append(arg)
            continue
        list_file = Path(arg[1:])
        if not list_file.is_file():
            sys.exit(f"No such list of repos: {list_file}")
        for line in list_file.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                repos.append(line)
    return repos


def cmd_case(args):
    args.repos = expand_repo_lists(args.repos)
    # Catch a mistyped folder now, not after minutes of model work on the others
    missing = [arg for arg in args.repos if not is_url(arg) and not Path(arg).expanduser().is_dir()]
    if missing:
        sys.exit("Not a folder: " + ", ".join(missing) + "\nNothing was written. Fix the path, "
                 "or use the GitHub URL (https://github.com/you/repo).")
    for repo_arg in args.repos:
        # A temporary folder for GitHub clones; deleted when we're done with this repo
        with tempfile.TemporaryDirectory(prefix="proof_") as clone_dir:
            write_case_study(repo_arg, clone_dir, args)


def write_case_study(repo_arg, clone_dir, args):
    name = repo_name(repo_arg)
    out_dir = Path(args.out) / name
    meta = load_meta(out_dir)
    facts = read_facts(out_dir)

    # Skip if neither the code nor your facts changed since last time.
    # For GitHub URLs we can ask for the latest commit without cloning.
    if not (args.force or args.dry_run) and (out_dir / "case_study.md").exists():
        commit = remote_head(repo_arg) if is_url(repo_arg) else head_commit(get_repo(repo_arg))
        if commit and meta.get("commit") == commit and meta.get("facts") == fingerprint(facts):
            print(f"[{name}] up to date - skipping (use --force to redo)")
            return

    repo = get_repo(repo_arg, clone_dir)
    if not args.force and not has_enough_to_write_about(repo, list_files(repo)):
        print(f"[{name}] skipped: no code and no real README, so the model could only make "
              f"things up. Push some code (or use --force).")
        return
    print(f"[{name}] scanning ...")
    removed = []
    repo_scan = scan_repo(repo, budget=args.scan_chars or scan_budget(args.provider),
                          removed=removed)
    warn_about_secrets(name, removed)
    prompt = casestudy.build_prompt(repo_scan, facts)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Kept with every case study: the exact input, for `proof dataset` (training data)
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    if args.dry_run:
        print(f"[{name}] dry run - prompt saved to {out_dir / 'prompt.txt'}")
        return

    print(f"[{name}] writing case study with {args.provider}/{args.model} ...")
    result = casestudy.write(repo, repo_scan, facts, args.provider, args.model,
                             say=lambda message: print(f"[{name}] {message}"))
    save_case_study(result["case_study"], result["problems"], repo_arg, repo, facts, out_dir,
                    meta, args.provider, args.model)


def save_case_study(case_study, problems, repo_arg, repo, facts, out_dir, meta, provider, model):
    """Link results and check the diagram, then write case_study.md (or case_study.new.md
    if you edited the old one) and meta.json, and say what's left to do."""
    name = out_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    case_study, dashed = casestudy.finish(case_study, repo, facts, web_url(repo_arg, repo),
                                          pushed_commit(repo))

    # Never overwrite a case study you edited: put the new one next to it instead
    edited = was_edited(out_dir / "case_study.md", meta)
    target = out_dir / ("case_study.new.md" if edited else "case_study.md")
    target.write_text(case_study + "\n", encoding="utf-8")

    meta = {
        "name": name, "source": repo_arg, "commit": head_commit(repo),
        "stack": detect_stack(repo, list_files(repo)),
        "provider": provider, "model": model,
        "generated": date.today().isoformat(),
        "facts": fingerprint(facts),                   # to notice when you add facts
        "written": fingerprint(case_study + "\n"),     # to notice when you edit it
        "problems": problems,                          # what the checks still found
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    report_case_study(name, target, case_study, edited, problems)
    if dashed:
        print(f"[{name}]   {dashed} diagram arrow(s) aren't backed by an import in the code: "
              f"drawn dashed (fine for HTTP calls or README-documented flows)")
    if start_facts_file(out_dir, name, case_study):
        print(f"[{name}] started {out_dir / 'facts.md'} - fill in the real numbers there, "
              f"then run this again to close the gaps")


def warn_about_secrets(name, removed):
    """Secrets found in the code were kept out of the prompt - but they're still in the repo."""
    for path in dict.fromkeys(path for path, _ in removed):
        kinds = sorted({kind for p, kind in removed if p == path})
        print(f"[{name}]   SECRET  {path}: {', '.join(kinds)} - kept out of the prompt, "
              f"but it's in your repo: move it to .env and rotate it")


def report_case_study(name, target, case_study, edited, problems):
    gaps = len(re.findall(r"\[add:", case_study))
    print(f"[{name}] saved {target}" + (f"  ({gaps} [add: ...] gaps to fill)" if gaps else ""))
    if edited:
        print(f"[{name}]   you edited case_study.md, so it was left alone. Copy what you "
              f"want from {target.name}, or delete case_study.md and use the new one.")
    for problem in problems:
        print(f"[{name}]   WARN  {problem}")


def was_edited(case_file, meta):
    """True if case_study.md isn't exactly what proof last wrote there (you changed it)."""
    if not case_file.exists():
        return False
    return fingerprint(case_file.read_text(encoding="utf-8")) != meta.get("written")


def load_meta(out_dir):
    meta_file = out_dir / "meta.json"
    return json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}


def cmd_eval(args):
    args.repos = expand_repo_lists(args.repos)
    missing = [arg for arg in args.repos if not is_url(arg) and not Path(arg).expanduser().is_dir()]
    if missing:
        sys.exit("Not a folder: " + ", ".join(missing))
    models = args.models or [args.model]
    with tempfile.TemporaryDirectory(prefix="proof_") as clone_dir:
        evaluate.run(args.repos, models, args.provider, args.out,
                     args.scan_chars or scan_budget(args.provider), clone_dir)


def cmd_dataset(args):
    folders = args.sources or [args.out]
    examples = dataset.collect(folders, exclude=set(args.exclude or []))
    if examples:
        dataset.write(examples, args.to)
    print(dataset.summary(examples, args.to))


def cmd_suggest(args):
    if not is_url(args.repo) and not Path(args.repo).expanduser().is_dir():
        sys.exit(f"Not a folder: {args.repo}")
    with tempfile.TemporaryDirectory(prefix="proof_") as clone_dir:
        repo = get_repo(args.repo, clone_dir)
        out_dir = Path(args.out)
        files = list_files(repo)
        checks = suggest.checklist(repo, files, out_dir)
        projects = [p for p in load_case_studies(out_dir) if p["slug"] == repo.name]
        project_text = projects[0]["text"] if projects else ""
        names = {repo.name} | {p["name"] for p in projects}
        wanted = suggest.asked_for(out_dir, names, project_text + " ".join(detect_stack(repo)))

        ideas_text, ideas, warnings = None, [], []
        if not args.no_ai:
            repo_scan = scan_repo(repo, budget=scan_budget(args.provider))
            print(f"[{repo.name}] asking {args.provider}/{args.model} for ideas ...")
            ideas_text = strip_wrapper(ask_llm(SUGGEST.format(
                repo_scan=repo_scan, checklist=checklist_text(checks),
                wanted=", ".join(f"{t} ({n})" for t, n in wanted.items()) or "(nothing yet)"),
                args.provider, args.model))
            ideas = suggest.parse_ideas(ideas_text)
            unknown = suggest.unknown_files(ideas, [f.as_posix() for f in files], [repo_scan])
            if unknown:
                warnings.append(f"these files aren't in the repo: {', '.join(unknown)} - "
                                "the model may have guessed them")

    target = out_dir / repo.name / "suggestions.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(suggest.report(repo.name, checks, wanted, ideas_text, ideas, warnings),
                      encoding="utf-8")
    done = sum(passed for passed, *_ in checks)
    print(f"[{repo.name}] checklist {done}/{len(checks)}, {len(ideas)} ideas -> {target}")
    for passed, what, _, fix in checks:
        if not passed:
            print(f"  [ ] {what}: {fix}")
    for warning in warnings:
        print(f"  WARN  {warning}")


def checklist_text(checks):
    return "\n".join(f"- [{'x' if passed else ' '}] {what}" for passed, what, _, _ in checks)


# ---------------------------------------------------------------------------
# scan / check: let a coding agent (Claude Code, Cursor, Codex) write case studies,
# with proof as the source of facts and the checker (an idea from REA)
# ---------------------------------------------------------------------------

def cmd_scan(args):
    """Print what the model would see for a repo - secrets removed - so an agent or a
    person can write the case study themselves."""
    with tempfile.TemporaryDirectory(prefix="proof_") as clone_dir:
        repo = get_repo(args.repo, clone_dir)
        facts = read_facts(Path(args.out) / repo.name)
        removed = []
        repo_scan = scan_repo(repo, budget=args.scan_chars or 70_000, removed=removed)
        print(casestudy.build_prompt(repo_scan, facts) if args.prompt else repo_scan)
        warn_about_secrets(repo.name, removed)


def cmd_check(args):
    """Run every check on a case study written by anyone. --save files it like `case` does."""
    text = Path(args.file).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="proof_") as clone_dir:
        repo = get_repo(args.repo, clone_dir)
        out_dir = Path(args.out) / repo.name
        facts = read_facts(out_dir)
        repo_scan = scan_repo(repo, budget=args.scan_chars or 70_000)
        problems = casestudy.review(text, casestudy.review_context(repo, repo_scan, facts))
        for problem in problems:
            print(f"  WARN  {problem}")
        if not problems:
            print("Check: no problems found.")
        if args.save:
            save_case_study(text, problems, args.repo, repo, facts, out_dir, load_meta(out_dir),
                            "agent", "written outside proof")
    sys.exit(1 if problems else 0)


# ---------------------------------------------------------------------------
# pitch / lint / profile
# ---------------------------------------------------------------------------

def project_block(project):
    """One project as the LLM sees it in pitch and profile prompts."""
    block = f"--- PROJECT: {project['name']} ---\n{project['text']}"
    if project["facts"]:
        block += f"\n\nFacts from the developer:\n{project['facts']}"
    return block


def require_case_studies(out_dir):
    projects = load_case_studies(out_dir)
    if not projects:
        sys.exit(f"No case studies in {out_dir}. Run `proof case <repo>` first.")
    return projects


def searchable(projects):
    """Projects as the matcher reads them: case study, your facts and the detected stack."""
    return [{**p, "text": "\n".join([p["text"], p["facts"], " ".join(p["stack"])]),
             "case_study": p["text"]} for p in projects]


def choose_projects(job, projects, top, say=print):
    """The projects to use as evidence for this job, best first.
    Evidence = projects that share real tech with the job and score at least half as
    well as the best one (Docker alone doesn't make a project relevant).
    If none share any tech, use the best one anyway."""
    ranked = rank_projects(job, searchable(projects))
    say("Project match for this job:")
    for p in ranked:
        say(f"  {p['score']:5.1f}  {p['name']:<28} {', '.join(p['matched']) or '-'}")
    best = ranked[0]["score"]
    chosen = [p for p in ranked if p["matched"] and p["score"] >= best / 2][:top]
    if not chosen:
        say("  (no shared tech - this job may not suit your current projects)")
        chosen = ranked[:1]
    return [{**p, "text": p["case_study"]} for p in chosen]


def pitch_folder(out_dir):
    return Path(out_dir) / "pitches"


def write_pitch(job, job_name, source, projects, args, say=print):
    """Pick the projects, write the pitch, save it (with the job post next to it, for
    `proof followup` and `proof prep`) and log it as a draft.
    Returns (pitch file, pitch text, lint problems)."""
    chosen = choose_projects(job, projects, args.top, say)
    say(f"Writing pitch using: {', '.join(p['name'] for p in chosen)} ...")
    case_studies = "\n\n".join(project_block(p) for p in chosen)
    pitch = strip_wrapper(ask_llm(PITCH.format(job=job, case_studies=case_studies),
                                  args.provider, args.model))

    folder = pitch_folder(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    pitch_file = folder / f"{job_name}.md"
    pitch_file.write_text(pitch + "\n", encoding="utf-8")
    (folder / f"{job_name}.job.txt").write_text(job + "\n", encoding="utf-8")
    matched = sorted({term for p in chosen for term in p["matched"]})
    record_pitch(args.out, job_name, source, [p["name"] for p in chosen], matched,
                 job_tech=tech_in(job))
    problems = lint_pitch(pitch, job, sources=[project_block(p) for p in chosen])
    return pitch_file, pitch, problems


def cmd_pitch(args):
    job, job_name = read_job(args.job)
    projects = require_case_studies(args.out)
    pitch_file, pitch, problems = write_pitch(job, job_name,
                                              args.job if args.job != "-" else "pasted",
                                              projects, args)
    print(f"Saved {pitch_file}\n")
    print(pitch, "\n")
    print_problems(problems)
    print(f"\nWhen you send it:  proof log {job_name} sent")


# ---------------------------------------------------------------------------
# apply / followup / prep: from job boards to the client call
# ---------------------------------------------------------------------------

def cmd_apply(args):
    """Read job boards, list the new jobs that fit your projects, draft pitches for the
    best few. Sends nothing: you read, fix and send each pitch yourself."""
    projects = require_case_studies(args.out)
    cache_dir = Path(args.out) / "jobs" / "cache"
    jobs, boards_read, saved_copies = [], [], []
    for board in args.boards or DEFAULT_BOARDS:
        try:
            found, cached = read_board(board, cache_dir, refresh=args.refresh)
        except FeedError as error:
            print(f"  WARN  {board}: {error}")
            continue
        print(f"  {board_name(board)}: {len(found)} jobs" + (" (saved copy, under "
              f"{CACHE_HOURS}h old)" if cached else ""))
        jobs += found
        boards_read.append(board_name(board))
        saved_copies.append(cached)
    if not boards_read:
        sys.exit("No job board could be read. Check your internet connection, or try "
                 "again later (--refresh skips the saved copies).")

    seen = load_seen(args.out)
    skip = {} if args.all else seen
    fits = find_fits(jobs, searchable(projects), skip, args.days, args.min_tech)
    new = sum(1 for job in jobs if job["id"] not in skip and is_recent(job, args.days))
    print(f"\n{new} new job(s) from the last {args.days} days, {len(fits)} fit your projects"
          + (":" if fits else "."))
    for line in console_lines(fits):
        print(line)
    if not new and any(saved_copies):
        print(f"(Boards are read again {CACHE_HOURS}h after the last time; --refresh to read "
              f"them now, --all to see jobs you've been shown before.)")

    drafts = {}
    # Jobs that already have a pitch (from an earlier run, or `proof pitch <url>`) are skipped
    drafted = {entry.get("source") for entry in load_log(args.out).values()}
    to_draft = [] if args.no_ai else [(job, fit) for job, fit in fits
                                      if job["url"] not in drafted][:args.draft]
    if to_draft:
        print(f"\nDrafting pitches for the top {len(to_draft)} ...")
    for job, _ in to_draft:
        name = unused_name(pitch_folder(args.out), slug(headline(job), max_words=8) or "job")
        pitch_file, _, problems = write_pitch(job_text(job), name, job["url"], projects, args,
                                              say=lambda message: None)
        drafts[job["id"]] = pitch_file.as_posix()
        warnings = sum(level != "INFO" for level, _ in problems)
        print(f"  {pitch_file}" + (f"  ({warnings} lint warning(s): proof lint {pitch_file} "
                                   f"--job {pitch_file.with_suffix('.job.txt')})"
                                   if warnings else ""))

    save_seen(args.out, seen, jobs)
    if fits:
        path = save_digest(args.out, digest(fits, drafts, boards_read))
        print(f"\nList saved to {path}")
    if drafts:
        print("Read each draft, make it yours, send it yourself, then:  "
              "proof log <pitch name> sent")


def unused_name(folder, name):
    """'python-dev' or, if a pitch already has that name, 'python-dev-2' ... - never
    overwrite a pitch you may have sent."""
    candidate, number = name, 2
    while (folder / f"{candidate}.md").exists():
        candidate, number = f"{name}-{number}", number + 1
    return candidate


def find_logged_pitch(out_dir, name):
    """(name, log entry, pitch text, job text) for a pitch in the log."""
    log = load_log(out_dir)
    name = find_pitch(log, name)
    folder = pitch_folder(out_dir)
    pitch_file = folder / f"{name}.md"
    pitch = pitch_file.read_text(encoding="utf-8") if pitch_file.exists() else ""
    job_file = folder / f"{name}.job.txt"
    if job_file.exists():
        job = job_file.read_text(encoding="utf-8")
    elif log[name].get("source", "pasted") != "pasted":
        job = read_job(log[name]["source"])[0]        # pitches from before job.txt was kept
    else:
        job = ""
    return name, log[name], pitch, job


def logged_projects(out_dir, entry):
    projects = require_case_studies(out_dir)
    used = [p for p in projects if p["name"] in entry.get("projects", [])]
    return used or projects[:1]


def cmd_followup(args):
    name, entry, first, job = find_logged_pitch(args.out, args.pitch)
    if entry["status"] in ("replied", "won"):
        sys.exit(f"{name} already got a reply - no follow-up needed. Getting ready for the "
                 f"call?  proof prep {name}")
    if not first:
        sys.exit(f"No pitch file for {name} in {pitch_folder(args.out)}.")
    if entry["status"] == "draft":
        print(f"Note: {name} isn't marked as sent. If you sent it:  proof log {name} sent")
    if entry["status"] == "followed-up":
        print(f"Note: you already followed up on {name}. A second follow-up rarely helps.")

    projects = logged_projects(args.out, entry)
    case_studies = "\n\n".join(project_block(p) for p in projects)
    print(f"Writing a follow-up using: {', '.join(p['name'] for p in projects)} ...")
    text = strip_wrapper(ask_llm(FOLLOW_UP.format(job=job or "(not saved)", pitch=first,
                                                  case_studies=case_studies),
                                 args.provider, args.model))
    target = pitch_folder(args.out) / f"{name}.followup.md"
    target.write_text(text + "\n", encoding="utf-8")
    print(f"Saved {target}\n")
    print(text, "\n")
    print_problems(lint_followup(text, first, [project_block(p) for p in projects]))
    print(f"\nWhen you send it:  proof log {name} followed-up")


def cmd_prep(args):
    """A one-page brief for a client call: likely questions with answers from your
    projects, the gaps to be ready for, questions to ask them, a 30-second intro."""
    is_job = args.target == "-" or args.target.startswith(("http://", "https://")) \
        or Path(args.target).is_file()
    if is_job:
        job, name = read_job(args.target)
        pitch, notes = "", ""
        projects = choose_projects(job, require_case_studies(args.out), args.top)
    else:
        name, entry, pitch, job = find_logged_pitch(args.out, args.target)
        notes = "\n".join(entry.get("notes", []))
        projects = logged_projects(args.out, entry)
    if not job:
        sys.exit(f"The job post for {name} wasn't saved. Give it directly:  "
                 f"proof prep <job file or URL>")

    # Gaps: what the job (or the client's reply, in your notes) names that NONE of your
    # projects show - not just the projects chosen for this job
    shown = set()
    for project in searchable(require_case_studies(args.out)):
        shown |= tech_in(project["text"])
    gaps = sorted(tech_in(job + "\n" + notes) - shown - COMMON_TOOLS)
    header = (f"# Call prep: {name}\n\n"
              f"Projects to talk about: {', '.join(p['name'] for p in projects)}\n"
              f"Not shown in any project: {', '.join(gaps) or 'nothing - you cover it all'}\n")

    brief, problems = "", []
    if not args.no_ai:
        case_studies = "\n\n".join(project_block(p) for p in projects)
        print(f"Writing the call brief with {args.provider}/{args.model} ...")
        brief = strip_wrapper(ask_llm(PREP.format(job=job, pitch=pitch or "(none)",
                                                  notes=notes or "(none)",
                                                  case_studies=case_studies,
                                                  gaps=", ".join(gaps) or "(none)"),
                                      args.provider, args.model))
        problems = lint_prep(brief, [project_block(p) for p in projects] + [job, pitch, notes])

    target = Path(args.out) / "prep" / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header + ("\n" + brief + "\n" if brief else ""), encoding="utf-8")
    print(f"Saved {target}\n")
    print(header)
    if brief:
        print(brief, "\n")
        print_problems(problems, ok_message="Check: every claim traces to your case studies.")


def cmd_lint(args):
    pitch = Path(args.pitch).read_text(encoding="utf-8")
    job = read_job(args.job)[0] if args.job else ""
    # Numbers are checked against your case studies, if you have any
    sources = [project_block(p) for p in load_case_studies(args.out)] or None
    problems = lint_pitch(pitch, job, sources)
    print_problems(problems)
    sys.exit(1 if any(level == "ERROR" for level, _ in problems) else 0)


def cmd_profile(args):
    projects = require_case_studies(args.out)
    if args.only:
        projects = [p for p in projects if p["slug"] in args.only or p["name"] in args.only]
        if not projects:
            sys.exit(f"No case studies called {', '.join(args.only)} in {args.out}.")
    projects, left_out = fit_to_budget(projects, scan_budget(args.provider))
    if left_out:
        print(f"Left out (they don't fit the model's context): {', '.join(left_out)}. "
              f"Pick projects with --only to choose.")
    case_studies = "\n\n".join(project_block(p) for p in projects)
    print(f"Writing profile from: {', '.join(p['name'] for p in projects)} ...")
    profile = strip_wrapper(ask_llm(PROFILE.format(case_studies=case_studies),
                                    args.provider, args.model))

    profile_file = Path(args.out) / "profile.md"
    profile_file.write_text(profile + "\n", encoding="utf-8")
    print(f"Saved {profile_file}\n")
    print(profile, "\n")

    problems = []
    if "[add:" in profile:
        problems.append(("ERROR", "Unfilled [add: ...] placeholder - replace or delete it."))
    numbers = unsupported_numbers(profile, [case_studies])
    if numbers:
        problems.append(("WARN", f"Numbers not in your case studies: {', '.join(numbers)}. "
                                 "Make sure they're true."))
    print_problems(problems, ok_message="Check: no placeholders or unsupported numbers.")


def fit_to_budget(projects, budget):
    """As many projects as fit in `budget` characters, the most complete ones (fewest
    [add: ...] gaps) first. Returns (kept, names of the ones left out)."""
    kept, left_out, used = [], [], 0
    for p in sorted(projects, key=lambda p: p["placeholders"]):
        size = len(project_block(p))
        if used + size > budget and kept:
            left_out.append(p["name"])
            continue
        kept.append(p)
        used += size
    return kept, left_out


# ---------------------------------------------------------------------------
# site / log
# ---------------------------------------------------------------------------

def cmd_site(args):
    page, projects = build_site(args.out, owner=args.owner, contact=args.contact)
    count = "1 project" if len(projects) == 1 else f"{len(projects)} projects"
    print(f"Portfolio with {count}: {page}")
    for p in projects:
        if p["placeholders"]:
            print(f"  WARN  {p['name']}: {p['placeholders']} [add: ...] gaps still showing "
                  f"(highlighted yellow). Fill them before publishing.")


def cmd_log(args):
    if args.pitch and not args.status:
        sys.exit(f"Say what happened: proof log {args.pitch} <{'|'.join(STATUSES)}>")
    if args.pitch:
        name = update_status(args.out, args.pitch, args.status, args.note)
        print(f"{name}: {args.status}")
        return
    print(report(load_log(args.out)))


# ---------------------------------------------------------------------------
# Command-line setup
# ---------------------------------------------------------------------------

def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="proof_output", help="Output folder")
    common.add_argument("--provider", default=os.environ.get("PROOF_PROVIDER", "anthropic"),
                        choices=["anthropic", "ollama", "openai", "mock"])
    common.add_argument("--model", default=os.environ.get("PROOF_MODEL"))

    parser = argparse.ArgumentParser(prog="proof",
                                     description="Turn your repos into proof of skill.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("case", parents=[common], help="Write case studies for repos")
    p.add_argument("repos", nargs="+", help="Local folders, GitHub URLs, or @list.txt")
    p.add_argument("--force", action="store_true", help="Redo even if unchanged")
    p.add_argument("--dry-run", action="store_true", help="Save prompts, don't call the LLM")
    p.add_argument("--scan-chars", type=int, default=None,
                   help="How much of the repo the model sees (default: fits the model). "
                        "Set it to make training data for a smaller model's context.")
    p.set_defaults(func=cmd_case)

    p = sub.add_parser("scan", parents=[common], help="Print what the model would see")
    p.add_argument("repo", help="Local folder or GitHub URL")
    p.add_argument("--prompt", action="store_true", help="The whole prompt, not just the scan")
    p.add_argument("--scan-chars", type=int, default=None, help="How much of the repo to show")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("check", parents=[common], help="Check a case study written by anyone")
    p.add_argument("file", help="The case study (Markdown)")
    p.add_argument("--repo", required=True, help="The repo it's about (folder or GitHub URL)")
    p.add_argument("--save", action="store_true",
                   help="Add source links, check the diagram, save it to the output folder")
    p.add_argument("--scan-chars", type=int, default=None, help="How much of the repo to compare")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("eval", parents=[common], help="Score models on writing case studies")
    p.add_argument("repos", nargs="+", help="Local folders, GitHub URLs, or @list.txt")
    p.add_argument("--models", nargs="+", help="Models to compare (default: --model)")
    p.add_argument("--scan-chars", type=int, default=None, help="How much of each repo to show")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("dataset", parents=[common], help="Fine-tuning data from good case studies")
    p.add_argument("--from", dest="sources", nargs="+", help="Output folders (default: --out)")
    p.add_argument("--to", default="training/data.jsonl", help="JSONL file to write")
    p.add_argument("--exclude", nargs="+", help="Repos to keep out (e.g. the ones you eval on)")
    p.set_defaults(func=cmd_dataset)

    p = sub.add_parser("suggest", parents=[common], help="What to build next in a project")
    p.add_argument("repo", help="Local folder or GitHub URL")
    p.add_argument("--no-ai", action="store_true", help="Checklist and client asks only")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("pitch", parents=[common], help="Write a pitch for a job post")
    p.add_argument("job", help="Job post: a text file, a URL, or - to paste it")
    p.add_argument("--top", type=int, default=2, help="How many projects to use")
    p.set_defaults(func=cmd_pitch)

    p = sub.add_parser("apply", parents=[common],
                       help="Find new jobs that fit your projects, draft pitches for the best")
    p.add_argument("boards", nargs="*", metavar="BOARD",
                   help=f"Job boards: {', '.join(BOARDS)}, or an RSS/Atom feed URL "
                        f"(default: {' '.join(DEFAULT_BOARDS)})")
    p.add_argument("--days", type=int, default=14, help="Only jobs posted in the last N days")
    p.add_argument("--draft", type=int, default=3, help="Draft pitches for the top N fits")
    p.add_argument("--min-tech", type=int, default=2,
                   help="Technologies a project must share with a job (default 2)")
    p.add_argument("--top", type=int, default=2, help="How many projects each pitch uses")
    p.add_argument("--no-ai", action="store_true", help="Just list the fits, draft nothing")
    p.add_argument("--all", action="store_true", help="Include jobs you've been shown before")
    p.add_argument("--refresh", action="store_true",
                   help=f"Read the boards again even if the saved copy is under {CACHE_HOURS}h old")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("followup", parents=[common], help="Draft a follow-up for a sent pitch")
    p.add_argument("pitch", help="Pitch name (as shown by `proof log`)")
    p.set_defaults(func=cmd_followup)

    p = sub.add_parser("prep", parents=[common], help="Get ready for a client call")
    p.add_argument("target", help="Pitch name from `proof log`, or a job post (file, URL, -)")
    p.add_argument("--top", type=int, default=2, help="Projects to use, for a job post")
    p.add_argument("--no-ai", action="store_true", help="Only the fit and the gaps")
    p.set_defaults(func=cmd_prep)

    p = sub.add_parser("lint", parents=[common], help="Check a pitch")
    p.add_argument("pitch", help="Pitch text file")
    p.add_argument("--job", help="Job post (file or URL), to check for missing tech")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("profile", parents=[common], help="Profile text + resume bullets")
    p.add_argument("--only", nargs="+", help="Use only these projects")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("site", parents=[common], help="Build portfolio page")
    p.add_argument("--owner", default="My projects", help="Your name for the page title")
    p.add_argument("--contact", default="", help="Email / links shown under your name")
    p.set_defaults(func=cmd_site)

    p = sub.add_parser("log", parents=[common], help="Track pitches: sent, replies, wins")
    p.add_argument("pitch", nargs="?", help="Pitch name (as shown by `proof log`)")
    p.add_argument("status", nargs="?", choices=STATUSES, help="What happened")
    p.add_argument("--note", default="", help="Anything worth remembering")
    p.set_defaults(func=cmd_log)

    args = parser.parse_args(argv)
    args.model = args.model or DEFAULT_MODELS[args.provider]
    calls_llm = (args.command in ("case", "pitch", "profile", "eval", "suggest", "apply",
                                  "followup", "prep")
                 and not getattr(args, "no_ai", False) and getattr(args, "draft", 1) != 0
                 and not getattr(args, "dry_run", False) and not getattr(args, "models", None))
    if calls_llm and not args.model:
        sys.exit("Pick a model with --model or PROOF_MODEL.")
    try:
        args.func(args)
    except BrokenPipeError:            # `proof scan repo | head`: the reader stopped early
        sys.stderr.close()
