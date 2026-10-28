"""
lint.py - check generated text before anyone sees it. Plain rules, no LLM.

  lint_pitch(pitch, job, sources)  -> problems with a pitch
  check_case_study(text, sources)  -> problems with a case study
  unsupported_numbers(text, sources) -> numbers that appear in none of the sources

Each problem is (level, message):
  ERROR -> fix before sending
  WARN  -> probably hurts your chances
  INFO  -> worth a look
"""

import re

from .match import tech_in

BUZZWORDS = [
    "passionate", "synergy", "cutting-edge", "cutting edge", "revolutionary",
    "world-class", "rockstar", "ninja", "guru", "leverage", "dynamic",
    "results-driven", "go-getter", "think outside the box", "game-changer",
    "game changer", "seamless", "robust solution",
]
WEAK_OPENINGS = ("hi", "hello", "dear", "i am", "i'm", "my name", "greetings", "hope")
NEXT_STEP_WORDS = ("call", "demo", "chat", "meet", "?", "schedule", "walk you through")
MAX_WORDS = 180

SECTIONS = ["The problem", "What I built", "How it works", "Tech stack",
            "Engineering highlights", "Results", "Skills shown"]
MAX_CASE_STUDY_WORDS = 600


# ---------------------------------------------------------------------------
# Claims: every number should come from somewhere
# ---------------------------------------------------------------------------

# A number in the text being checked: "40%", "1,200", "2.5", "17/20" (two numbers).
# Not one glued to a word, like the 5 in "gpt5" or the 3 in "S3".
CLAIMED_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:\s*(%|x\b|×))?")
# Numbers in the sources: anywhere at all, so "qwen2.5" backs up a claim of "2.5".
ANY_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Offers, not claims: "a 15-minute call", "within 24 hours"
OFFER = re.compile(r"^[\s-]*(minute|min|hour|hr)", re.IGNORECASE)


def plain_number(number):
    """'1,200' and '1200' are the same number; so are '2.50' and '2.5'."""
    number = number.replace(",", "")
    return number.rstrip("0").rstrip(".") if "." in number else number


def unsupported_numbers(text, sources):
    """Numbers in `text` that appear in none of the `sources` (a list of strings).
    Single digits without % or x are skipped: "3 agents" is rarely a made-up claim,
    and checking them would bury the real warnings."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)      # diagrams
    text = re.sub(r"\[add:[^\]]*\]", "", text)                  # placeholders
    known = {plain_number(n) for source in sources for n in ANY_NUMBER.findall(source)}
    unsupported = []
    for match in CLAIMED_NUMBER.finditer(text):
        number, unit = match.group(0).split()[0].rstrip("%x×"), match.group(1)
        if len(number) == 1 and not unit:
            continue
        if OFFER.match(text[match.end():]):
            continue
        if plain_number(number) not in known and match.group(0) not in unsupported:
            unsupported.append(match.group(0))
    return unsupported


# ---------------------------------------------------------------------------
# Case studies
# ---------------------------------------------------------------------------

def check_case_study(text, sources=()):
    """Did the model follow the format, and can its numbers be traced? -> list of messages."""
    problems = []
    words = len(re.sub(r"```mermaid.*?```", "", text, flags=re.DOTALL).split())
    if words > MAX_CASE_STUDY_WORDS:
        problems.append(f"{words} words - over the {MAX_CASE_STUDY_WORDS} limit, "
                        "trim it before publishing")
    missing = [s for s in SECTIONS if not re.search(rf"^## {s}", text, flags=re.MULTILINE)]
    if missing:
        problems.append(f"missing sections: {', '.join(missing)}")
    if "```mermaid" not in text:
        problems.append("no Mermaid diagram")
    if sources:
        numbers = unsupported_numbers(text, sources)
        if numbers:
            problems.append(f"numbers not found in the repo or your facts: {', '.join(numbers)}"
                            " - check them, the model may have made them up")
    return problems


# ---------------------------------------------------------------------------
# Pitches
# ---------------------------------------------------------------------------

def lint_pitch(pitch, job="", sources=None):
    """`sources`: case studies and facts the pitch was written from. When given,
    numbers in the pitch that aren't in them (or the job post) are flagged."""
    problems = []
    text = pitch.strip()
    lower = text.lower()

    if re.search(r"\[add:", lower):
        problems.append(("ERROR", "Unfilled [add: ...] placeholder - replace it with a real detail."))

    if re.search(r"\[(your name|client name|name|company)\]", lower):
        problems.append(("ERROR", "Template placeholder like [Your Name] left in."))

    if sources is not None:
        numbers = unsupported_numbers(text, list(sources) + [job])
        if numbers:
            problems.append(("WARN", f"Numbers not in your case studies or the job post: "
                                     f"{', '.join(numbers)}. Make sure they're true."))

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


def print_problems(problems, ok_message="Lint: looks good."):
    if not problems:
        print(ok_message)
        return
    for level, message in problems:
        print(f"  {level:5}  {message}")
