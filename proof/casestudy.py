"""
casestudy.py - write one case study: draft, check, repair, link claims to their sources.

Used by `proof case` (writes it to proof_output/) and `proof eval` (scores it).
"""

from .claims import add_source_links
from .lint import check_case_study
from .llm import ask_llm, drop_preamble, fix_mermaid, strip_wrapper
from .prompts import CASE_STUDY, REVISE
from .scan import git_stats, list_files, readme_text


def build_prompt(repo_scan, facts):
    return CASE_STUDY.format(repo_scan=repo_scan, facts=facts or "(none given)")


def review_context(repo, repo_scan, facts):
    """What the checks compare a case study against."""
    files = [f.as_posix() for f in list_files(repo)]
    return {
        "sources": [repo_scan, facts],                     # everything the model saw
        "files": files,
        "prose": [readme_text(repo, files), facts, git_stats(repo)],   # where results are stated
        "prompt": CASE_STUDY.split("=== END OF FACTS ===")[1],         # the instructions alone
    }


def review(case_study, context):
    return check_case_study(case_study, context["sources"], files=context["files"],
                            prose=context["prose"], prompt=context["prompt"])


def draft(prompt, provider, model):
    """Ask the model, and tidy what comes back."""
    return fix_mermaid(drop_preamble(strip_wrapper(ask_llm(prompt, provider, model))))


def write(repo, repo_scan, facts, provider, model, say=print):
    """Draft a case study, check it, and if the checks find problems ask the model once to
    fix them, keeping whichever version has fewer. Small models fix a listed problem far
    better than they avoid it in the first place.

    Returns {"case_study", "draft", "first_problems", "problems", "repaired"}."""
    context = review_context(repo, repo_scan, facts)
    first = draft(build_prompt(repo_scan, facts), provider, model)
    first_problems = review(first, context)
    result = {"case_study": first, "draft": first, "first_problems": first_problems,
              "problems": first_problems, "repaired": False}
    if not first_problems:
        return result

    say(f"checks found {len(first_problems)} problem(s) - asking the model to fix them ...")
    revised = draft(REVISE.format(repo_scan=repo_scan, facts=facts or "(none given)",
                                  case_study=first, problems=bullets(first_problems)),
                    provider, model)
    revised_problems = review(revised, context)
    if len(revised_problems) < len(first_problems):
        result.update(case_study=revised, problems=revised_problems, repaired=True)
    return result


def link_sources(case_study, repo, facts, repo_url, commit):
    """Results numbers -> links to the README line they come from (see claims.py)."""
    files = [f.as_posix() for f in list_files(repo)]
    readmes = sorted((f for f in files if f.split("/")[-1].lower().startswith("readme")),
                     key=lambda f: f.count("/"))
    readme_path = readmes[0] if readmes else None
    return add_source_links(case_study, readme_text(repo, files), readme_path, facts,
                            repo_url, commit)


def bullets(lines):
    return "\n".join(f"- {line}" for line in lines)
