"""prompts.py - the instructions we give the LLM. Edit these to change the writing style.

The material (repo scan, case studies, job post) comes first and the instructions come
last. Small local models follow the most recent text best, and if a prompt is ever too
long, Ollama cuts the *start* of it: we'd rather lose some code than the instructions.
"""

CASE_STUDY = """Below is a scan of a developer's code repository, then facts the developer
gave about it. Read both, then do the task at the end.

=== REPOSITORY SCAN ===
{repo_scan}
=== END OF REPOSITORY SCAN ===

=== FACTS FROM THE DEVELOPER (true - use them) ===
{facts}
=== END OF FACTS ===

Task: write a case study of this project for freelance clients and employers. They want
to know "can this person build what I need?" - write for them, not for a professor.

Use Markdown with exactly these sections, in this order:

# <Project name> - <one line: what it does, and for whom>
## The problem
(2-4 sentences: who exactly has this problem, and what goes wrong for them without this.
Bad: "Many developers struggle with testing, which can be a daunting task."
Good: "Small clinics book appointments by phone, so every missed call is a lost patient
and the front desk spends hours a day on calls.")
## What I built
(What the software does, from a user's point of view. Short paragraphs or bullets.)
## How it works
(The architecture in plain words, 3-5 sentences. Then a Mermaid diagram in a ```mermaid
block, with no sentence introducing it:
- first line `flowchart TD` (top-down reads well on phones)
- 5-10 boxes for real parts of the code, taken from "How the files connect" and the files
  shown. Label each box with what it does and its file, e.g. A["Web API (app/main.py)"].
- every box label in double quotes)
## Tech stack
(Bullets, grouped: languages, frameworks, infra/devops, AI/ML - only what's really used.)
## Engineering highlights
(3-5 bullets on the hardest parts. Each one names a real file or function from the scan
in backticks, says what it does, and why that was hard or clever.
Bad: "Developed a comparison algorithm to identify changes."
Good: "`sync/queue.py` retries failed uploads with backoff and resumes from the last
chunk, so a dropped connection never loses a file.")
## Results
(Real outcomes only: from the facts, or results written in the repo (README results,
benchmarks, test counts). Keep each number with exactly what it measured, in the repo's own
words - never change its meaning: "12 of 40 tests didn't run" must NOT become "passed 12
of 40 tests".
Pick the results that show the project working; skip zeros and failures. If there are no
results, write placeholders like [add: response time / users / accuracy].)
## Skills shown
(Comma-separated skills a client would type into a job search: technologies and practices,
like "REST APIs", "CI/CD", "LLM agents", "PostgreSQL". Not features of this project.)

Rules:
- First person ("I built..."), confident and plain. No hype or filler: not "revolutionary",
  "cutting-edge", "seamless", "robust", "daunting", "struggle".
- NEVER invent numbers, users, clients or features. Every number you write must appear in
  the scan or the facts. Anything missing becomes an [add: ...] placeholder.
- Under 600 words, not counting the diagram.
- Output only the case study, starting with the "# " title line.
"""

PITCH = """A developer is applying for this opportunity:

=== OPPORTUNITY ===
{job}
=== END OF OPPORTUNITY ===

These are case studies of their most relevant projects (best match first):

{case_studies}

Task: write the reply they will send (a freelance proposal, or an answer to the
application question).

Rules:
- Open with the client's problem in one sentence, not with "Hi, I'm...".
- Connect 2-3 specific things from the projects to what the opportunity asks for.
  Name the project each one comes from.
- If no project matches some requirement, don't pretend - say briefly how they'd handle it.
- Use only numbers that appear in the case studies or facts, and keep what each one
  measured. Never copy [add: ...] placeholders.
- End with one concrete next step (a question, or offering a quick call or demo).
- Under 180 words. Plain, direct, no buzzwords.
- Output only the reply text.
"""

PROFILE = """These are case studies of a developer's projects:

{case_studies}

Task: write profile text they can paste into Upwork and LinkedIn, plus resume bullets.
Use exactly this Markdown:

## Headline
(One line, under 70 characters, saying what they build. Example: "Python developer -
RAG chatbots and LLM tools". No adjectives like "passionate".)
## About
(For the Upwork overview and LinkedIn About. 120-200 words, first person. Open with the
problems they solve for clients, then 2-3 projects as proof (name each), then the kind of
work they want. End by inviting the reader to get in touch.)
## Skills
(10-15 skills shown in the projects, comma-separated, most in-demand first.)
## Resume bullets
### <Project name>
- (2-3 bullets per project, one line each. Start with a past-tense verb (Built, Designed,
  Automated...), say what was built and with which tech, and the result if there is one.)

Rules:
- Only claims the case studies back up. Use only numbers that appear in them or in the
  facts, and keep what each one measured. Never copy [add: ...] placeholders - leave that detail out instead.
- Plain, direct words. No buzzwords.
- Output only the Markdown above.
"""
