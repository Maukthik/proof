"""prompts.py - the instructions we give the LLM. Edit these to change the writing style."""

CASE_STUDY = """You are helping a developer turn their project into proof of skill
for freelance clients and employers. Below is a scan of their repository.

Write a case study in Markdown with exactly these sections:

# <Project name> - <one-line description of what it does>
## The problem
(Who has this problem and why it matters. 2-4 sentences.)
## What I built
(What the software does, from a user's point of view. Short paragraphs or bullets.)
## How it works
(The architecture in plain words, then a Mermaid diagram in a ```mermaid block,
using `flowchart TD` (top-down reads well on phones). Keep it to 5-10 boxes. Only show parts that exist in the code.
Put box labels in double quotes, e.g. A["FastAPI server"].)
## Tech stack
(Bullets, grouped: languages, frameworks, infra/devops, AI/ML - only what's really used.)
## Engineering highlights
(3-5 bullets on the hardest or most impressive parts. Point to real files or functions.)
## Results
(Real outcomes only. If the repo shows no numbers, write placeholders like
[add: response time / users / accuracy] for the developer to fill in.)
## Skills shown
(A comma-separated list of skills a client would search for.)

Rules:
- Write in first person ("I built..."), confident and plain. No hype words like
  "revolutionary" or "cutting-edge".
- NEVER invent metrics, users, or features that aren't in the code. Use [add: ...] instead.
- Keep the whole thing under 600 words (not counting the diagram).

Repository scan:
{repo_scan}
"""

PITCH = """You are helping a developer apply for this opportunity:

--- OPPORTUNITY START ---
{job}
--- OPPORTUNITY END ---

These are case studies of their most relevant projects (best match first):

{case_studies}

Write a reply they can send (a freelance proposal, or an answer to the application question).

Rules:
- Open with the client's problem in one sentence, not with "Hi, I'm...".
- Connect 2-3 specific things from the projects to what the opportunity asks for.
  Name the project each one comes from.
- If no project matches some requirement, don't pretend - say briefly how they'd handle it.
- Never copy [add: ...] placeholders or invent numbers.
- End with one concrete next step (a question, or offering a quick call/demo).
- Under 180 words. Plain, direct, no buzzwords. Output only the reply text.
"""
