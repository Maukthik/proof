"""
evaluate.py - `proof eval`: score models on writing case studies, so prompt changes and
fine-tuned models are judged by numbers, not by reading one output.

    proof eval ~/code/doppel ~/code/client-desk --provider ollama --models llama3.1:8b qwen3:4b

For every repo x model it writes a case study the way `proof case` does (draft, checks,
one repair) and counts what the checks in lint.py find. No AI judges the AI: the same
output always gets the same score. Everything is saved in proof_output/eval/<time>/:
every draft and final version, the prompts, and results.json. The table at the end is
compared with the previous eval, so you can see whether a change helped.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import casestudy
from .facts import read_facts
from .scan import get_repo, has_enough_to_write_about, list_files, repo_name, scan_repo

# What each problem message from lint.py is about (first matching phrase wins)
KINDS = [
    ("files that aren't in the repo", "invented files"),
    ("copied from the prompt", "copied prompt"),
    ("meaning may be turned around", "flipped number"),
    ("numbers not found", "unsupported number"),
    ("Results numbers", "unsupported number"),
    ("technologies the repo never mentions", "wrong tech"),
    ("missing sections", "format"),
    ("no Mermaid diagram", "format"),
    ("words - over the", "format"),
    ("Engineering highlights name no", "vague highlights"),
    ("filler phrases", "filler"),
]


def kind_of(problem):
    return next((kind for phrase, kind in KINDS if phrase in problem), "other")


def evaluate_one(repo, repo_scan, facts, provider, model):
    """Write one case study and score it. Returns a row for results.json."""
    started = time.time()
    result = casestudy.write(repo, repo_scan, facts, provider, model, say=lambda _: None)
    return {
        "repo": repo.name, "model": model,
        "first_problems": result["first_problems"], "problems": result["problems"],
        "repaired": result["repaired"],
        "gaps": len(re.findall(r"\[add:", result["case_study"])),
        "minutes": round((time.time() - started) / 60, 1),
        "draft": result["draft"], "case_study": result["case_study"],
    }


def run(repo_args, models, provider, out_dir, scan_budget, clone_dir):
    """Score every model on every repo. GitHub URLs are cloned into clone_dir."""
    eval_dir = Path(out_dir) / "eval" / datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = []
    for repo_arg in repo_args:
        repo = get_repo(repo_arg, clone_dir)
        if not has_enough_to_write_about(repo, list_files(repo)):
            print(f"[{repo.name}] skipped: nothing to write about")
            continue
        facts = read_facts(Path(out_dir) / repo_name(repo_arg))
        repo_scan = scan_repo(repo, budget=scan_budget)
        save(eval_dir / "prompts" / f"{repo.name}.txt", casestudy.build_prompt(repo_scan, facts))
        for model in models:
            print(f"[{repo.name}] {model} ...")
            row = evaluate_one(repo, repo_scan, facts, provider, model)
            folder = eval_dir / slug(model) / repo.name
            save(folder / "draft.md", row.pop("draft"))
            save(folder / "case_study.md", row.pop("case_study"))
            rows.append(row)
            print(f"[{repo.name}] {model}: {len(row['first_problems'])} problems -> "
                  f"{len(row['problems'])} after repair, {row['minutes']} min")

    previous = latest_results(Path(out_dir) / "eval", before=eval_dir.name)
    save(eval_dir / "results.json", json.dumps(rows, indent=2))
    print()
    print(table(rows))
    print()
    print(totals(rows, previous))
    print(f"\nEverything is in {eval_dir}")
    return rows


def table(rows):
    lines = [f"{'model':<28} {'repo':<22} {'draft':>5} {'final':>5} {'gaps':>4} {'min':>5}  "
             "what's left"]
    for row in rows:
        left = counts(row["problems"])
        lines.append(f"{row['model'][:28]:<28} {row['repo'][:22]:<22} "
                     f"{len(row['first_problems']):>5} {len(row['problems']):>5} "
                     f"{row['gaps']:>4} {row['minutes']:>5}  "
                     + (", ".join(f"{kind} x{n}" for kind, n in left.items()) or "clean"))
    return "\n".join(lines)


def totals(rows, previous=None):
    """One line per model: problems before/after repair, clean case studies, time - and
    the change since the previous eval of the same model (on the repos both runs share)."""
    lines = []
    for model in dict.fromkeys(row["model"] for row in rows):
        mine = [row for row in rows if row["model"] == model]
        final = sum(len(row["problems"]) for row in mine)
        line = (f"{model}: {sum(len(r['first_problems']) for r in mine)} problems in drafts, "
                f"{final} after repair, {sum(not r['problems'] for r in mine)}/{len(mine)} clean, "
                f"{sum(r['minutes'] for r in mine):.1f} min")
        before = [row for row in previous or [] if row["model"] == model
                  and row["repo"] in {r["repo"] for r in mine}]
        if before:
            then = sum(len(row["problems"]) for row in before)
            change = "better" if final < then else "worse" if final > then else "same"
            line += f"   (last eval: {then} after repair - {change})"
        lines.append(line)
    return "\n".join(lines)


def counts(problems):
    found = {}
    for problem in problems:
        found[kind_of(problem)] = found.get(kind_of(problem), 0) + 1
    return found


def latest_results(eval_root, before):
    """Rows of the most recent earlier eval, or None."""
    earlier = sorted(p for p in eval_root.glob("*/results.json") if p.parent.name < before)
    return json.loads(earlier[-1].read_text(encoding="utf-8")) if earlier else None


def slug(model):
    """'llama3.1:8b-instruct' -> 'llama3.1-8b-instruct' (a safe folder name)."""
    return re.sub(r"[^\w.-]+", "-", model)


def save(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
