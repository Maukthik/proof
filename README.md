# proof: turn your repos into proof of skill

Good projects don't turn into evidence a client trusts, and every proposal gets written
from scratch. `proof` reads your GitHub repos and gives you:

1. **Case studies** for clients, not professors: problem, what you built, how it works
   (with an architecture diagram drawn from the code's real imports), stack, results.
2. **Tailored pitches**: give it a job post (file, URL or paste) and it picks your best-matching
   projects, says why, writes the reply, and checks it.
3. **Profile text**: an Upwork/LinkedIn "about" section and resume bullets.
4. **A portfolio page** that can rebuild itself every time you push code.
5. **A pitch log** that shows which projects and skills actually get replies.

```
your repos ──case──▶ case studies ──pitch──▶ pitch for a job post (+ lint, + log)
             facts.md ──┘    ├──profile──▶ Upwork / LinkedIn text + resume bullets
                             └──site─────▶ portfolio page (GitHub Pages)
```

It never invents results. Missing facts become `[add: ...]` gaps, and every number in
generated text is checked against your repo and your own notes.

## Install

```bash
pipx install git+https://github.com/Maukthik/proof
```

(or `pip install -e .` in a clone; needs Python 3.10+ and git). Try the whole flow with
**no LLM and no key** first:

```bash
proof case ./some-repo --provider mock
proof site
```

Then pick a real LLM:

| Provider | Cost | Setup |
|---|---|---|
| `ollama` | Free, local | `ollama pull qwen2.5-coder:7b`, then `ollama serve` |
| `openai` (any compatible API) | Free tiers exist (OpenRouter, Groq, Gemini) | `OPENAI_BASE_URL=...`, `OPENAI_API_KEY=...`, `--model <id>` |
| `anthropic` | Paid, best writing | `ANTHROPIC_API_KEY=...` |

To avoid typing it every time: `export PROOF_PROVIDER=ollama` (and `PROOF_MODEL=...`).
With Ollama the repo scan is sized to fit the context window (`OLLAMA_NUM_CTX`, default
16384 tokens); raise it if your GPU has room and you want the model to see more code.

## Use it

```bash
# 1. Case studies: any mix of local folders and GitHub URLs.
#    Re-running skips repos with no new commits and no new facts (--force to redo).
proof case https://github.com/you/doppel ./rag-chatbot ./negotiation-platform

# 2. Fill the gaps: each project gets proof_output/<repo>/facts.md with one line per
#    [add: ...] gap. Write real numbers there, then run `proof case` again.

# 3. Pitch for a job: a text file, a URL, or - to paste it
proof pitch upwork_job.txt
proof pitch https://boards.greenhouse.io/acme/jobs/123
proof pitch -
#   -> shows which projects match and why, writes the pitch from the top 2, then lints it

# 4. Track what you send, and see what works
proof log need-a-fastapi-dev sent
proof log need-a-fastapi-dev replied --note "wants a call Friday"
proof log

# 5. Profile text + resume bullets from all your case studies
proof profile

# 6. Portfolio page -> proof_output/site/index.html
proof site --owner "Your Name" --contact "you@mail.com · github.com/you"

# Check any pitch you wrote yourself
proof lint my_pitch.txt --job upwork_job.txt
```

Output layout:
```
proof_output/
  <repo>/case_study.md      edit it freely: proof never overwrites your edits
  <repo>/case_study.new.md  a regenerated version, when you had edited the one above
  <repo>/facts.md           yours: real numbers, users, links. Used for every claim
  <repo>/meta.json          commit, detected stack, model used
  pitches/<job>.md          one per job post
  pitches/log.json          what you sent and what happened
  profile.md                Upwork / LinkedIn text + resume bullets
  site/index.html           upload to GitHub Pages / Netlify
```

## How it keeps things true

- The model is told to use only numbers from the repo scan and your `facts.md`. Anything else
  becomes an `[add: ...]` gap, which the site highlights in yellow and the linter blocks.
- After writing, every number is checked: any that appears in neither the repo nor your facts
  is flagged ("the model may have made this up"). Pitches are checked against the case
  studies and the job post.
- The diagram is based on which files actually import which (Python and JS/TS), so it shows
  the real structure. Labels are quoted so Mermaid can draw them, and a diagram that still
  fails is left off the page rather than shown as an error.

## Keep it updated automatically (GitHub Actions)

| Template | Put it in | What it does |
|---|---|---|
| `templates/portfolio-workflow.yml` | a `portfolio` repo with a `repos.txt` | Daily (and on ping): updates changed projects only, publishes the page to GitHub Pages |
| `templates/ping-portfolio.yml` | each project repo | On push, tells the portfolio to rebuild now |
| `templates/proof-workflow.yml` | a project repo | On push, keeps `docs/proof/<repo>/case_study.md` in that repo up to date |

Setup steps are at the top of each file. Unchanged projects are skipped without cloning,
so a quiet day costs no LLM calls.

## What each file does

| File | Job |
|---|---|
| `proof/cli.py` | Command line: `case`, `pitch`, `lint`, `profile`, `site`, `log` |
| `proof/scan.py` | Reads a repo (incl. notebooks), picks what the LLM sees, detects the stack |
| `proof/codemap.py` | Which files import which: the skeleton of the architecture diagram |
| `proof/prompts.py` | The instructions sent to the LLM. Edit these to change the writing style |
| `proof/llm.py` | Talks to Anthropic / Ollama / OpenAI-compatible APIs / mock; tidies replies |
| `proof/facts.py` | Your per-project facts file |
| `proof/match.py` | Ranks your projects against a job post (no LLM, explainable) |
| `proof/jobpost.py` | Reads a job post from a file, a URL or a paste |
| `proof/lint.py` | Checks: placeholders, invented numbers, length, openers, buzzwords, format |
| `proof/tracker.py` | The pitch log |
| `proof/portfolio.py` | Builds the portfolio page |
| `templates/` | GitHub Actions (see above) |
| `examples/` | Real output for two projects: case studies, a pitch, a profile, the page |

## Tests

```bash
pip install -e ".[test]"
python -m pytest -q          # no LLM or internet needed
```

## Roadmap
- [x] Case studies with caching, facts and edit protection
- [x] Job matching, pitch (file / URL / paste), linter, claim checks
- [x] Profile text and resume bullets
- [x] Pitch log with reply rates per project and skill
- [x] Portfolio page + GitHub Actions to keep it updated
- [ ] Tune prompts on real model output (see CLAUDE.md)
- [ ] `proof apply`: watch a job feed and draft pitches for good matches
