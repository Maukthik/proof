"""
lint.py - check a pitch before you send it. Plain rules, no LLM.

Each problem is (level, message):
  ERROR -> fix before sending
  WARN  -> probably hurts your chances
  INFO  -> worth a look
"""

import re

from match import tech_in

BUZZWORDS = [
    "passionate", "synergy", "cutting-edge", "cutting edge", "revolutionary",
    "world-class", "rockstar", "ninja", "guru", "leverage", "dynamic",
    "results-driven", "go-getter", "think outside the box", "game-changer",
    "game changer", "seamless", "robust solution",
]
WEAK_OPENINGS = ("hi", "hello", "dear", "i am", "i'm", "my name", "greetings", "hope")
NEXT_STEP_WORDS = ("call", "demo", "chat", "meet", "?", "schedule", "walk you through")
MAX_WORDS = 180


def lint_pitch(pitch, job=""):
    problems = []
    text = pitch.strip()
    lower = text.lower()

    if re.search(r"\[add:", lower):
        problems.append(("ERROR", "Unfilled [add: ...] placeholder - replace it with a real detail."))

    if re.search(r"\[(your name|client name|name|company)\]", lower):
        problems.append(("ERROR", "Template placeholder like [Your Name] left in."))

    count = len(text.split())
    if count > MAX_WORDS:
        problems.append(("WARN", f"{count} words - clients skim; aim for under {MAX_WORDS}."))

    if lower.startswith(WEAK_OPENINGS):
        problems.append(("WARN", "Opens with a greeting/intro. Open with the client's problem instead."))

    found = [b for b in BUZZWORDS if b in lower]
    if found:
        problems.append(("WARN", f"Buzzwords: {', '.join(found)}. Replace with specifics."))

    last_part = lower[-200:]
    if not any(w in last_part for w in NEXT_STEP_WORDS):
        problems.append(("WARN", "No clear next step at the end (a question, call or demo)."))

    if job:
        missing = sorted(tech_in(job) - tech_in(text))
        if missing:
            problems.append(("INFO", f"Job mentions {', '.join(missing)} but your pitch doesn't. "
                                     "Address them if you can, or say how you'd handle them."))

    return problems


def print_problems(problems):
    if not problems:
        print("Lint: looks good.")
        return
    for level, message in problems:
        print(f"  {level:5}  {message}")
