"""
dataset.py - `proof dataset`: turn good case studies into fine-tuning data.

Every example is the exact prompt proof sent (prompt.txt) and a case study we trust, as
one line of JSONL in the chat format training tools expect:

    {"messages": [{"role": "user", "content": <prompt>},
                  {"role": "assistant", "content": <case study>}], "source": ..., "repo": ...}

Trusted, best first:
  1. case studies you edited by hand (a person fixed them: the best labels there are)
  2. case studies that passed every check (meta.json "problems" is empty)
  3. clean outputs from `proof eval` runs
Repos named in --exclude are left out, so you can keep your own repos for an honest eval.
See training/README.md for the whole loop: teacher data -> dataset -> train -> eval.
"""

import hashlib
import json
import re
from pathlib import Path

from .evaluate import slug
from .facts import fingerprint

MIN_EXAMPLES = 50     # below this, fine-tuning mostly teaches the model a few repos by heart


def collect(folders, exclude=()):
    """All trusted examples in proof output folders, best source first, no duplicates."""
    examples = []
    for folder in folders:
        examples += from_case_studies(Path(folder))
        examples += from_evals(Path(folder) / "eval")
    best, seen = [], set()
    for example in sorted(examples, key=lambda e: e["rank"]):
        key = hashlib.sha256(example["prompt"].encode()).hexdigest()
        if example["repo"] in exclude or key in seen:
            continue
        seen.add(key)
        best.append(example)
    return best


def from_case_studies(out_dir):
    examples = []
    for prompt_file in sorted(out_dir.glob("*/prompt.txt")):
        folder = prompt_file.parent
        case_file, meta_file = folder / "case_study.md", folder / "meta.json"
        if not case_file.exists() or not meta_file.exists():
            continue                                   # a dry run: no answer to learn from
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        text = case_file.read_text(encoding="utf-8")
        if fingerprint(text) != meta.get("written"):
            source, rank = "edited by you", 1
        elif meta.get("problems") == []:
            source, rank = f"passed all checks ({meta.get('model')})", 2
        else:
            continue                                   # has problems, or from an older proof
        examples.append(example(prompt_file, text, folder.name, source, rank))
    return examples


def from_evals(eval_root):
    examples = []
    for results_file in sorted(eval_root.glob("*/results.json")):
        run_dir = results_file.parent
        for row in json.loads(results_file.read_text(encoding="utf-8")):
            case_file = run_dir / slug(row["model"]) / row["repo"] / "case_study.md"
            prompt_file = run_dir / "prompts" / f"{row['repo']}.txt"
            if not row["problems"] and case_file.exists() and prompt_file.exists():
                text = case_file.read_text(encoding="utf-8")
                examples.append(example(prompt_file, text, row["repo"],
                                        f"clean in eval ({row['model']})", 3))
    return examples


def example(prompt_file, case_study, repo, source, rank):
    return {"prompt": prompt_file.read_text(encoding="utf-8"), "answer": without_links(case_study),
            "repo": repo, "source": source, "rank": rank}


def without_links(case_study):
    """Source links are added by proof after writing, so the model shouldn't learn them."""
    text = re.sub(r" \(\[source\]\([^)]*\)\)| \([\w./-]+ line \d+\)| \(self-reported\)", "",
                  case_study)
    return text.strip() + "\n"


def write(examples, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for e in examples:
            messages = [{"role": "user", "content": e["prompt"]},
                        {"role": "assistant", "content": e["answer"]}]
            out.write(json.dumps({"messages": messages, "source": e["source"],
                                  "repo": e["repo"]}) + "\n")


def summary(examples, path):
    if not examples:
        return ("No trusted case studies found. Make some first - see training/README.md "
                "(a big model writing case studies for public repos).")
    by_source = {}
    for e in examples:
        kind = e["source"].split(" (")[0]
        by_source[kind] = by_source.get(kind, 0) + 1
    longest = max(len(e["prompt"]) + len(e["answer"]) for e in examples)
    lines = [f"Wrote {len(examples)} examples to {path}",
             "  " + ", ".join(f"{n} {kind}" for kind, n in by_source.items()),
             f"  longest example: ~{longest // 3:,} tokens "
             "(MAX_TOKENS in training/train_lora.py must be above this)"]
    if len(examples) < MIN_EXAMPLES:
        lines.append(f"  WARN  only {len(examples)} examples; aim for {MIN_EXAMPLES}+ or the model "
                     "will learn these repos by heart instead of the task")
    return "\n".join(lines)

