"""
claims.py - link each number in a case study's Results to the line it comes from.

    - Caught 17/20 regressions in the benchmark ([source](https://github.com/you/app/blob/<commit>/README.md#L466))

A client who doubts a number clicks it and lands on that line of your README, pinned to
the commit proof read (so the link stays right after the README changes). Numbers from
your facts.md are marked "self-reported": there's no line in the repo to point to.
A number with no source gets no link - and lint.py has already warned about it.
"""

import re

from .lint import NEGATION, plain_number, section, words_around
from .match import words

ANY_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def add_source_links(case_study, readme, readme_path, facts, repo_url, commit):
    """Return the case study with a source added to each Results line that has a number.
    repo_url: "https://github.com/you/app", or None for a repo with no web address."""
    results = section(case_study, "Results")
    if not results.strip():
        return case_study
    linked = "\n".join(link_line(line, readme, readme_path, facts, repo_url, commit)
                       for line in results.split("\n"))
    return case_study.replace(results, linked, 1)


def link_line(line, readme, readme_path, facts, repo_url, commit):
    """Add up to two sources to one Results line: the README lines that best match it."""
    if "[source](" in line or "(self-reported)" in line or not ANY_NUMBER.search(line):
        return line
    numbers = numbers_in(line)
    if numbers & numbers_in(facts or ""):
        return f"{line.rstrip()} (self-reported)"
    sources = []
    for line_no in best_lines(line, numbers, readme):
        sources.append(source_link(readme_path, line_no, repo_url, commit))
    return f"{line.rstrip()} {' '.join(sources)}" if sources else line


def best_lines(claim, numbers, readme, most=2):
    """README line numbers that state this claim. A line must share two of its numbers,
    one long number (10,214), or one number and two words ("8 of 10 apps ... after fixing
    gaps" matches "Gaps were fixed: 1/10 before, 8/10 after"), and say them the same way:
    a line where the number sits next to "didn't" doesn't back up a claim where it doesn't."""
    claim_words = words(claim)
    candidates = []
    for line_no, text in enumerate(readme.split("\n"), start=1):
        if text.lstrip().startswith("<"):        # HTML (image alt text): not a statement
            continue
        shared = numbers & numbers_in(text)
        if not shared or negated_near(text, shared) != negated_near(claim, shared):
            continue
        shared_words = len(claim_words & words(text))
        distinctive = any(len(n) >= 4 for n in shared)     # 10,214 rarely appears by chance
        if len(shared) >= 2 or shared_words >= 2 or distinctive:
            candidates.append((2 * len(shared) + shared_words, line_no, shared))

    chosen, covered = [], set()
    for _, line_no, shared in sorted(candidates, key=lambda c: (-c[0], c[1])):
        new = shared - covered                   # numbers this line would back up
        if len(new) >= 2 or any(len(n) >= 2 for n in new):     # a lone "0" proves nothing
            chosen.append(line_no)
            covered |= shared
        if len(chosen) == most or covered >= numbers:
            break
    return sorted(chosen)


def negated_near(text, numbers):
    """True if "not", "didn't", "failed" ... sits within a few words of one of `numbers`."""
    for match in ANY_NUMBER.finditer(text):
        if plain_number(match.group(0)) in numbers and \
                NEGATION.search(words_around(text, match.start(), match.end())):
            return True
    return False


def numbers_in(text):
    """Numbers in a piece of text, written the same way ('1,200' = '1200'); numbers inside
    links (commit hashes, #L466) don't count."""
    text = re.sub(r"\]\([^)]*\)", "", text)
    return {plain_number(n) for n in ANY_NUMBER.findall(text)}


def source_link(path, line_no, repo_url, commit):
    if repo_url:
        return f"([source]({repo_url}/blob/{commit or 'HEAD'}/{path}#L{line_no}))"
    return f"({path} line {line_no})"
