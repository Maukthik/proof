"""
llm.py - send a prompt to an LLM and get text back, then tidy what comes back.

Providers:
  anthropic -> needs ANTHROPIC_API_KEY
  ollama    -> free, local (ollama serve). OLLAMA_URL to change the address,
               OLLAMA_NUM_CTX for the context window (default 16384 tokens).
  openai    -> any OpenAI-compatible API (OpenRouter, Groq, Gemini, LM Studio)
               needs OPENAI_BASE_URL, and OPENAI_API_KEY if the service wants one
  mock      -> no LLM at all; fills a template. For testing the pipeline offline.
"""

import os
import re
import sys
import time

import requests

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",   # change if this model name is retired
    "ollama": "qwen2.5-coder:7b",       # fits in ~6GB VRAM
    "openai": "",                       # must be given with --model / PROOF_MODEL
    "mock": "mock",
}
TEMPERATURE = 0.3     # low: we want facts from the code, not creative writing
RETRY_WAITS = [5, 20, 60]   # seconds; free API tiers often answer 429 "slow down"


def ollama_num_ctx():
    return int(os.environ.get("OLLAMA_NUM_CTX", "16384"))


def scan_budget(provider):
    """How many characters of repo scan to send.
    Ollama silently drops the *start* of a prompt that doesn't fit its context window,
    so the scan must fit with room to spare: ~3 characters per token, minus ~5000
    tokens for the instructions and the reply. Cloud models have far bigger windows."""
    if provider == "ollama":
        return (ollama_num_ctx() - 5000) * 3
    return 70_000


def ask_llm(prompt, provider, model):
    """Send one prompt, get back the reply text."""
    if provider == "mock":
        return mock_reply(prompt)

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("Set ANTHROPIC_API_KEY first.")
        response = post("https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                        body={"model": model, "max_tokens": 3000, "temperature": TEMPERATURE,
                              "messages": [{"role": "user", "content": prompt}]},
                        timeout=300)
        return response.json()["content"][0]["text"]

    if provider == "ollama":
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        response = post(f"{url}/api/chat",
                        body={"model": model, "stream": False,
                              "messages": [{"role": "user", "content": prompt}],
                              "options": {"num_ctx": ollama_num_ctx(),
                                          "temperature": TEMPERATURE}},
                        timeout=900,
                        not_running=f"Can't reach Ollama at {url}. Is `ollama serve` running?",
                        not_found=f"Ollama doesn't have the model '{model}'. Run `ollama list` "
                                  f"and pick one with --model, or `ollama pull {model}`.")
        return response.json()["message"]["content"]

    if provider == "openai":
        base = os.environ.get("OPENAI_BASE_URL") or sys.exit(
            "Set OPENAI_BASE_URL (e.g. https://openrouter.ai/api/v1).")
        key = os.environ.get("OPENAI_API_KEY", "none")
        response = post(f"{base.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        body={"model": model, "temperature": TEMPERATURE,
                              "messages": [{"role": "user", "content": prompt}]},
                        timeout=300)
        return response.json()["choices"][0]["message"]["content"]

    sys.exit(f"Unknown provider: {provider}")


def post(url, body, headers=None, timeout=300, not_running=None, not_found=None):
    """POST JSON. Waits and retries on rate limits / server hiccups; stops with a
    readable error on anything else (`not_running`, `not_found`: friendlier wording)."""
    for wait in RETRY_WAITS + [None]:
        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.ConnectionError:
            sys.exit(not_running or f"Can't connect to {url}.")
        if response.status_code == 200:
            return response
        if response.status_code in (429, 500, 502, 503, 529) and wait is not None:
            print(f"  LLM API busy ({response.status_code}), retrying in {wait}s ...")
            time.sleep(wait)
            continue
        if response.status_code == 404 and not_found:
            sys.exit(not_found)
        sys.exit(f"LLM API error {response.status_code}:\n{response.text[:1000]}")


# ---------------------------------------------------------------------------
# Tidying model output (small models get the format slightly wrong)
# ---------------------------------------------------------------------------

def strip_wrapper(text):
    """Remove what models put around the answer: a <think>...</think> block (reasoning
    models like qwen3 and deepseek-r1), "Here's your case study:" before it, or a
    ```markdown fence around all of it."""
    if "</think>" in text:                  # sometimes the opening <think> is left out
        text = text.split("</think>")[-1]
    text = text.strip()
    # [^#]* = only chatter before the fence, no heading: the fence wraps the whole answer
    match = re.match(r"[^#]*?```(?:markdown|md)\s*\n(.*)\n```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.fullmatch(r"```\s*\n(.*)\n```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


def drop_preamble(text):
    """Case studies start with the '# ' title. Drop any chatter before it."""
    match = re.search(r"^# ", text, flags=re.MULTILINE)
    return text[match.start():] if match else text


def fix_mermaid(text):
    """Quote Mermaid box labels. A["Server (FastAPI)"] works, A[Server (FastAPI)] is a
    syntax error and the diagram won't draw - the most common mistake models make.
    Only plain [label] boxes are touched; other shapes like [(db)] or [[x]] start with
    a bracket and are left alone."""
    def fix_block(match):
        block = match.group(0)
        block = re.sub(r"(\b\w+)\[(?![(\[/\\\"])([^\]\"]*)\]",
                       lambda m: f'{m.group(1)}["{m.group(2).strip()}"]', block)
        # Edge labels: -->|reads (cached)| also breaks on brackets
        block = re.sub(r"\|([^|\"]*[()\[\]{}][^|\"]*)\|", r'|"\1"|', block)
        return block
    return re.sub(r"```mermaid\n.*?```", fix_block, text, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Mock provider: builds plausible output from the prompt itself
# ---------------------------------------------------------------------------

def mock_reply(prompt):
    if "=== CHECKLIST ===" in prompt:
        return mock_suggestions(prompt)
    if "=== REPOSITORY SCAN ===" in prompt:
        return mock_case_study(prompt)
    if "Task: write a short follow-up" in prompt:
        return ("One more thing that fits your project: (mock) a detail the first message "
                "didn't use. Would a short call on Thursday work?")
    if "Task: write a one-page brief" in prompt:
        return mock_prep(prompt)
    if "Resume bullets" in prompt:
        names = re.findall(r"^--- PROJECT: (.+) ---$", prompt, flags=re.MULTILINE)
        bullets = "\n".join(f"### {n}\n- Built {n}." for n in names)
        return ("## Headline\nDeveloper (mock profile)\n## About\nI build software. "
                f"See {', '.join(names)}.\n## Skills\nPython\n## Resume bullets\n{bullets}")
    # Pitch: mention the first project's title
    title = re.search(r"^# (.+)$", prompt, flags=re.MULTILINE)
    project = title.group(1).split(" - ")[0] if title else "my project"
    return (f"You need this built reliably. In {project} I built something very close "
            f"to it. Could we do a 15-minute call this week to go over your setup?")


def mock_prep(prompt):
    gaps = re.search(r"=== NOT SHOWN IN ANY PROJECT ===\n(.*?)\n===", prompt, flags=re.DOTALL)
    gap_lines = [f"- {g.strip()}: (mock) how I'd get up to speed" for g in
                 gaps.group(1).split(",") if g.strip() and g.strip() != "(none)"] if gaps else []
    return ("## What they need\n- (mock) what the post asks for\n"
            "## Questions they'll likely ask\n### Have you built this before?\n"
            "(mock) Yes - see my projects.\n"
            "## Gaps to be ready for\n" + ("\n".join(gap_lines) or "None.") + "\n"
            "## Questions to ask them\n- Who will use it?\n"
            "## 30-second intro\n(mock) I build software like this.")


def mock_suggestions(prompt):
    """One idea, about the first file the scan shows."""
    shown = re.search(r"^# File: (.+)$", prompt, flags=re.MULTILINE)
    where = shown.group(1) if shown else "README.md"
    return (f"### Add a usage example\n- What: (mock) show how to use {where}.\n"
            f"- Why a client cares: they see it working.\n"
            f"- Where: {where}, examples/demo.md (new)\n"
            f"- Size: small (hours)\n- Done when: the example runs.\n")


def mock_case_study(prompt):
    name = re.search(r"# Repo name: (.+)", prompt).group(1).strip()
    stack = re.search(r"# Detected stack: (.+)", prompt).group(1).strip()
    return f"""# {name} - (mock) project summary
## The problem
[add: who has this problem]
## What I built
A project called {name}.
## How it works
```mermaid
flowchart TD
{mock_diagram(prompt, name)}
```
## Tech stack
- {stack}
## Engineering highlights
- [add: hardest part]
## Results
- [add: response time / users / accuracy]
## Skills shown
{stack}
"""


def mock_diagram(prompt, name):
    """Draw the first few real import links from the scan, so the mock still shows
    the project's actual structure."""
    links = re.search(r"# How the files connect.*?\n(.*?)(?:\n\n|\Z)", prompt, flags=re.DOTALL)
    edges = []
    for line in (links.group(1).splitlines() if links else []):
        if " -> " in line:
            source, targets = line.split(" -> ", 1)
            edges += [(source, target) for target in targets.split(", ")]
    if not edges:
        return f'  U["User"] --> A["{name}"] --> D["Data"]'
    ids = {}
    lines = []
    for source, target in edges[:8]:
        for path in (source, target):
            ids.setdefault(path, f"N{len(ids)}")
        lines.append(f'  {ids[source]}["{source}"] --> {ids[target]}["{target}"]')
    return "\n".join(lines)
