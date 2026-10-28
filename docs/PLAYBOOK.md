# The proof playbook: getting the most out of it

Commands are for PowerShell on Windows, run in `D:\MyAIProjects\proof`. On Mac/Linux, or
after adding Python's Scripts folder to PATH, type `proof` instead of `py -m proof`.

---

## Part 1 - The newer features, in plain words

### Claim links: every result points to its proof
Each line in a case study's **Results** gets a `[source]` link to the exact README line it
came from, pinned to the commit proof read - so the link stays right after you change the
README. Numbers from your `facts.md` are marked **(self-reported)**. A number with no real
source gets no link, so nothing made-up can look verified.
*Needs:* the repo on GitHub (a local folder must have a GitHub `origin` remote). Commits you
haven't pushed yet are linked to the latest version instead.

### Diagram checks: arrows must be real
The model draws the architecture diagram; proof then checks every arrow between two real
files against the code's imports. An arrow the code doesn't show is redrawn **dashed** (it
may still be true - an HTTP call, a documented flow - but it's marked as unproven). Boxes
naming real files become **clickable** on the portfolio page, opening that file on GitHub.

### Secret removal: keys never reach a model
Before anything is sent to a model, keys and passwords written into the code are removed
(OpenAI, Anthropic, AWS, GitHub, Stripe, Slack, Google, Groq, Hugging Face, private keys,
hardcoded passwords, passwords in database URLs). proof prints `SECRET <file>` so you can
move it to `.env` and rotate it - if it's in the repo, it's public.

### Outlines: the model sees more of your code
Files that don't fit in the model's budget now appear as their signatures (classes,
functions, types) instead of one line each. Your 8B model sees the shape of 2-4x more files.

### Repair round
After the first draft, proof's checks run; if they find problems, the model gets the list
and one chance to fix them. The version with fewer problems is kept.

### `proof suggest`: what to build next
A checklist of what clients look for (README, Results section, screenshot, live demo,
quick start, tests, CI, deploy setup, `.env.example`, license, unfilled facts), the
technologies jobs you pitched asked for that this project doesn't show, and 3-5 concrete
feature ideas - each written as a task you can paste into a coding assistant.

### `proof eval`: a report card
Writes a case study for each repo with each model, runs the checks, and prints problems
before/after repair, by kind, with time taken - compared with your previous eval. Use it to
pick a model and to test any change to the prompts.

### `proof dataset` + `training\`: fine-tune your own model
Collects trusted examples (exact prompt + a case study that passed every check or that you
fixed by hand) into training data, and `training\README.md` walks through training on a
free Kaggle GPU and loading the result into Ollama. *The training script hasn't been run yet.*

### Agent mode: `proof scan` + `proof check`
Let a strong coding agent (Claude Code, Cursor, Codex) write case studies, with proof
supplying the facts and the checks:
- `proof scan <repo> --prompt` prints exactly what a model would see (secrets removed)
- `proof check <file> --repo <repo>` runs every check on any case study; `--save` adds the
  links and diagram check and files it with your others
- `agents\proof-case-study\SKILL.md` teaches the agent the routine

### `proof apply`: jobs come to you
Reads public job boards - Remotive, Remote OK, We Work Remotely, and the monthly Hacker
News "Seeking freelancer" thread (add `hn` for "Who is hiring", or any RSS feed URL) - and
lists only the **new** jobs that fit your projects: best first, which project fits and
why, and what the job asks for that you don't show yet. It drafts pitches for the top 3.
It never sends anything: you read, fix and send each one yourself. Upwork has no feed
any more and LinkedIn needs a login, so copy those posts into `proof pitch -`.

### `proof followup`: one well-timed nudge
`proof log` lists pitches sent 4+ days ago with no reply. `proof followup <pitch>` drafts
a short follow-up that adds one *new* detail from your project (not "just checking in").
After a follow-up, 10+ days of silence means let it go.

### `proof prep`: ready for the call
When a client wants to talk: `proof prep <pitch>` writes a one-page brief - the questions
they'll likely ask with answers from your real projects (naming files), the technologies
they want that you don't show and an honest way to answer, questions to ask them, and a
30-second intro. Notes you logged ("asked about Kubernetes") count too.

### Small conveniences
- `"@file.txt"` anywhere repos go: a list of repos, one per line, `#` for comments
  (keep the quotes in PowerShell).
- `--scan-chars N`: how much of each repo the model sees.

---

## Part 2 - Set up once

```powershell
git pull                                    # get the latest proof
py -m pip install -e .                      # only needed once (already done)
ollama list                                 # which local models you have
```

For each new PowerShell window, pick the model (or pass `--provider` / `--model` each time):

```powershell
$env:PROOF_PROVIDER="ollama"; $env:PROOF_MODEL="llama3.1:8b-instruct-q4_K_M"
```

Then check everything works - Python, git, the model (it sends one test prompt), every
job board, your case studies and pitch log:
```powershell
py -m proof doctor
```
Every line is `ok`, `warn` or `FAIL` with the fix next to it. If something's wrong that
you can't fix, paste the whole output when asking for help.

---

## Part 3 - Choose how case studies get written

| Way | Quality | Cost | How |
|---|---|---|---|
| **A. Local model** | OK; the checks and repair catch most mistakes | free | `py -m proof case <repo>` |
| **B. Big free cloud model** | better | free tier, rate-limited | Groq or OpenRouter: `--provider openai --model <id>` |
| **C. Coding agent** | best | your agent subscription | agent mode (below) |
| **D. You write it** | yours | your time | `py -m proof check draft.md --repo <repo> --save` |

**B, with Groq** (free key at console.groq.com):
```powershell
$env:OPENAI_BASE_URL="https://api.groq.com/openai/v1"; $env:OPENAI_API_KEY="<key>"
py -m proof case D:\MyAIProjects\doppel --provider openai --model llama-3.3-70b-versatile --force
```

**C, with Claude Code:** copy `agents\proof-case-study` to `%USERPROFILE%\.claude\skills\`,
then ask: *"Write a case study for D:\MyAIProjects\doppel with the proof-case-study skill."*
It runs `scan`, writes, runs `check` until it passes, and saves with `--save`.

You can mix them: draft with A, then let the agent or you improve it and `check --save`.

---

## Part 4 - The full workflow, start to finish

### Step 1. Make your projects easy to prove
```powershell
py -m proof suggest D:\MyAIProjects\client-desk --no-ai     # instant checklist
py -m proof suggest D:\MyAIProjects\client-desk             # + ideas and tasks
```
Open `proof_output\client-desk\suggestions.md`. Do the cheap checklist items first - they
change how a client sees the project the most:
- a **`## Results`** section in the README with real numbers (case studies quote it and
  link to it - this single section powers the claim links)
- a screenshot or GIF, and a live demo or 1-minute video link
- a quick-start section, tests, CI, a license

Bigger ideas come as tasks: paste one into Claude Code or Cursor, review, push.

### Step 2. Write the case studies
```powershell
py -m proof case D:\MyAIProjects\doppel D:\MyAIProjects\client-desk https://github.com/Maukthik/codefork
```
Read what it prints:
- `checks found N problem(s) - asking the model to fix them` - the repair round ran
- `WARN ...` - problems still left (fix table in Part 5)
- `SECRET <file>` - remove that key from the repo and rotate it
- `N diagram arrow(s) ... drawn dashed` - fine; the diagram is honest about them
- `started facts.md` - the gaps it couldn't prove

### Step 3. Close the gaps with real facts
Open `proof_output\<repo>\facts.md`. Each empty line is a gap. Fill in what's true
(numbers, users, a client's words, a demo link), delete what isn't, then:
```powershell
py -m proof case D:\MyAIProjects\doppel          # notices the new facts and rewrites
```
Want to tweak wording yourself? Edit `case_study.md` directly - proof never overwrites your
edits (new versions go to `case_study.new.md`). After editing, check it:
```powershell
py -m proof check proof_output\doppel\case_study.md --repo D:\MyAIProjects\doppel
```

### Step 4. Publish the portfolio
```powershell
py -m proof site --owner "Maukthik J" --contact "github.com/Maukthik"
start proof_output\site\index.html
```
Yellow highlights = gaps still open. For a page that updates itself on every push, follow
the setup notes at the top of `templates\portfolio-workflow.yml` (a `portfolio` repo with a
`repos.txt`, GitHub Pages on) and add `templates\ping-portfolio.yml` to each project.

### Step 5. Profiles
```powershell
py -m proof profile
```
Paste `proof_output\profile.md` into your Upwork overview, LinkedIn About and resume.
`--only doppel client-desk` to choose the projects.

### Step 6. Find jobs and pitch
Each morning (or every few days):
```powershell
py -m proof apply                     # new jobs that fit + pitch drafts for the top 3
py -m proof apply --no-ai             # just the list, instantly
py -m proof apply hn --days 7         # add HN "Who is hiring", last week only
```
It prints the fits (also saved to `proof_output\jobs\<date>.md`) and the drafts it wrote
in `proof_output\pitches\`. Next time it shows only jobs you haven't seen.

For a job you found yourself (Upwork, LinkedIn, a client's email), save the text, then:
```powershell
py -m proof pitch job.txt            # or a job URL, or - to paste
```
Either way: open the draft, fix anything flagged, make it sound like you, send it, then:
```powershell
py -m proof log job sent
```
Check a pitch you wrote yourself: `py -m proof lint my_pitch.txt --job job.txt`.

### Step 7. Follow up, prepare, learn what wins
```powershell
py -m proof log                       # pitches, reply rates, and what to do next
```
- **"Due a follow-up"** (sent 4+ days ago, no reply):
  ```powershell
  py -m proof followup job            # one short nudge with something new
  py -m proof log job followed-up     # after you send it
  ```
- **They replied:**
  ```powershell
  py -m proof log job replied --note "wants a call Friday, asked about Docker"
  py -m proof prep job                # read proof_output\prep\job.md before the call
  ```
- **Won it:** `py -m proof log job won`. **Silence 10+ days after the follow-up:**
  `py -m proof log job ignored`.

After ~10 sent pitches, `proof log` shows which projects and skills get answers. Re-run
`py -m proof suggest <repo>`: its "what clients asked for" section lists the technologies
those jobs wanted that the project doesn't show yet - that's your next feature. The
"missing:" lines from `proof apply` point the same way.

### Step 8. Improve the AI (when you want better drafts)
```powershell
# baseline: how good is each model on your repos?
py -m proof eval D:\MyAIProjects\doppel https://github.com/Maukthik/client-desk --models llama3.1:8b-instruct-q4_K_M qwen3:4b-thinking
```
Use the model with the fewest problems after repair. When you have 50+ trusted examples
(case studies that passed every check, ones you fixed by hand, a big free model's runs on
`training\repos.txt`), follow `training\README.md` to fine-tune, then eval old vs new.

---

## Part 5 - What the warnings mean, and the fix

| Warning | Meaning | Fix |
|---|---|---|
| `files that aren't in the repo` | the model named a file that doesn't exist | rerun (repair usually fixes it), or edit the case study |
| `numbers not found in the repo or your facts` | a number with no source | put the real number in `facts.md`, or delete it |
| `Results numbers the README and your facts don't state` | a result that isn't written down anywhere | add it to the README's Results section or `facts.md` |
| `meaning may be turned around` | e.g. "didn't run" became "caught" | rewrite that line with the repo's own wording |
| `copied from the prompt` | the model pasted the instructions | rerun, or try another model |
| `technologies the repo never mentions` | a skill the code doesn't show | remove it |
| `Engineering highlights name no real file` | vague highlights | rerun, or name the files that do the hard parts |
| `filler phrases` | "seamless", "daunting" ... | say something specific |
| `missing sections` / `no Mermaid diagram` | the format broke | rerun with `--force` |
| `gives them no reason to reply` (followup) | "just checking in" | lead with a new detail from the project |
| `Repeats your first message` (followup) | same sentences again | say something the pitch didn't |
| `Files your case studies don't mention` (prep) | the brief names a file you may not have | check it before the call |
| `WARN remotive: couldn't reach ...` (apply) | a board is down or blocked | the others still run; try later |

---

## Part 6 - Tips

- **Your README is the main source.** Results, numbers and links in the README flow into
  case studies, claim links and pitches. Improving the README improves everything.
- **See what the model sees:** `py -m proof scan D:\MyAIProjects\doppel` - if something
  important is missing there, the case study can't mention it.
- **Re-run freely:** unchanged repos are skipped; `--force` rewrites.
- **Keep your own repos out of training data** (`--exclude` in `proof dataset`), so evals
  on them stay honest.
- **Quote `"@list.txt"`** in PowerShell; `@` on its own means something else there.

## Troubleshooting

Start with `py -m proof doctor`: it checks all of the below in one go.

| Problem | Fix |
|---|---|
| `python` fails with "No application is associated" | use `py` (Cygwin's python is first on your PATH) |
| `Ollama doesn't have the model` | `ollama list`, then `--model <one of those>` |
| `Can't reach Ollama` | start the Ollama app, or `ollama serve` |
| `LLM API busy, retrying` | free tiers limit requests per minute; proof waits and retries |
| `Not a folder` | check the path, or use the GitHub URL |
| `skipped: no code and no real README` | push some code first (or `--force`) |
| `apply` finds nothing new | boards are re-read every 6h: `--refresh`; `--all` to see old fits; `--min-tech 1` to loosen |
