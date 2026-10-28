# proof — project notes for Claude

## What this is
A CLI that turns a developer's GitHub repos into proof of skill: client-facing case studies,
job-matched pitches, and a portfolio page. Built by Maukthik J (second-year engineering student) to
win freelance work first, then to sell to other students/freelancers with the same problem.

Core problem it solves: good projects don't turn into evidence a client trusts, and every
application/proposal gets rewritten from scratch.

## Layout
- `proof.py`: CLI with `case`, `pitch`, `lint`, `site`
- `scan.py`: reads a repo, picks what the LLM sees, detects the stack without an LLM
- `prompts.py`: the LLM instructions (case study, pitch)
- `llm.py`: providers: anthropic, ollama, openai-compatible, mock (offline)
- `match.py`: explainable job ↔ project ranking (no LLM)
- `lint.py`: rule-based pitch checks
- `portfolio.py`: static portfolio page (Python-Markdown + Mermaid via CDN)
- `templates/proof-workflow.yml`: GitHub Action template
- `tests/test_proof.py`: pytest, no network or LLM needed
- `examples/doppel/`: real output for github.com/maukthik/doppel (case study written by
  Claude following prompts.py by hand, since no model was available)

## How to work on it
- Run tests: `python -m pytest -q` (all must pass before committing)
- Try the whole flow with no model: `python proof.py case <repo> --provider mock`, then `python proof.py site`
- Real model: `--provider ollama` (Mauk's laptop: RTX 3050 6GB, runs qwen2.5-coder:7b) or openai-compatible
- Test every change on a REAL repo too (e.g. maukthik/doppel), not only the fixtures. Most bugs so far
  were found that way: side folders swamping the scan, dev deps counted as stack, README results cut off.

## Code style (important)
- Mauk reads every line. Keep code plain and readable: small functions, clear names, a short comment
  on *why*, no clever one-liners or deep abstractions.
- Prefer the standard library; current deps are only `requests` and `markdown`.
- Never let the model invent metrics: missing facts become `[add: ...]` placeholders.
- Don't name a module after a stdlib module (we hit this with `site.py`).

## Status (2026-10-28)
Done and tested: multi-repo case studies with commit caching, notebook support, stack detection from
deps and top-level imports, main-code-first scanning, README results extraction, case study format check,
job matching, pitch + linter, portfolio page (checked desktop/mobile, light/dark), GH Action template.

Not yet verified: output quality from a real model. That's the first thing to check.

## Next gaps to close (in priority order)
1. Run on Mauk's real repos with a real model; tune `prompts.py` from what comes out wrong.
2. `pitch` from a job URL or pasted text (stdin), not only a file.
3. Profile outputs from the same case studies: Upwork/LinkedIn "about" text and resume bullets.
4. Pitch tracker: log sent pitches and replies (`proof.py log`) to learn which projects and angles win.
5. Verify claims: flag case-study numbers that don't appear anywhere in the repo scan.
6. Package it: `pyproject.toml` with a `proof` command, so `pipx install` works.
