---
name: proof-case-study
description: Write a client-facing case study for a code repository with the `proof` CLI, using proof's repo scan as the source of facts and `proof check` as the gate before saving. Use when asked to write a case study, portfolio entry or project write-up for a repo.
---

# Writing a case study with proof

`proof` reads the repo and checks the result; you write. Every claim must be traceable
to the repo or to the developer's facts file - clients will click the source links.

On Windows, run `py -m proof` wherever this says `proof`.

1. **Get the material.** Run `proof scan <repo> --prompt` and read all of it: the repo
   scan (stack, git history, how files connect, key files, outlines), the developer's
   facts, and at the end the exact format and rules. You may open files in the repo to
   understand them better.

2. **Write** the case study to `case_study_draft.md` in exactly that format:
   - Name real files and functions (the paths in the scan).
   - Every number in Results must be stated in the README or the facts, with the same
     meaning. Missing facts become `[add: what's missing]` - never estimate.
   - Diagram arrows should follow "How the files connect"; others will be drawn dashed.

3. **Check** with `proof check case_study_draft.md --repo <repo>`. Fix every `WARN` and
   check again, until it prints "no problems found" (exit code 0). If a warning can't be
   fixed honestly, replace the claim with an `[add: ...]` placeholder.

4. **Save** with `proof check case_study_draft.md --repo <repo> --save`. This adds links
   from each result to its README line, checks the diagram against the imports, and
   saves it to `proof_output/<repo>/` where `proof pitch`, `proof profile` and `proof site`
   use it.

5. **Report** the `[add: ...]` gaps left: the developer fills them in
   `proof_output/<repo>/facts.md`, then you (or `proof case`) can update the case study.

## Install

- Claude Code: copy this folder to `~/.claude/skills/proof-case-study/`
  (or `.claude/skills/` in a project).
- Other agents (Cursor, Codex, Gemini CLI ...): paste this file into their rules or
  instructions.
