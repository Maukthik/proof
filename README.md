# proof: turn your repos into proof of skill

```
your repos ──case──▶ case studies ──pitch──▶ tailored pitch for a job post (+ lint)
                           └──────site──▶ portfolio page
```

## Setup

```bash
pip install -r requirements.txt      # requests + markdown; also needs git
```

Try the whole flow with **no LLM and no key** first:

```bash
python proof.py case ./some-repo --provider mock
python proof.py site
```

Then pick a real LLM:

| Provider | Cost | Setup |
|---|---|---|
| `ollama` | Free, local | `ollama pull qwen2.5-coder:7b`, then `ollama serve` |
| `openai` (any compatible API) | Free tiers exist (OpenRouter, Groq, Gemini) | `OPENAI_BASE_URL=...`, `OPENAI_API_KEY=...`, `--model <id>` |
| `anthropic` | Paid, best writing | `ANTHROPIC_API_KEY=...` |

To avoid typing the provider every time: `export PROOF_PROVIDER=ollama` (and `PROOF_MODEL=...`).

## Commands

```bash
# 1. Case studies: any mix of local folders and GitHub URLs.
#    Re-running skips repos with no new commits (--force to redo).
python proof.py case https://github.com/you/doppel ./rag-chatbot ./negotiation-platform

# 2. Pitch: paste a job post into a .txt file
python proof.py pitch upwork_job.txt
#   -> shows which projects match and why (shared tech terms),
#      writes a pitch from the top 2, then lints it

# 3. Lint any pitch you wrote yourself
python proof.py lint my_pitch.txt --job upwork_job.txt

# 4. Portfolio page -> proof_output/site/index.html
python proof.py site --owner "Your Name" --contact "you@mail.com · github.com/you"
```

Output layout:
```
proof_output/
  <repo>/case_study.md     edit this freely, it's yours
  <repo>/meta.json         commit, detected stack, model used
  pitches/<job>.md
  site/index.html          upload to GitHub Pages / Netlify
```

**Fill in the `[add: ...]` gaps.** The model is told never to invent numbers, so real
results (latency, accuracy, users) have to come from you. The site highlights unfilled gaps in
yellow, and the linter blocks pitches that still contain them.

## What each file does

| File | Job |
|---|---|
| `proof.py` | Command line: `case`, `pitch`, `lint`, `site` |
| `scan.py` | Reads a repo, including Jupyter notebooks; detects the stack from deps and imports |
| `prompts.py` | The instructions sent to the LLM. Edit these to change the writing style |
| `llm.py` | Talks to Anthropic / Ollama / OpenAI-compatible APIs / mock |
| `match.py` | Ranks your projects against a job post (no LLM, explainable) |
| `lint.py` | Pitch checks: placeholders, length, greeting openers, buzzwords, missing tech |
| `portfolio.py` | Builds the portfolio page |
| `templates/proof-workflow.yml` | GitHub Action: refreshes `docs/CASE_STUDY.md` on every push |

## Tests

```bash
pip install pytest pyyaml
python -m pytest -q          # 26 tests, no LLM or internet needed
```

## Roadmap
- [x] Multi-repo case studies with caching
- [x] Job-post matching + pitch + linter
- [x] Portfolio page
- [x] GitHub Action template
- [ ] Tune prompts on real model output (needs real runs)
- See CLAUDE.md for the full list of next gaps
- [ ] `proof.py apply`: watch a job feed and draft pitches for good matches
- [ ] Track which pitches got replies, to learn what works
