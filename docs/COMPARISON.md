# proof compared with similar tools

Researched 2026-10-28. Repos marked **(read)** were cloned and their README, prompts or
code read directly; the others come from listings and articles, so check them yourself.

## The landscape

| Tool | What it does | Closest proof feature |
|---|---|---|
| **REA - Reverse Engineer Anything** (read) | An MCP server that lets AI agents (Claude Code, Codex, Cursor ...) inspect binaries, Electron/JS apps, .NET, APKs and websites *without source code*, and return findings with their evidence and limits. | None - different job. proof explains *your own* code to *clients*. |
| **gitdiagram** (read) | Repo URL -> interactive architecture diagram. A SOURCE INDEX computed by code (not the model) lists which files reference which; every edge must cite an evidence file; unshown edges are dashed; nodes link to files. | The diagram in each case study |
| **aider repo map** (read) | tree-sitter tags of definitions and references -> a file graph ranked with PageRank -> the most important signatures that fit a token budget. | Scan order and outlines |
| **repomix** (read) | Packs a repo into one AI-ready file: token counts, Secretlint secret detection, tree-sitter `--compress` (signatures only), MCP server, agent skills, GitHub Action. | The repo scan |
| **gitingest** (read) | Repo -> text digest for prompts; web, CLI, browser extension. | The repo scan |
| **DeepWiki / deepwiki-open** (read) | AI-written wiki plus chat for any repo. | Case studies (but those are docs for developers) |
| **readme-ai** (read) | Generates a README with styled headers and badges. | `proof suggest` (what the README is missing) |
| Foliox, GitFolio, devb.io, GitHired, PortGen | Portfolio sites or profile summaries from your GitHub account. | `proof site`, `proof profile` |
| GigRadar, Upwex, PouncerAI | Upwork job alerts, auto-bidding, AI proposals, reply analytics. | `proof apply`, `proof pitch`, `proof log`, `proof followup` |

## Where proof is different

1. **Written for clients, per project.** The portfolio tools summarise a GitHub profile; the
   docs tools explain code to developers. proof writes one case study per project for
   someone deciding whether to hire you: the problem, what you built, results, skills.
2. **Claims are checked, then linked to their source.** Every number must appear in the
   README or your facts with the same meaning ("22 of 37 didn't run" can't become "caught
   22 of 37"); invented files, copied prompt text and filler are caught; the model gets
   one repair round; each result links to its README line, pinned to the commit.
3. **From evidence to a sent pitch.** Explainable job matching ("next.js, stripe, prisma"),
   a pitch linter, and a log of replies per project - the proposal tools write pitches
   without evidence, and the portfolio tools stop at a page.
4. **Runs on a laptop.** Local models through Ollama, with the prompt sized to fit their
   context; no account, no server.
5. **Measured.** `proof eval` scores models and prompt changes with the same checks, and
   the training kit fine-tunes a local model on outputs that passed them.

## Where the others are ahead

- **Code parsing:** aider and repomix use tree-sitter for every language; proof uses
  Python's own parser for Python and line patterns elsewhere (less exact for JS/Go/Rust/Java).
- **Diagram depth:** gitdiagram plans the diagram in two model passes (an explanation
  with components and evidence, then the graph) and aims for 12-24 components on big
  products; proof's diagram is part of one case-study answer, 5-10 boxes.
- **Reach:** REA analyses closed-source software of 30+ kinds; DeepWiki answers questions
  about any public repo; the proposal tools watch Upwork itself (proof reads public boards
  only: Remotive, Remote OK, We Work Remotely, Hacker News, any RSS feed).
- **Polish:** the hosted tools have web apps, browser extensions and hourly refreshes.

## What proof took from them

| Idea | From | In proof |
|---|---|---|
| Arrows need evidence; unshown ones are dashed; boxes link to files | gitdiagram | `diagram.py`: arrows between real files are checked against the import map |
| Signatures of the files that don't fit | aider, repomix `--compress` | `outline.py` |
| Scan file *contents* for secrets before they reach a model | repomix (Secretlint) | `redact.py` |
| Rank files by how much the rest of the code uses them | aider (PageRank) | scan order by import count |
| Agents call the tool; findings come with evidence and unknowns | REA | `proof scan` + `proof check` + `agents/proof-case-study/SKILL.md` |
| Know what's missing from a README | readme-ai | `proof suggest` checklist |

## What proof left out, on purpose

- **Auto-bidding on job boards** (GigRadar, PouncerAI): mass proposals are what make
  clients ignore pitches, and automation may break a platform's terms.
- **tree-sitter:** a compiled dependency per language; proof keeps to the standard
  library plus `requests` and `markdown`. Worth revisiting if outlines prove too rough.
- **A chat over the repo** (DeepWiki): useful, but not proof's job.
- **An MCP server** (REA, repomix): the CLI and the skill file already work with Claude
  Code, Cursor and Codex, which can all run commands. An MCP server is a possible next
  step for agents that can't.

## Sources

- REA: [github.com/morluto/rea](https://github.com/morluto/rea), [rea.tools](https://rea.tools/),
  [AlternativeTo listing](https://alternativeto.net/software/rea-reverse-engineer-anything/about/),
  [fake-copy warning](https://pasqualepillitteri.it/en/news/23845/rea-reverse-engineer-anything-github-true-false)
- [gitdiagram](https://github.com/ahmedkhaleel2004/gitdiagram) (prompts in `src/server/generate/prompts.ts`)
- [aider repo map](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py)
- [repomix](https://github.com/yamadashy/repomix), [gitingest](https://github.com/coderamp-labs/gitingest),
  [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open), [readme-ai](https://github.com/eli64s/readme-ai)
- Portfolio tools: [Foliox](https://www.scriptbyai.com/github-profile-generator-foliox),
  [GitFolio](https://awesome.ecosyste.ms/projects/github.com%2Fdefremont%2Fgitfolio),
  [GitHired review](https://aiindigo.com/blog/githired-review-2026-turning-code-commits-into-career-opportunities),
  [PortGen](https://hunted.space/product/portgen), [devb.io overview](https://dev.to/bharathlakkoju/stop-building-portfolios-manually-generate-them-from-your-github-50of)
- Proposal tools: [Fueler's list](https://www.fueler.io/blog/best-ai-proposal-generators-for-upwork-freelancers),
  [GigRadar](https://gigradar.io/blog/upwork-proposal-generator),
  [Upwex](https://www.toolbit.ai/ai-tool/upwex-io)
