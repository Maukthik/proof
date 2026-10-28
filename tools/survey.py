"""
survey.py - what would the model see? A quick check of the scan across many repos.

    python tools/survey.py ~/code/doppel ~/code/client-desk ~/code/*

For each repo: detected stack, git history, prompt size (cloud model and Ollama),
size of the import map, and the first files the model gets to read. Run it after any
change to scan.py, stack.py or codemap.py, on repos of different languages and sizes:
most bugs so far showed up here, not in the unit tests.
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proof.llm import scan_budget                                       # noqa: E402
from proof.prompts import CASE_STUDY                                    # noqa: E402
from proof.scan import has_enough_to_write_about, list_files, scan_repo  # noqa: E402


def files_read(scan):
    return re.findall(r"^# File: (.+)$", scan, flags=re.MULTILINE)


def survey(repo):
    started = time.time()
    files = list_files(repo)
    if not has_enough_to_write_about(repo, files):
        print(f"=== {repo.name}: {len(files)} files - skipped by `proof case` (nothing to write about)")
        return
    cloud = scan_repo(repo)
    small = scan_repo(repo, budget=scan_budget("ollama"))
    imports = re.search(r"# How the files connect.*?\n(.*?)(?:\n\n# |\Z)", cloud, flags=re.DOTALL)

    print(f"=== {repo.name}: {len(files)} files, scanned in {time.time() - started:.1f}s")
    print("  stack: ", re.search(r"# Detected stack: (.+)", cloud).group(1))
    print("  git:   ", re.search(r"# Git history: (.+)", cloud).group(1))
    print(f"  prompt: {len(CASE_STUDY.format(repo_scan=cloud, facts=''))} chars (cloud), "
          f"{len(CASE_STUDY.format(repo_scan=small, facts=''))} chars (Ollama)")
    print("  import map lines:", len(imports.group(1).splitlines()) if imports else 0)
    print(f"  Ollama reads {len(files_read(small))} files:", ", ".join(files_read(small)[:12]))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        if Path(arg).is_dir():
            survey(Path(arg).resolve())
