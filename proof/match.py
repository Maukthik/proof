"""
match.py - which of your projects best fits a job post? (no LLM, fully explainable)

Score = 3 points per shared tech term (e.g. "fastapi", "spring boot", "rag")
      + 1 point per shared everyday tool ("docker", "github actions", "pytest")
      + 0.5 points per other shared meaningful word.
"""

import re

from .stack import ALL_NAMES, PACKAGES

# Tech words worth extra points. Multi-word terms are fine ("github actions").
EXTRA_TECH = {
    "aws", "gcp", "azure", "docker", "kubernetes", "k8s", "terraform", "ansible",
    "ci/cd", "github actions", "jenkins", "linux", "nginx", "rag", "llm",
    "agent", "chatbot", "embeddings", "vector database", "rest api",
    "graphql", "websocket", "microservices", "machine learning", "deep learning",
    "nlp", "computer vision", "fine-tuning", "prompt engineering", "arduino",
    "iot", "embedded", "postgres", "mysql", "sqlite", "supabase", "firebase",
    "webhook", "payments", "saas", "multi-tenant", "role-based access", "rbac", "oauth", "jwt",
    "vercel", "netlify", "heroku", "unit tests", "automated tests", "e2e", "lora", "qlora",
}
TECH_TERMS = {t.lower() for t in list(PACKAGES) + list(ALL_NAMES)} | EXTRA_TECH
# Also plain English words ("go", "click here", "a rich UI"). Still matched when written
# with a capital, the way stack lists and job posts name them: "Room", "Hilt", "Go".
CASE_SENSITIVE = {"Go", "Room", "Hilt", "Click", "Rich", "Echo", "Fiber", "Rocket", "Expo",
                  "Rayon", "Glamour"}
TECH_TERMS -= {"c", "next", "express", "three", "ai", "chi", "regex"}
TECH_TERMS -= {t.lower() for t in CASE_SENSITIVE}
TECH_TERMS |= {"golang", "next.js", "express.js"}
# Tools nearly every project has: weak evidence that this project fits this job
COMMON_TOOLS = {"docker", "github actions", "git", "pytest", "jest", "junit", "vitest", "linux",
                "ci/cd", "sql", "unit tests", "automated tests", "gradle", "maven"}

STOPWORDS = set("""a an the and or but if of to in on for with by from at as is are was were be
been this that these those it its you your we our they their i me my will would can could should
must have has had do does did not no yes so than then there here what which who whom how why when
where all any each more most some such only own same very just also into about over after before
looking need needs needed want wants someone project projects work working experience build built
using use used able strong good great skills skill years year plus please apply""".split())


def has_term(text, term):
    """True if `term` appears in `text` as a whole word/phrase ("github actions" also
    matches "github action", "agents" matches "agent")."""
    forms = {term, term[:-1]} if term.endswith("s") and len(term) > 4 else {term}
    return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}s?(?![a-z0-9])", text) for t in forms)


def words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9+#.\-]{3,}", text.lower())
            if w.strip(".-") not in STOPWORDS}


def score_project(job, project_text):
    """Return (score, shared_tech_terms) for one project against the job."""
    tech = sorted(tech_in(job) & tech_in(project_text))
    other = (words(job) & words(project_text)) - {t.lower() for t in tech}
    points = sum(1 if term in COMMON_TOOLS else 3 for term in tech)
    return points + 0.5 * len(other), tech


def rank_projects(job, projects):
    """projects: list of {"name", "text"}. Returns them sorted best first, with scores."""
    ranked = []
    for p in projects:
        score, tech = score_project(job, p["text"])
        ranked.append({**p, "score": score, "matched": tech})
    return sorted(ranked, key=lambda p: p["score"], reverse=True)


def tech_in(text):
    """All tech terms mentioned in a text (also used by the linter)."""
    lower = text.lower()
    found = {t for t in TECH_TERMS if has_term(lower, t)}
    return found | {t for t in CASE_SENSITIVE if re.search(rf"\b{t}\b", text)}
