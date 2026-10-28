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
(2-4 sentences about THIS project: who has the problem it solves (a kind of person or
business) and what goes wrong for them today. Take it from the README.)
## What I built
(What the software does, from a user's point of view. Short paragraphs or bullets.)
## How it works
(The architecture in plain words, 3-5 sentences. Then a Mermaid diagram in a ```mermaid
block, with no sentence introducing it:
- first line `flowchart TD` (top-down reads well on phones)
- 5-10 boxes for real parts of THIS code, from "How the files connect" and the files shown.
  Each label: what the part does, then its real path from the scan in brackets, in double
  quotes: A["<what it does> (<path from the scan>)"].)
## Tech stack
(Bullets, grouped: languages, frameworks, infra/devops, AI/ML - only what's really used.
Leave out a group that would be empty.)
## Engineering highlights
(3-5 bullets on the hardest parts. Each bullet has this shape:
`<a real file or function from the scan>` <what it does>, so <why that matters or was hard>.
Never name a file that isn't in the scan.)
## Results
(Only results the README or the facts state. Copy each number together with the words the
repo uses for it, and never change what it counts: if the repo says something did NOT work,
don't write it as a success. Skip zeros and failures. If the repo states no results, write
placeholders like [add: response time / users / accuracy].)
## Skills shown
(Comma-separated skills a client would type into a job search: the technologies from the
"Detected stack" line and your Tech stack section, plus practices this code clearly shows.
Not features of this project.)

Rules:
- Everything you write is about THIS repository. The shapes above show the form only.
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
(One line, under 70 characters, in the shape "<role> - <what they build>", using the
main technologies of the projects below. No adjectives like "passionate".)
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
- Everything you write comes from the case studies above. The shapes show the form only.
- Only claims the case studies back up. Use only numbers that appear in them or in the
  facts, and keep what each one measured. Never copy [add: ...] placeholders - leave that
  detail out instead.
- Plain, direct words. No buzzwords.
- Output only the Markdown above.
"""


# A second pass, when the checks in lint.py find problems in a draft. Small models are much
# better at fixing a listed problem than at avoiding it the first time.
REVISE = """Below is a scan of a code repository, facts from its developer, a case study
written about it, and problems found in that case study.

=== REPOSITORY SCAN ===
{repo_scan}
=== END OF REPOSITORY SCAN ===

=== FACTS FROM THE DEVELOPER (true - use them) ===
{facts}
=== END OF FACTS ===

=== CASE STUDY ===
{case_study}
=== END OF CASE STUDY ===

Problems found in the case study:
{problems}

Task: rewrite the case study so every problem above is gone. Keep the same sections and
everything that was right. Use only files, numbers and facts that appear in the scan or the
facts; where a fact is missing, write an [add: ...] placeholder instead of guessing.
Output only the corrected case study, starting with the "# " title line.
"""
