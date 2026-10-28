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

from .facts import fingerprint, read_facts, start_facts_file
from .jobpost import read_job
from .lint import check_case_study, lint_pitch, print_problems, unsupported_numbers
from .llm import (DEFAULT_MODELS, ask_llm, drop_preamble, fix_mermaid, scan_budget,
                  strip_wrapper)
from .match import rank_projects
from .portfolio import build_site, load_case_studies
from .prompts import CASE_STUDY, PITCH, PROFILE
from .scan import (detect_stack, get_repo, has_enough_to_write_about, head_commit, is_url,
                   list_files, remote_head, repo_name, scan_repo)
from .tracker import STATUSES, load_log, record_pitch, report, update_status


# ---------------------------------------------------------------------------
# case
# ---------------------------------------------------------------------------

def cmd_case(args):
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
    repo_scan = scan_repo(repo, budget=scan_budget(args.provider))
    prompt = CASE_STUDY.format(repo_scan=repo_scan, facts=facts or "(none given)")
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"[{name}] dry run - prompt saved to {out_dir / 'prompt.txt'}")
        return

    print(f"[{name}] writing case study with {args.provider}/{args.model} ...")
    reply = ask_llm(prompt, args.provider, args.model)
    case_study = fix_mermaid(drop_preamble(strip_wrapper(reply)))

    # Never overwrite a case study you edited: put the new one next to it instead
    edited = was_edited(out_dir / "case_study.md", meta)
    target = out_dir / ("case_study.new.md" if edited else "case_study.md")
    target.write_text(case_study + "\n", encoding="utf-8")

    meta = {
        "name": name, "source": repo_arg, "commit": head_commit(repo),
        "stack": detect_stack(repo, list_files(repo)),
        "provider": args.provider, "model": args.model,
        "generated": date.today().isoformat(),
        "facts": fingerprint(facts),                   # to notice when you add facts
        "written": fingerprint(case_study + "\n"),     # to notice when you edit it
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    report_case_study(name, target, case_study, edited, sources=[repo_scan, facts])
    if start_facts_file(out_dir, name, case_study):
        print(f"[{name}] started {out_dir / 'facts.md'} - fill in the real numbers there, "
              f"then run this again to close the gaps")


def report_case_study(name, target, case_study, edited, sources):
    gaps = len(re.findall(r"\[add:", case_study))
    print(f"[{name}] saved {target}" + (f"  ({gaps} [add: ...] gaps to fill)" if gaps else ""))
    if edited:
        print(f"[{name}]   you edited case_study.md, so it was left alone. Copy what you "
              f"want from {target.name}, or delete case_study.md and use the new one.")
    for problem in check_case_study(case_study, sources):
        print(f"[{name}]   WARN  {problem}")


def was_edited(case_file, meta):
    """True if case_study.md isn't exactly what proof last wrote there (you changed it)."""
    if not case_file.exists():
        return False
    return fingerprint(case_file.read_text(encoding="utf-8")) != meta.get("written")


def load_meta(out_dir):
    meta_file = out_dir / "meta.json"
    return json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}


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


def cmd_pitch(args):
    job, job_name = read_job(args.job)
    projects = require_case_studies(args.out)

    # Match against the case study, your facts and the detected stack
    searchable = [{**p, "text": "\n".join([p["text"], p["facts"], " ".join(p["stack"])]),
                   "case_study": p["text"]} for p in projects]
    ranked = rank_projects(job, searchable)

    print("Project match for this job:")
    for p in ranked:
        print(f"  {p['score']:5.1f}  {p['name']:<28} {', '.join(p['matched']) or '-'}")
    # Evidence = projects that share real tech with the job and score at least half as
    # well as the best one (Docker alone doesn't make a project relevant).
    # If none share any tech, use the best one anyway.
    best = ranked[0]["score"]
    chosen = [p for p in ranked if p["matched"] and p["score"] >= best / 2][:args.top]
    if not chosen:
        print("  (no shared tech - this job may not suit your current projects)")
        chosen = ranked[:1]
    chosen = [{**p, "text": p["case_study"]} for p in chosen]

    print(f"Writing pitch using: {', '.join(p['name'] for p in chosen)} ...")
    case_studies = "\n\n".join(project_block(p) for p in chosen)
    pitch = strip_wrapper(ask_llm(PITCH.format(job=job, case_studies=case_studies),
                                  args.provider, args.model))

    pitch_file = Path(args.out) / "pitches" / f"{job_name}.md"
    pitch_file.parent.mkdir(parents=True, exist_ok=True)
    pitch_file.write_text(pitch + "\n", encoding="utf-8")
    matched = sorted({term for p in chosen for term in p["matched"]})
    record_pitch(args.out, job_name, args.job if args.job != "-" else "pasted",
                 [p["name"] for p in chosen], matched)

    print(f"Saved {pitch_file}\n")
    print(pitch, "\n")
    print_problems(lint_pitch(pitch, job, sources=[project_block(p) for p in chosen]))
    print(f"\nWhen you send it:  proof log {job_name} sent")


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
    p.add_argument("repos", nargs="+", help="Local folders or GitHub URLs")
    p.add_argument("--force", action="store_true", help="Redo even if unchanged")
    p.add_argument("--dry-run", action="store_true", help="Save prompts, don't call the LLM")
    p.set_defaults(func=cmd_case)

    p = sub.add_parser("pitch", parents=[common], help="Write a pitch for a job post")
    p.add_argument("job", help="Job post: a text file, a URL, or - to paste it")
    p.add_argument("--top", type=int, default=2, help="How many projects to use")
    p.set_defaults(func=cmd_pitch)

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
    calls_llm = args.command in ("case", "pitch", "profile") and not getattr(args, "dry_run", False)
    if calls_llm and not args.model:
        sys.exit("Pick a model with --model or PROOF_MODEL.")
    args.func(args)
