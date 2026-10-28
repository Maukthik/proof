"""
proof.py - turn your repos into proof of skill.

Commands:
  case   REPO [REPO ...]   write a case study for each repo (skips unchanged ones)
  pitch  JOB_FILE          pick your best-matching projects and write a pitch
  lint   PITCH_FILE        check a pitch for common mistakes
  site                     build a portfolio page from all case studies

Examples:
  python proof.py case https://github.com/you/doppel ./rag-chatbot --provider ollama
  python proof.py pitch upwork_job.txt
  python proof.py site --owner "Maukthik J" --contact "you@email.com"

Try the whole flow with no LLM:  add --provider mock
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from lint import lint_pitch, print_problems
from llm import DEFAULT_MODELS, ask_llm, strip_wrapper
from match import rank_projects
from prompts import CASE_STUDY, PITCH
from scan import detect_stack, get_repo, head_commit, list_files, scan_repo
from portfolio import build_site, load_case_studies


# ---------------------------------------------------------------------------
# case
# ---------------------------------------------------------------------------

def cmd_case(args):
    for repo_arg in args.repos:
        repo = get_repo(repo_arg)
        out_dir = Path(args.out) / repo.name
        meta_file = out_dir / "meta.json"
        commit = head_commit(repo)

        # Skip if nothing changed since last time (a dry run always runs)
        cached = meta_file.exists() and (out_dir / "case_study.md").exists()
        if commit and cached and not args.force and not args.dry_run:
            if json.loads(meta_file.read_text()).get("commit") == commit:
                print(f"[{repo.name}] up to date - skipping (use --force to redo)")
                continue

        print(f"[{repo.name}] scanning ...")
        repo_scan = scan_repo(repo)
        prompt = CASE_STUDY.format(repo_scan=repo_scan)
        out_dir.mkdir(parents=True, exist_ok=True)

        if args.dry_run:
            (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            print(f"[{repo.name}] dry run - prompt saved to {out_dir / 'prompt.txt'}")
            continue

        print(f"[{repo.name}] writing case study with {args.provider}/{args.model} ...")
        case_study = strip_wrapper(ask_llm(prompt, args.provider, args.model))
        (out_dir / "case_study.md").write_text(case_study + "\n", encoding="utf-8")

        meta = {
            "name": repo.name, "source": repo_arg, "commit": commit,
            "stack": detect_stack(repo, list_files(repo)),
            "provider": args.provider, "model": args.model,
            "generated": date.today().isoformat(),
        }
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        gaps = len(re.findall(r"\[add:", case_study))
        print(f"[{repo.name}] saved {out_dir / 'case_study.md'}"
              + (f"  ({gaps} [add: ...] gaps to fill)" if gaps else ""))
        for problem in check_case_study(case_study):
            print(f"[{repo.name}]   WARN  {problem}")


SECTIONS = ["The problem", "What I built", "How it works", "Tech stack",
            "Engineering highlights", "Results", "Skills shown"]


def check_case_study(text):
    """Did the model follow the format? Returns a list of problems."""
    problems = []
    words = len(re.sub(r"```mermaid.*?```", "", text, flags=re.DOTALL).split())
    if words > 600:
        problems.append(f"{words} words - over the 600 limit, trim it before publishing")
    missing = [s for s in SECTIONS if not re.search(rf"^## {s}", text, flags=re.MULTILINE)]
    if missing:
        problems.append(f"missing sections: {', '.join(missing)}")
    if "```mermaid" not in text:
        problems.append("no Mermaid diagram")
    return problems


# ---------------------------------------------------------------------------
# pitch
# ---------------------------------------------------------------------------

def cmd_pitch(args):
    job = Path(args.job).read_text(encoding="utf-8")
    projects = load_case_studies(args.out)
    if not projects:
        sys.exit(f"No case studies in {args.out}. Run `python proof.py case <repo>` first.")

    for p in projects:   # include detected stack in what we match against
        p["text"] = p["text"] + "\n" + " ".join(p["stack"])
    ranked = rank_projects(job, projects)

    print("Project match for this job:")
    for p in ranked:
        print(f"  {p['score']:5.1f}  {p['name']:<28} {', '.join(p['matched']) or '-'}")

    chosen = [p for p in ranked if p["score"] > 0][:args.top] or ranked[:1]
    if ranked[0]["score"] == 0:
        print("  (no real overlap - this job may not suit your current projects)")

    case_studies = "\n\n".join(f"--- PROJECT: {p['name']} ---\n{p['text']}" for p in chosen)
    print(f"Writing pitch using: {', '.join(p['name'] for p in chosen)} ...")
    pitch = strip_wrapper(ask_llm(PITCH.format(job=job, case_studies=case_studies),
                                  args.provider, args.model))

    pitch_dir = Path(args.out) / "pitches"
    pitch_dir.mkdir(parents=True, exist_ok=True)
    pitch_file = pitch_dir / f"{Path(args.job).stem}.md"
    pitch_file.write_text(pitch + "\n", encoding="utf-8")
    print(f"Saved {pitch_file}\n")
    print(pitch, "\n")
    print_problems(lint_pitch(pitch, job))


# ---------------------------------------------------------------------------
# lint / site
# ---------------------------------------------------------------------------

def cmd_lint(args):
    pitch = Path(args.pitch).read_text(encoding="utf-8")
    job = Path(args.job).read_text(encoding="utf-8") if args.job else ""
    problems = lint_pitch(pitch, job)
    print_problems(problems)
    sys.exit(1 if any(level == "ERROR" for level, _ in problems) else 0)


def cmd_site(args):
    page, projects = build_site(args.out, owner=args.owner, contact=args.contact)
    print(f"Portfolio with {len(projects)} projects: {page}")
    for p in projects:
        if p["placeholders"]:
            print(f"  WARN  {p['name']}: {p['placeholders']} [add: ...] gaps still showing "
                  f"(highlighted yellow). Fill them before publishing.")


# ---------------------------------------------------------------------------
# Command-line setup
# ---------------------------------------------------------------------------

def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="proof_output", help="Output folder")
    common.add_argument("--provider", default=os.environ.get("PROOF_PROVIDER", "anthropic"),
                        choices=["anthropic", "ollama", "openai", "mock"])
    common.add_argument("--model", default=os.environ.get("PROOF_MODEL"))

    parser = argparse.ArgumentParser(description="Turn your repos into proof of skill.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("case", parents=[common], help="Write case studies for repos")
    p.add_argument("repos", nargs="+", help="Local folders or GitHub URLs")
    p.add_argument("--force", action="store_true", help="Redo even if unchanged")
    p.add_argument("--dry-run", action="store_true", help="Save prompts, don't call the LLM")
    p.set_defaults(func=cmd_case)

    p = sub.add_parser("pitch", parents=[common], help="Write a pitch for a job post")
    p.add_argument("job", help="Text file with the job post / application question")
    p.add_argument("--top", type=int, default=2, help="How many projects to use")
    p.set_defaults(func=cmd_pitch)

    p = sub.add_parser("lint", parents=[common], help="Check a pitch")
    p.add_argument("pitch", help="Pitch text file")
    p.add_argument("--job", help="Job post, to check for missing tech")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("site", parents=[common], help="Build portfolio page")
    p.add_argument("--owner", default="My projects", help="Your name for the page title")
    p.add_argument("--contact", default="", help="Email / links shown under your name")
    p.set_defaults(func=cmd_site)

    args = parser.parse_args(argv)
    args.model = args.model or DEFAULT_MODELS[args.provider]
    if args.command in ("case", "pitch") and not args.model and not getattr(args, "dry_run", False):
        sys.exit("Pick a model with --model or PROOF_MODEL.")
    args.func(args)


if __name__ == "__main__":
    main()
