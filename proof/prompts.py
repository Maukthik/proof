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


SUGGEST = """Below is a scan of a developer's repository, a checklist of what clients look for,
and technologies clients asked for in jobs the developer applied to with this project.

=== REPOSITORY SCAN ===
{repo_scan}
=== END OF REPOSITORY SCAN ===

=== CHECKLIST ===
{checklist}
=== END OF CHECKLIST ===

=== WHAT CLIENTS ASKED FOR ===
{wanted}
=== END ===

Task: suggest 3-5 features or improvements to build next in THIS project, so it becomes
stronger proof for clients like the ones above. Prefer small, visible changes a client would
notice, built on the code that is already there. Don't repeat checklist items unless you
make them specific to this code.

For each one, use exactly this shape (the shape shows the form only):
### <short title>
- What: <one or two sentences, specific to this code>
- Why a client cares: <one sentence>
- Where: <real files from the scan to change; new files marked (new)>
- Size: <small (hours) | medium (a day) | large (days)>
- Done when: <a check anyone can do: a command to run, or a result to see>

Rules:
- Name only files that appear in the scan, or new files marked (new).
- Output only the ideas.
"""


FOLLOW_UP = """A developer sent this message about an opportunity a few days ago and got no
reply yet.

=== OPPORTUNITY ===
{job}
=== END OF OPPORTUNITY ===

=== THEIR FIRST MESSAGE ===
{pitch}
=== END OF FIRST MESSAGE ===

Case studies of the projects they mentioned:

{case_studies}

Task: write a short follow-up message they can send now.

Rules:
- Give the client one NEW reason to reply: a specific detail from the case studies that the
  first message didn't use (a feature, a file, a result), tied to something the opportunity
  asks for. Or a small, concrete first step they could take for the client.
- Don't repeat the first message, don't apologise, and don't write "just following up",
  "checking in", "circling back" or "any update".
- Use only numbers that appear in the case studies or facts, and keep what each one
  measured. Never copy [add: ...] placeholders.
- End with one easy question.
- Under 80 words. Plain and friendly.
- Output only the message text.
"""


PREP = """A client answered a developer and wants to talk. Below are the opportunity, the
developer's message, their notes, case studies of their projects, and the technologies the
opportunity names that none of their projects show.

=== OPPORTUNITY ===
{job}
=== END OF OPPORTUNITY ===

=== THEIR MESSAGE ===
{pitch}
=== END OF MESSAGE ===

=== NOTES ===
{notes}
=== END OF NOTES ===

{case_studies}

=== NOT SHOWN IN ANY PROJECT ===
{gaps}
=== END ===

Task: write a one-page brief the developer reads before the call. Use exactly this
Markdown (the shapes show the form only):

## What they need
(2-3 bullets: the client's goal and main requirements, in the client's own words.)
## Questions they'll likely ask
(5-7 questions this client is likely to ask. Each one as `### <question>`, then a 2-4
sentence answer in the developer's voice (first person), taken from the case studies:
name the project, and the feature or file that shows it.)
## Gaps to be ready for
(One bullet per technology in "not shown in any project": an honest answer - what they
have used that is close, from the case studies, and how they would get up to speed.
Write "None." if that list is empty.)
## Questions to ask them
(4-5 questions that pin down the work: who uses it, what data, deadline, what "done"
looks like, how they'll judge it.)
## 30-second intro
(What the developer says first: who they are, the most relevant project, and one result.)

Rules:
- Every claim comes from the case studies or facts. Never claim experience they don't
  show; for anything missing, say how they would handle it.
- Use only numbers that appear in the case studies or facts, and keep what each one
  measured. Never copy [add: ...] placeholders.
- Plain words, no buzzwords.
- Output only the Markdown above.
"""


NEW_PROJECT = """A developer wants to start a new project. Below are their idea, the
technologies they have already used in their projects, and technologies clients asked for
in jobs they applied to.

=== IDEA ===
{idea}
=== END OF IDEA ===

=== TECHNOLOGIES THEY HAVE USED ===
{known}
=== END ===

=== TECHNOLOGIES CLIENTS ASKED FOR (how many jobs) ===
{wanted}
=== END ===

Task: write a short, practical plan for a first version they can finish in 2-4 weeks of
evenings. Use exactly this Markdown (the shapes show the form only):

# <Project name: one or two words> - <one line: what it does, and for whom>
## The problem
(2-3 sentences: who has this problem and what goes wrong for them today.)
## Who it's for
(One or two kinds of users.)
## First version
(3-6 bullets: the features of the first version, from a user's point of view. Leave out
everything that can wait.)
## Stack
(Bullets. Mostly technologies they have already used. One technology clients asked for
is good if it fits the idea - say which one and why.)
## Milestones
(3-5 numbered steps, each ending with "- done when: <a check anyone can do>".)
## First tasks
(5-8 bullets, each a task of a few hours, in the order to do them.)
## Proof to collect
(2-4 bullets: what to measure or show once it works, so the project becomes evidence for
clients - for example a timing, an accuracy, a user count, a screenshot.)

Rules:
- Everything is about THIS idea. No market sizes, statistics or numbers you don't know.
- Plain words, no buzzwords.
- Output only the Markdown above, starting with the "# " title line.
"""
