# Examples: real output for two of Maukthik's projects

| File | What it is |
|---|---|
| `doppel/case_study.md` | Case study for [doppel](https://github.com/Maukthik/doppel), a Python GitHub Action |
| `client-desk/case_study.md` | Case study for [client-desk](https://github.com/Maukthik/client-desk), a Next.js + Stripe app |
| `client-desk/facts.md` | The facts file `proof` started for its 2 `[add: ...]` gaps (not filled in yet) |
| `pitch/sample_job.txt` → `pitch/sample_pitch.md` | A sample job post and the pitch `proof pitch` wrote for it |
| `profile.md` | `proof profile`: Upwork/LinkedIn text and resume bullets from both case studies |
| `portfolio.html`, `portfolio-preview.png` | `proof site` with both projects |
| `doppel/sample_pitch.txt` | An earlier hand-written pitch, kept for comparison |

**How they were made:** no LLM could be run where these were built, so Claude wrote each reply
by hand from the exact prompt `proof` produced (`proof case --dry-run` shows it), following
`proof/prompts.py`. Everything else is the real pipeline: the scan, project matching
(ClientDesk 33.0, Doppel 0.5 for the sample job, so only ClientDesk was used), reply cleanup,
the facts file, the format and claim checks (no unsupported numbers), the pitch lint
(which caught "role-based access" and "automated tests" missing from the first draft), and
the portfolio page.

They show what good output looks like. Output from a small local model will be rougher; compare
against these when tuning the prompts.
