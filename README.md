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
6. **Suggestions**: what to build next in a project so it's stronger proof, as tasks you can
   hand to a coding assistant.
7. **An eval and a training kit**: score models on the task, and fine-tune a local one.
8. **Job finding and follow-through**: new jobs from public job boards that fit your
   projects (with pitch drafts), follow-up reminders and drafts, and a brief for the
   client call. It never sends anything for you.

```
your repos ──case──▶ case studies ──pitch──▶ pitch for a job post (+ lint, + log)
             facts.md ──┘    ├──profile──▶ Upwork / LinkedIn text + resume bullets
                             └──site─────▶ portfolio page (GitHub Pages)
```

Works with Python (incl. notebooks), JavaScript/TypeScript (React, Next.js, Node), Go, Rust,
Java/Kotlin (Spring, Android), plus Ruby and PHP dependency files. Tested on 19 real repos,
from a 1-file repo to 5,500-commit projects.

It never invents results. Missing facts become `[add: ...]` gaps, every number in generated
text is checked against your repo and your own notes, and each result in a case study links
to the README line it comes from.

**New here? Read [docs/PLAYBOOK.md](docs/PLAYBOOK.md)** - every feature in plain words and
the full workflow, from first run to won job.

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

# 7. What to build next in a project: a checklist, what clients asked for, ideas + tasks
proof suggest ./doppel                 # -> proof_output/doppel/suggestions.md
proof suggest ./doppel --no-ai         # checklist and client asks only, instant

# 8. Which model writes the best case studies? (repeat after any prompt change)
proof eval ./doppel ./client-desk --provider ollama --models llama3.1:8b-instruct-q4_K_M qwen3:4b

# 9. Training data for fine-tuning a local model (see training/README.md)
proof dataset --exclude doppel client-desk

# 10. New jobs that fit your projects, from public job boards, + pitch drafts for the top 3
proof apply                            # Remotive, Remote OK, We Work Remotely, HN freelance
proof apply hn https://example.com/jobs.rss --days 7 --no-ai

# 11. No reply after 4 days? `proof log` says so; draft one follow-up
proof followup need-a-fastapi-dev
proof log need-a-fastapi-dev followed-up

# 12. They want a call: likely questions + answers from your projects, gaps, an intro
proof prep need-a-fastapi-dev

# 13. Let a coding agent write it, with proof as the checker (see below)
proof scan ./doppel --prompt          # what the model would see, secrets removed
proof check draft.md --repo ./doppel --save
```

A file listing repos (one per line, `#` comments) works anywhere repos go: `proof case
"@training/repos.txt"` (keep the quotes in PowerShell).

Output layout:
```
proof_output/
  <repo>/case_study.md      edit it freely: proof never overwrites your edits
  <repo>/case_study.new.md  a regenerated version, when you had edited the one above
  <repo>/facts.md           yours: real numbers, users, links. Used for every claim
  <repo>/meta.json          commit, detected stack, model used
  pitches/<job>.md          one per job post (+ <job>.job.txt, the post itself,
                            and <job>.followup.md)
  pitches/log.json          what you sent and what happened
  jobs/<date>.md            jobs `proof apply` found that fit, with why and what's missing
  jobs/seen.json            jobs already shown (so each run shows only new ones)
  prep/<job>.md             call briefs
  profile.md                Upwork / LinkedIn text + resume bullets
  site/index.html           upload to GitHub Pages / Netlify
```

## What the model gets to see

`proof` reads what git tracks (so `.gitignore`d folders, build output and `.env` files are
never looked at; secret files are skipped even outside git). Then it picks files in order of
importance: README and dependency files, entry points and data schemas, then the modules most
other files import. Tests, examples, benchmarks, generated code, config files and copies come
last. The amount is sized to the model: about 35K characters for Ollama's default context,
70K for cloud models. Repos with no code and no real README are skipped: there's nothing true
to write. To see exactly what a model would get: `proof case <repo> --dry-run`.

## Use it with a coding agent

A strong agent (Claude Code, Cursor, Codex) writes better than a small local model, but it
still needs facts and checks. `agents/proof-case-study/SKILL.md` gives it the routine:
`proof scan <repo> --prompt` for the material, write the case study, `proof check` until it
passes, then `proof check --save` to link the results and file it. Copy that folder to
`~/.claude/skills/` for Claude Code, or paste the file into another agent's rules.

## How it keeps things true

- The model is told to use only numbers from the repo scan and your `facts.md`. Anything else
  becomes an `[add: ...]` gap, which the site highlights in yellow and the linter blocks.
- After writing, every number is checked: any that appears in neither the repo nor your facts
  is flagged ("the model may have made this up"). Pitches are checked against the case
  studies and the job post.
- The diagram is based on which files actually import which. After writing, every arrow
  between two real files is checked against the imports; one the code doesn't show is drawn
  dashed. Boxes link to their files on GitHub. A diagram that fails to draw is left off the
  page rather than shown as an error.
- Keys and passwords written into the code are removed before anything reaches a model, and
  `proof` tells you which files to clean up.

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
| `proof/cli.py` | Command line: `case`, `scan`, `check`, `pitch`, `lint`, `profile`, `site`, `log`, `apply`, `followup`, `prep`, `suggest`, `eval`, `dataset` |
| `proof/casestudy.py` | One case study: draft, checks, one repair round, source links |
| `proof/claims.py` | Links each result to the README line it comes from |
| `proof/diagram.py` | Checks diagram arrows against the imports; links boxes to files |
| `proof/redact.py` | Keeps keys and passwords in the code out of every prompt |
| `proof/outline.py` | Signatures of the files that don't fit the model's budget |
| `proof/scan.py` | Reads a repo (incl. notebooks) and picks what the LLM sees |
| `proof/stack.py` | Detects the stack from dependency files, imports and languages |
| `proof/codemap.py` | Which files import which: the skeleton of the architecture diagram |
| `proof/prompts.py` | The instructions sent to the LLM. Edit these to change the writing style |
| `proof/llm.py` | Talks to Anthropic / Ollama / OpenAI-compatible APIs / mock; tidies replies |
| `proof/facts.py` | Your per-project facts file |
| `proof/match.py` | Ranks your projects against a job post (no LLM, explainable) |
| `proof/jobpost.py` | Reads a job post from a file, a URL or a paste |
| `proof/lint.py` | Checks: placeholders, invented numbers, length, openers, buzzwords, format |
| `proof/tracker.py` | The pitch log, follow-up reminders |
| `proof/feeds.py` | Reads job boards: Remotive, Remote OK, We Work Remotely, Hacker News, any RSS/Atom feed |
| `proof/apply.py` | `proof apply`: which new jobs fit your projects, and why |
| `proof/portfolio.py` | Builds the portfolio page |
| `proof/suggest.py` | What to build next: checklist, client asks, ideas as coding tasks |
| `proof/evaluate.py` | `proof eval`: scores models with the checks, compares with the last run |
| `proof/dataset.py` | Fine-tuning data from case studies we trust |
| `training/` | Fine-tuning kit: public repo list, Kaggle training script, Ollama Modelfile, guide |
| `agents/proof-case-study/` | Skill file: how a coding agent writes case studies with proof |
| `docs/PLAYBOOK.md` | How to use everything, step by step |
| `docs/COMPARISON.md` | proof next to REA, gitdiagram, aider, repomix, DeepWiki, portfolio and proposal tools |
| `templates/` | GitHub Actions (see above) |
| `tools/survey.py` | Dev check: what the model would see, across many repos |
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
- [x] Claim links, `proof eval`, `proof suggest`, fine-tuning kit
- [ ] Tune prompts on real model output (see CLAUDE.md)
- [ ] Run the fine-tuning loop for real (training/README.md)
- [x] `proof apply` (job boards -> fits -> pitch drafts), follow-ups, call prep
- [ ] Learn from the pitch log: feed what gets replies back into matching and pitches
