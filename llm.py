"""
llm.py - send a prompt to an LLM and get text back.

Providers:
  anthropic -> needs ANTHROPIC_API_KEY
  ollama    -> free, local (ollama serve). OLLAMA_URL to change the address.
  openai    -> any OpenAI-compatible API (OpenRouter, Groq, Gemini, LM Studio)
               needs OPENAI_BASE_URL, and OPENAI_API_KEY if the service wants one
  mock      -> no LLM at all; fills a template. For testing the pipeline offline.
"""

import os
import re
import sys

import requests

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",   # change if this model name is retired
    "ollama": "qwen2.5-coder:7b",       # fits in ~6GB VRAM
    "openai": "",                       # must be given with --model / PROOF_MODEL
    "mock": "mock",
}


def ask_llm(prompt, provider, model):
    """Send one prompt, get back the reply text."""
    if provider == "mock":
        return mock_reply(prompt)

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("Set ANTHROPIC_API_KEY first.")
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 3000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=300,
        )
        check(response)
        return response.json()["content"][0]["text"]

    if provider == "ollama":
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        try:
            response = requests.post(
                f"{url}/api/chat",
                json={"model": model, "stream": False,
                      "messages": [{"role": "user", "content": prompt}],
                      "options": {"num_ctx": 16384}},   # repo scans are long
                timeout=900,
            )
        except requests.ConnectionError:
            sys.exit(f"Can't reach Ollama at {url}. Is `ollama serve` running?")
        check(response)
        return response.json()["message"]["content"]

    if provider == "openai":
        base = os.environ.get("OPENAI_BASE_URL") or sys.exit(
            "Set OPENAI_BASE_URL (e.g. https://openrouter.ai/api/v1).")
        key = os.environ.get("OPENAI_API_KEY", "none")
        response = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=300,
        )
        check(response)
        return response.json()["choices"][0]["message"]["content"]

    sys.exit(f"Unknown provider: {provider}")


def check(response):
    """Stop with a readable error if the API call failed."""
    if response.status_code != 200:
        sys.exit(f"LLM API error {response.status_code}:\n{response.text[:1000]}")


def strip_wrapper(text):
    """Some models wrap the whole answer in ```markdown ... ``` - remove that."""
    text = text.strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


# ---------------------------------------------------------------------------
# Mock provider: builds plausible output from the prompt itself
# ---------------------------------------------------------------------------

def mock_reply(prompt):
    if "Repository scan:" in prompt:
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
  U["User"] --> A["{name}"] --> D["Data"]
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
    # Pitch: mention the first project's title
    title = re.search(r"^# (.+)$", prompt, flags=re.MULTILINE)
    project = title.group(1).split(" - ")[0] if title else "my project"
    return (f"You need this built reliably. In {project} I built something very close "
            f"to it. Could we do a 15-minute call this week to go over your setup?")
