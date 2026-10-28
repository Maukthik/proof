# proof — project notes for Claude

## What this is
A CLI that turns a developer's GitHub repos into proof of skill: client-facing case studies,
job-matched pitches, and a portfolio page. Built by Maukthik J (second-year engineering student) to
win freelance work first, then to sell to other students/freelancers with the same problem.

Core problem it solves: good projects don't turn into evidence a client trusts, and every
application/proposal gets rewritten from scratch.

## Layout
Everything is in the `proof/` package (installed as the `proof` command via `pyproject.toml`).
- `proof/cli.py`: CLI with `case`, `pitch`, `lint`, `profile`, `site`, `log`
- `proof/scan.py`: reads a repo (git-tracked files only), picks what the LLM sees, sized to the model's context
- `proof/stack.py`: stack detection without an LLM: dependency files (Python, JS, Go, Rust, JVM/Android, Ruby, PHP), imports, language shares
- `proof/codemap.py`: which files import which (Python, JS/TS, Go, Java/Kotlin, Rust): grounds the architecture diagram
- `proof/prompts.py`: the LLM instructions (case study, pitch, profile). Material first, instructions last
- `proof/llm.py`: providers: anthropic, ollama, openai-compatible, mock (offline); retries; tidies replies (fences, preamble, Mermaid labels)
- `proof/facts.py`: per-project `facts.md`, written by the user, used for every claim
- `proof/match.py`: explainable job ↔ project ranking (no LLM)
- `proof/jobpost.py`: job post from a file, URL (schema.org JobPosting or page text) or stdin
- `proof/lint.py`: rule-based checks: pitch lint, case study format, numbers not found in any source
- `proof/tracker.py`: pitch log (`proof_output/pitches/log.json`) and reply rates
- `proof/portfolio.py`: static portfolio page (Python-Markdown + Mermaid via CDN)
- `templates/`: GitHub Actions: portfolio (Pages, daily + on ping), ping-portfolio, per-project case study
- `tests/test_proof.py`: pytest, no network or LLM needed
- `tools/survey.py`: dev check of what the model sees, across many real repos
- `examples/`: real output for doppel and client-desk: case studies, a pitch, a profile, the page
  (LLM replies written by Claude by hand from the real prompts, run through the real pipeline;
  see examples/README.md). Use them as the quality bar when tuning prompts.

## How to work on it
- Run tests: `python -m pytest -q` (all must pass before committing)
- Run without installing: `python -m proof ...`; or `pip install -e ".[test]"` once, then `proof ...`
- Try the whole flow with no model: `proof case <repo> --provider mock`, then `proof site`
- Real model: `--provider ollama` (Mauk's laptop: Windows, RTX 3050 6GB; has llama3.1:8b-instruct-q4_K_M,
  qwen3:4b-thinking, deepseek-coder-v2:16b-lite; run as `py -m proof`) or openai-compatible
- Test every change on a REAL repo too (e.g. maukthik/doppel, codefork, client-desk), not only the
  fixtures. Most bugs so far were found that way: side folders swamping the scan, dev deps counted as
  stack, README results cut off, root-level test files and legacy/ read as main code, schema.prisma
  never read, prompts too long for Ollama's context (it silently drops the START of the prompt).
- After touching scan.py / stack.py / codemap.py, run `python tools/survey.py <repos>` on repos of
  different stacks and sizes. The set used so far: Mauk's doppel (1,200 files), client-desk, codefork,
  gemma4, doppel-demo, doppel-shop-demo, doppel-try, FinanceFlow/FinanceFlow1/test1/git-journey (empty or
  near-empty: must be skipped), plus public fastapi/full-stack-fastapi-template, pallets/flask,
  karpathy/nanoGPT, jakevdp/PythonDataScienceHandbook, shadcn-ui/taxonomy, charmbracelet/glow (Go),
  BurntSushi/ripgrep (Rust), spring-projects/spring-petclinic (Java), android/sunflower (Kotlin).
- Check the portfolio page in a real browser when touching portfolio.py (desktop/mobile, light/dark,
  and that every Mermaid diagram draws).

## Code style (important)
- Mauk reads every line. Keep code plain and readable: small functions, clear names, a short comment
  on *why*, no clever one-liners or deep abstractions.
- Prefer the standard library; current deps are only `requests` and `markdown`.
- Never let the model invent metrics: missing facts become `[add: ...]` placeholders.
- Don't name a module after a stdlib module (we hit this with `site.py`).

## Status (2026-10-28)
Done and tested: multi-repo case studies with commit + facts caching, edit protection (`case_study.new.md`),
facts.md loop for [add: ...] gaps, notebook support, stack detection from deps and top-level imports,
import map for diagrams, importance-ordered scanning sized to the model's context, README results
extraction, case study format + invented-number checks, Mermaid label fixing, job matching, pitch from
file/URL/stdin + linter, profile + resume bullets, pitch log with reply rates, portfolio page (checked
desktop/mobile, light/dark, broken diagrams hidden), GH Action templates (portfolio on Pages,
ping, per-project), packaging (`pipx install git+https://github.com/Maukthik/proof`).

Tested on 19 real repos (see "How to work on it"): stacks, reading order, import maps, matching,
the 16-project portfolio page, URL clone + skip-without-clone, local folders with node_modules.

First real-model run (llama3.1:8b, doppel, 2026-10-28; saved in tests/fixtures/): format right,
no invented numbers, but (1) it turned "22 of 37 didn't run" into "caught 22 of 37", (2) generic
problem text ("many developers struggle... daunting"), (3) highlights with no file names, (4) a zero
result listed as an achievement, (5) project features in "Skills shown". Fixed with checks in lint.py
(flipped numbers, vague highlights, filler) and bad/good examples in prompts.py.

Second run: the 8B model COPIED the prompt's realistic examples into both case studies (a made-up
`sync/queue.py`, "12 of 40 tests", `app/main.py`, "Small clinics...", skills list). Lessons:
- Never put realistic example content in a prompt for small models. Use fill-in shapes only
  (`<a real file from the scan>`), and say "the shapes show the form only".
- Checks beat instructions. lint.py now also flags: files that aren't in the repo, text copied
  from the prompt, Results numbers the README/facts don't state (code is full of numbers, so
  "appears somewhere in the repo" proved nothing), named technologies the repo never mentions.
- `proof case` sends the model ONE repair request listing the problems and keeps whichever
  version has fewer (prompts.REVISE). Small models fix listed problems much better than they
  avoid them.

## Next gaps to close (in priority order)
1. Keep tuning `prompts.py` on Mauk's real repos with a real model (`proof case ... --force`). Save each
   real output that shows a new failure in tests/fixtures/ with a test that catches it. Look at: sections missing, diagram boxes that don't exist, numbers
   flagged by the claim check, generic "Skills shown".
2. Try the templates for real: a `portfolio` repo with repos.txt, Pages on, one ping from doppel.
3. `proof apply`: watch a job feed (RSS / saved search) and draft pitches for good matches.
4. Learn from the pitch log: feed the best-replying projects/angles back into the pitch prompt.
5. Publish to PyPI (name `proof-cli` in pyproject.toml) once the real-model output is good.
