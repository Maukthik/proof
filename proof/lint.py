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
from .stack import ALL_NAMES

NAMED_TECH = {name.lower() for name in ALL_NAMES} | {"Go", "Room", "Hilt"}

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


def claims(text):
    """The numbers in `text` worth checking, as (number, unit, regex match).
    Diagrams and [add: ...] placeholders are left out. So are single digits without
    % or x ("3 agents" is rarely made up, and checking them would bury real warnings)
    and offers like "a 15-minute call"."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"\[add:[^\]]*\]", "", text)
    found = []
    for match in CLAIMED_NUMBER.finditer(text):
        number, unit = match.group(0).split()[0].rstrip("%x×"), match.group(1)
        if (len(number) == 1 and not unit) or OFFER.match(text[match.end():]):
            continue
        found.append((number, unit, match))
    return text, found


def unsupported_numbers(text, sources):
    """Numbers in `text` that appear in none of the `sources` (a list of strings)."""
    known = {plain_number(n) for source in sources for n in ANY_NUMBER.findall(source)}
    unsupported = []
    for number, _, match in claims(text)[1]:
        if plain_number(number) not in known and match.group(0) not in unsupported:
            unsupported.append(match.group(0))
    return unsupported


# "not", "didn't", "failed" ... : words that turn a number's meaning around. ("without"
# isn't one: "10,214 tests without a false difference" says nothing against the 10,214.)
NEGATION = re.compile(r"\b(not|no|never|none|failed|fails|unable)\b|n't\b", re.IGNORECASE)


def words_around(text, start, end, count=4):
    """text[start:end] with up to `count` words each side, without crossing a clause
    boundary (, ; : . brackets). Kept this narrow so "all 44 tests pass, Doppel fails
    the check" doesn't count as a "fails" next to 44."""
    before = re.split(r"[,;:.!?()\[\]\n]", text[max(0, start - 80):start])[-1].split()
    after = re.split(r"[,;:.!?()\[\]\n]", text[end:end + 80])[0].split()
    return " ".join(before[-count:] + [text[start:end]] + after[:count])


def flipped_numbers(text, sources):
    """Numbers whose meaning may have been turned around. Everywhere the repo has the
    number it sits next to a "not" / "didn't" / "failed", but the text says it plainly.
    Real case: the README said "22 of 37 didn't run", the model wrote "caught 22 of 37".
    Returns [(number, what the repo says around it)]."""
    source = "\n".join(sources)
    text, found = claims(text)
    flips, seen = [], set()
    for number, _, match in found:
        if number in seen or NEGATION.search(words_around(text, match.start(), match.end())):
            continue
        seen.add(number)
        places = [words_around(source, m.start(), m.end()) for m in ANY_NUMBER.finditer(source)
                  if plain_number(m.group(0)) == plain_number(number)]
        if places and all(NEGATION.search(place) for place in places):
            flips.append((match.group(0), " ".join(places[0].split())))
    return flips


# ---------------------------------------------------------------------------
# Case studies
# ---------------------------------------------------------------------------

def check_case_study(text, sources=(), files=None, prose=None, prompt=None):
    """Problems with a case study, as messages a person (or the model) can act on.
    sources: the repo scan and facts. files: the repo's file paths. prose: what states
    results in words (README, facts). prompt: the instructions the model was given."""
    problems = format_problems(text)
    if sources:
        problems += claim_problems(text, sources)
    if files is not None:
        unknown = missing_files(text, files, sources)
        if unknown:
            problems.append(f"files that aren't in the repo: {', '.join(unknown)} - "
                            "name only real files from the scan")
    if prose is not None:
        numbers = unsupported_numbers(section(text, "Results"), prose)
        if numbers:
            problems.append(f"Results numbers the README and your facts don't state: "
                            f"{', '.join(numbers)} - remove them or use [add: ...]")
    if prompt:
        copied = copied_phrases(text, prompt, sources)
        if copied:
            problems.append("copied from the prompt's instructions instead of written about "
                            f"this project: \"{copied[0]}...\"")
    if vague_highlights(text):
        problems.append("Engineering highlights name no real file or function - they read "
                        "as generic. Name the files that do the hard parts.")
    filler = [phrase for phrase in FILLER if phrase in text.lower()]
    if filler:
        problems.append(f"filler phrases: {', '.join(filler)} - say something specific instead")
    return problems


def format_problems(text):
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
    return problems


def claim_problems(text, sources):
    """Numbers and technologies the repo doesn't back up."""
    problems = []
    numbers = unsupported_numbers(text, sources)
    if numbers:
        problems.append(f"numbers not found in the repo or your facts: {', '.join(numbers)}"
                        " - check them, the model may have made them up")
    by_place = {}                       # "22" and "37" from "22 of 37 didn't run": one warning
    for number, said in flipped_numbers(text, sources):
        by_place.setdefault(said, []).append(number)
    for said, numbers in by_place.items():
        problems.append(f"{', '.join(numbers)}: meaning may be turned around - "
                        f'the repo says "{said}"')
    # Only named technologies: practices ("CI/CD", "REST APIs") are shown, not written down
    tech = sorted(t for t in tech_in(text) - tech_in("\n".join(sources)) if t in NAMED_TECH)
    if tech:
        problems.append(f"technologies the repo never mentions: {', '.join(tech)}")
    return problems


# A path in the text: src/lib/dal.ts, app/(portal)/page.tsx, `cli.py`, src/app/portal/
PATH = re.compile(r"(?<![\w/:.])((?:[\w.\-\[\]()]+/)+[\w.\-\[\]()]*)"
                  r"|`([\w.\-]+\.[a-z]{1,6})`")


def missing_files(text, files, sources=()):
    """Paths the text names that match no file or folder in the repo. Partial paths count
    ("doppel/sandbox.py" is src/doppel/sandbox.py), and so do files the repo's own code
    mentions (a tool that reads tox.ini can talk about tox.ini). "CI/CD" and "AI/ML" have
    no file extension and no trailing slash, so they aren't paths."""
    files = ["/" + f for f in files]
    mentioned = "\n".join(sources)
    unknown = []
    for match in PATH.finditer(text):
        path = (match.group(1) or match.group(2)).strip("()").removeprefix("./")
        is_file = re.search(r"\.[a-z]{1,6}$", path) is not None
        if not (is_file or path.endswith("/")) or "://" in text[match.start():match.end() + 3]:
            continue
        if is_file:
            found = any(f.endswith("/" + path) for f in files)
        else:
            found = any("/" + path in f for f in files)
        if not found and path not in mentioned and path not in unknown:
            unknown.append(path)
    return unknown


def copied_phrases(text, prompt, sources=(), length=6):
    """Runs of `length` words the text shares with the prompt's own wording (and not with
    the repo): a small model pasting an example instead of writing about the project."""
    def runs(s):
        # Headings and [add: ...] placeholders are meant to be the same as the prompt's
        s = re.sub(r"^#.*$|\[add:[^\]]*\]", " ", s, flags=re.MULTILINE)
        words = re.findall(r"[a-z0-9]+", s.lower())
        return {" ".join(words[i:i + length]) for i in range(len(words) - length + 1)}
    shared = runs(text) & runs(prompt)
    shared -= runs("\n".join(sources))
    return sorted(shared)


# Phrases that make a case study sound like every other one
FILLER = ["daunting", "struggle", "seamless", "robust", "cutting-edge", "state-of-the-art",
          "in today's", "here is a mermaid", "here's a mermaid", "leverag", "game-chang"]
# A file name (app/main.py), `code`, or a function call: proof the text is about real code
CODE_REFERENCE = re.compile(r"`[^`]+`|\b[\w/.-]+\.(py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|sql|prisma"
                            r"|ipynb)\b|\b\w+\(\)")


def section(text, heading):
    """The body of '## <heading>' in a Markdown document ('' if it isn't there)."""
    match = re.search(rf"^## {heading}[^\n]*\n(.*?)(?=^## |\Z)", text,
                      flags=re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def vague_highlights(text):
    highlights = re.sub(r"\[add:[^\]]*\]", "", section(text, "Engineering highlights"))
    return bool(re.search(r"\w", highlights)) and not CODE_REFERENCE.search(highlights)


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
        for number, said in flipped_numbers(text, list(sources)):
            problems.append(("WARN", f'"{number}" may have the wrong meaning: your case study '
                                     f'says "{said}".'))

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
