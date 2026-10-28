"""
match.py - which of your projects best fits a job post? (no LLM, fully explainable)

Score = 3 points per shared tech term (e.g. "fastapi", "docker", "rag")
      + 0.5 points per other shared meaningful word.
"""

import re

from .scan import LANGUAGES, PACKAGES

# Tech words worth extra points. Multi-word terms are fine ("github actions").
EXTRA_TECH = {
    "aws", "gcp", "azure", "docker", "kubernetes", "k8s", "terraform", "ansible",
    "ci/cd", "github actions", "jenkins", "linux", "nginx", "rag", "llm", "llms",
    "agent", "agents", "chatbot", "embeddings", "vector database", "rest api",
    "graphql", "websocket", "microservices", "machine learning", "deep learning",
    "nlp", "computer vision", "fine-tuning", "prompt engineering", "arduino",
    "iot", "embedded", "postgres", "mysql", "sqlite", "supabase", "firebase",
    "webhook", "payments", "saas", "multi-tenant", "role-based access", "rbac", "oauth", "jwt",
    "vercel", "netlify", "heroku", "unit tests", "automated tests", "e2e", "lora", "qlora",
}
TECH_TERMS = {t.lower() for t in list(PACKAGES) + list(PACKAGES.values())
              + list(LANGUAGES.values())} | EXTRA_TECH
TECH_TERMS -= {"c", "next", "express", "go", "three", "ai"}   # also plain English words
TECH_TERMS |= {"golang", "next.js", "express.js"}

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
    job_l, proj_l = job.lower(), project_text.lower()
    tech = sorted(t for t in TECH_TERMS if has_term(job_l, t) and has_term(proj_l, t))
    other = (words(job_l) & words(proj_l)) - set(tech)
    return 3 * len(tech) + 0.5 * len(other), tech


def rank_projects(job, projects):
    """projects: list of {"name", "text"}. Returns them sorted best first, with scores."""
    ranked = []
    for p in projects:
        score, tech = score_project(job, p["text"])
        ranked.append({**p, "score": score, "matched": tech})
    return sorted(ranked, key=lambda p: p["score"], reverse=True)


def tech_in(text):
    """All tech terms mentioned in a text (used by the linter)."""
    text = text.lower()
    return {t for t in TECH_TERMS if has_term(text, t)}
