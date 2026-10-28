"""
casestudy.py - write one case study: draft, check, repair, then link claims and diagram.

Used by `proof case` (writes it to proof_output/) and `proof eval` (scores it).
After the checks, finish() adds source links to results and checks the diagram.
"""

from .claims import add_source_links
from .codemap import internal_imports
from .diagram import check_and_link
from .lint import check_case_study
from .llm import ask_llm, drop_preamble, fix_mermaid, strip_wrapper
from .prompts import CASE_STUDY, REVISE
from .scan import git_stats, is_side_folder, list_files, read_text, readme_text


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


def finish(case_study, repo, facts, repo_url, commit):
    """After the checks: link Results lines to their README source (claims.py), and check
    the diagram's arrows against the imports and link its boxes to the files (diagram.py).
    Returns (case study, number of arrows drawn dashed because no import backs them)."""
    files = list_files(repo)
    names = [f.as_posix() for f in files]
    readmes = sorted((f for f in names if f.split("/")[-1].lower().startswith("readme")),
                     key=lambda f: f.count("/"))
    readme_path = readmes[0] if readmes else None
    case_study = add_source_links(case_study, readme_text(repo, names), readme_path, facts,
                                  repo_url, commit)
    main_files = [f for f in files if not is_side_folder(f)]
    edges = internal_imports(repo, main_files, read_text)
    return check_and_link(case_study, names, edges, repo_url, commit)


def bullets(lines):
    return "\n".join(f"- {line}" for line in lines)
