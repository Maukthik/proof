"""
Tests for the proof tool. Run from the proof folder:   python -m pytest -q
No LLM or internet needed - uses the mock provider and a tiny fake HTTP server.
"""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

TOOL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL))

from proof import llm                                 # noqa: E402
from proof.lint import lint_pitch                      # noqa: E402
from proof.match import rank_projects                  # noqa: E402
from proof.portfolio import build_site                 # noqa: E402
from proof.scan import detect_stack, scan_repo         # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_repo(root, name, files):
    """Create a git repo with the given {path: content} files and one commit."""
    repo = root / name
    for path, content in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(content)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,  # noqa: E731
                                    capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "init")
    return repo


def commit_change(repo):
    (repo / "CHANGE.txt").write_text(str(time.time_ns()))      # always a real change
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "change"], check=True)


def run(*args, cwd, stdin=None):
    """Run the CLI (as `python -m proof`) and return (exit code, output)."""
    env = {**os.environ, "PYTHONPATH": str(TOOL)}
    env.pop("PROOF_PROVIDER", None)
    result = subprocess.run([sys.executable, "-m", "proof", *args], cwd=cwd, env=env,
                            input=stdin, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


RAG_FILES = {
    "README.md": "# RAG bot\nAnswers questions over PDFs.",
    "requirements.txt": "fastapi>=0.110  # web\nlangchain==0.2\nchromadb\n-e .\n",
    "Dockerfile": "FROM python:3.12\n",
    ".github/workflows/ci.yml": "on: push\n",
    "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
    "node_modules/pkg/index.ts": "should be ignored",
}
SHOP_FILES = {
    "README.md": "# Shop\nAn online store frontend.",
    "package.json": json.dumps({"dependencies": {"react": "18"},
                                "devDependencies": {"tailwindcss": "3"}}),
    "src/App.jsx": "export default function App() { return null }",
}


@pytest.fixture
def repos(tmp_path):
    return {"rag": make_repo(tmp_path, "rag-bot", RAG_FILES),
            "shop": make_repo(tmp_path, "shop-ui", SHOP_FILES)}


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def test_detect_stack_python(repos):
    assert detect_stack(repos["rag"]) == [
        "Chroma", "Docker", "FastAPI", "GitHub Actions", "LangChain", "Python"]


def test_detect_stack_js_and_skips_node_modules(repos):
    assert set(detect_stack(repos["shop"])) == {"JavaScript", "React", "Tailwind"}
    assert "TypeScript" not in detect_stack(repos["rag"])   # file was inside node_modules


def test_notebook_repo(tmp_path):
    notebook = json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# Indexing\n"]},
        {"cell_type": "code", "source": ["from langchain_openai import OpenAIEmbeddings\n",
                                         "import sklearn.metrics\n"],
         "outputs": [{"text": "HUGE OUTPUT"}]},
    ]})
    repo = make_repo(tmp_path, "nb-only", {"rag.ipynb": notebook,
                                           "util.py": "import cv2\nfrom torch import nn\n"})
    assert set(detect_stack(repo)) == {"Jupyter", "Python", "LangChain", "scikit-learn",
                                       "OpenCV", "PyTorch"}
    text = scan_repo(repo)
    assert "[code cell]" in text and "OpenAIEmbeddings" in text
    assert "HUGE OUTPUT" not in text


def test_side_folders_and_dev_deps_dont_count(tmp_path):
    pyproject = """[project]
name = "tool"
dependencies = ["pyyaml>=6", "openai>=1"]
[project.optional-dependencies]
dev = ["pytest>=8", "flask>=3", "django>=5"]
"""
    files = {"pyproject.toml": pyproject,
             "src/tool/cli.py": "import yaml\n",
             "tests/test_x.py": "import flask\n",
             "bench/apps/a/requirements.txt": "fastapi\n",
             "bench/apps/a/app.py": "from fastapi import FastAPI\n"}
    files.update({f"bench/case{i}.py": "x = 1\n" for i in range(50)})
    repo = make_repo(tmp_path, "tool", files)
    assert detect_stack(repo) == ["OpenAI SDK", "Python"]

    text = scan_repo(repo)
    assert text.index("# File: src/tool/cli.py") < text.index("# File: bench/")
    assert "bench/  (52 files" in text and "bench/case7.py" not in text.split("# File:")[0]


def test_all_code_in_side_folder_still_detected(tmp_path):
    repo = make_repo(tmp_path, "nbs", {"examples/demo.py": "import torch\n"})
    assert "PyTorch" in detect_stack(repo)


def test_long_readme_keeps_results_section(tmp_path):
    readme = ("# Tool\nIntro.\n" + "## Usage\n" + "blah " * 3000 +
              "\n## Results\nCaught 17/20 regressions.\n## License\nMIT " + "x " * 2000)
    repo = make_repo(tmp_path, "tool", {"README.md": readme, "main.py": "print(1)\n"})
    text = scan_repo(repo)
    assert "Caught 17/20 regressions." in text
    assert "## License" not in text


def test_dry_run_ignores_cache(repos, tmp_path):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    code, out = run("case", str(repos["rag"]), "--dry-run", cwd=tmp_path)
    assert "dry run" in out


def test_scan_contents(repos):
    text = scan_repo(repos["rag"])
    assert "# Repo name: rag-bot" in text
    assert "1 commit," in text
    assert "node_modules" not in text
    assert text.index("README.md\n```") < text.index("app/main.py\n```")  # README first


# ---------------------------------------------------------------------------
# case command + caching
# ---------------------------------------------------------------------------

def test_case_creates_files_and_caches(repos, tmp_path):
    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    folder = tmp_path / "proof_output" / "rag-bot"
    assert (folder / "case_study.md").read_text().startswith("# rag-bot")
    meta = json.loads((folder / "meta.json").read_text())
    assert "FastAPI" in meta["stack"] and len(meta["commit"]) == 40
    assert "gaps to fill" in out

    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert "up to date" in out

    commit_change(repos["rag"])
    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert "writing case study" in out

    code, out = run("case", str(repos["rag"]), "--provider", "mock", "--force", cwd=tmp_path)
    assert "writing case study" in out


def test_case_multiple_repos_and_dry_run(repos, tmp_path):
    code, out = run("case", str(repos["rag"]), str(repos["shop"]), "--dry-run", cwd=tmp_path)
    assert code == 0, out
    for name in ("rag-bot", "shop-ui"):
        assert (tmp_path / "proof_output" / name / "prompt.txt").exists()
        assert not (tmp_path / "proof_output" / name / "case_study.md").exists()


def test_bad_folder_gives_clear_error(tmp_path):
    code, out = run("case", "does-not-exist", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "Not a folder" in out


# ---------------------------------------------------------------------------
# matching, pitch, lint
# ---------------------------------------------------------------------------

def test_ranking_prefers_relevant_project():
    projects = [{"name": "shop", "text": "React Tailwind online store frontend"},
                {"name": "rag", "text": "FastAPI LangChain RAG chatbot over PDFs, Docker"}]
    job = "Need a Python dev to build a RAG chatbot with FastAPI, deployed with Docker."
    ranked = rank_projects(job, projects)
    assert ranked[0]["name"] == "rag"
    assert {"fastapi", "rag", "docker"} <= set(ranked[0]["matched"])
    assert ranked[1]["score"] < ranked[0]["score"]


def test_plain_english_words_are_not_tech():
    ranked = rank_projects("We want to go fast and express ideas, next steps.",
                           [{"name": "x", "text": "go express next"}])
    assert ranked[0]["matched"] == []


def test_lint_catches_problems():
    bad = ("Hi, I'm a passionate developer. I cut latency by [add: number]. "
           "Regards, [Your Name]")
    levels = [level for level, _ in lint_pitch(bad, job="Needs AWS and Docker")]
    messages = " ".join(m for _, m in lint_pitch(bad, job="Needs AWS and Docker"))
    assert levels.count("ERROR") == 2
    assert "greeting" in messages and "passionate" in messages
    assert "next step" in messages and "aws" in messages


def test_lint_good_pitch_is_clean():
    good = ("Your support team is drowning in PDF questions. In rag-bot I built a FastAPI "
            "chatbot that answers them from your documents, packaged with Docker. "
            "Could we do a 15-minute call to look at your docs?")
    assert lint_pitch(good, job="FastAPI and Docker chatbot") == []


def test_pitch_end_to_end(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    job = tmp_path / "upwork_rag.txt"
    job.write_text("Looking for a FastAPI developer to build a RAG chatbot with LangChain.")
    code, out = run("pitch", str(job), "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    assert out.index("rag-bot") < out.index("shop-ui")         # ranking order printed
    pitch = (tmp_path / "proof_output" / "pitches" / "upwork_rag.md").read_text()
    assert "rag-bot" in pitch


def test_pitch_without_case_studies(tmp_path):
    (tmp_path / "job.txt").write_text("anything")
    code, out = run("pitch", "job.txt", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "Run `proof case" in out


def test_lint_cli_exit_code(tmp_path):
    (tmp_path / "p.md").write_text("Fixed it in [add: x] days. Want a quick call?")
    code, out = run("lint", "p.md", cwd=tmp_path)
    assert code == 1 and "ERROR" in out


# ---------------------------------------------------------------------------
# portfolio site
# ---------------------------------------------------------------------------

def test_site(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    code, out = run("site", "--owner", "Test <Dev>", cwd=tmp_path)
    assert code == 0, out
    page = (tmp_path / "proof_output" / "site" / "index.html").read_text()
    assert page.count('class="card"') == 2
    assert '<pre class="mermaid">' in page
    assert "<mark>[add:" in page
    assert "Test &lt;Dev&gt;" in page                              # owner is escaped
    assert "WARN" in out                                           # placeholders warned


def test_list_without_blank_line_renders_as_list():
    from proof.portfolio import to_html
    html_out = to_html("On every PR it:\n- runs both versions\n- compares\n\n```\n- not a list\n```")
    assert html_out.count("<li>") == 2


def test_site_without_case_studies(tmp_path):
    with pytest.raises(SystemExit):
        build_site(tmp_path)


# ---------------------------------------------------------------------------
# LLM providers (against a fake local server)
# ---------------------------------------------------------------------------

class FakeAPI(BaseHTTPRequestHandler):
    last_request = None
    busy_once = False

    def do_GET(self):
        page = {"/jobs/fastapi-dev": JOB_PAGE,
                "/login-wall": "<html><body><h1>Please log in</h1></body></html>"}
        self.reply(200, page.get(self.path, "not found").encode(), "text/html")

    def reply(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAPI.last_request = (self.path, dict(self.headers), body)
        if self.path.startswith("/busy-once") and FakeAPI.busy_once:
            FakeAPI.busy_once = False
            return self.reply(429, b'{"error": "slow down"}', "application/json")
        if self.path.endswith("/v1/chat/completions"):
            reply = {"choices": [{"message": {"content": "openai ok"}}]}
        elif self.path == "/api/chat":
            reply = {"message": {"content": "ollama ok"}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_api(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_openai_provider(fake_api, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", fake_api + "/v1/")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    assert llm.ask_llm("hello", "openai", "m1") == "openai ok"
    path, headers, body = FakeAPI.last_request
    assert headers["Authorization"] == "Bearer secret"
    assert body["model"] == "m1" and body["messages"][0]["content"] == "hello"


def test_ollama_provider(fake_api, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", fake_api)
    assert llm.ask_llm("hello", "ollama", "qwen") == "ollama ok"
    assert FakeAPI.last_request[2]["stream"] is False


def test_ollama_not_running(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    with pytest.raises(SystemExit, match="ollama serve"):
        llm.ask_llm("hello", "ollama", "qwen")


def test_strip_wrapper():
    assert llm.strip_wrapper("```markdown\n# Hi\ntext\n```") == "# Hi\ntext"
    assert llm.strip_wrapper("# Hi\n```mermaid\nA\n```") == "# Hi\n```mermaid\nA\n```"


# ---------------------------------------------------------------------------
# GitHub Action template
# ---------------------------------------------------------------------------

def test_workflows_are_valid_yaml():
    wf = yaml.safe_load((TOOL / "templates" / "proof-workflow.yml").read_text())
    steps = wf["jobs"]["case-study"]["steps"]
    assert wf["permissions"]["contents"] == "write"
    assert any("proof case . --out docs/proof" in s.get("run", "") for s in steps)

    wf = yaml.safe_load((TOOL / "templates" / "portfolio-workflow.yml").read_text())
    runs = " ".join(s.get("run", "") for s in wf["jobs"]["build"]["steps"])
    assert "proof case" in runs and "proof site" in runs
    assert wf["permissions"]["pages"] == "write"
    assert "project-pushed" in wf[True]["repository_dispatch"]["types"]   # yaml reads on: as True

    wf = yaml.safe_load((TOOL / "templates" / "ping-portfolio.yml").read_text())
    assert "project-pushed" in wf["jobs"]["ping"]["steps"][0]["run"]


# ---------------------------------------------------------------------------
# What the scan reads (bugs found on real repos)
# ---------------------------------------------------------------------------

def test_loose_tests_and_legacy_code_are_not_main_code(tmp_path):
    repo = make_repo(tmp_path, "agents", {
        "agent_graph.py": "import json\n",
        "test_agent_graph.py": "import flask\n",          # test next to the code
        "legacy/app.py": "import django\n",               # old version, an "entrypoint" name
        "web/src/cart.test.ts": "import x from 'vitest'\n",
    })
    assert "Django" not in detect_stack(repo) and "Flask" not in detect_stack(repo)
    text = scan_repo(repo)
    assert text.index("# File: agent_graph.py") < text.index("# File: legacy/app.py")
    assert text.index("# File: agent_graph.py") < text.index("# File: test_agent_graph.py")
    assert "legacy/  (1 files, not main code)" in text


def test_side_folder_line_names_the_real_folder(tmp_path):
    repo = make_repo(tmp_path, "web", {"prisma/schema.prisma": "model User {\n  id Int @id\n}\n",
                                       "prisma/migrations/1_init/migration.sql": "CREATE TABLE x;",
                                       ".env.example": "STRIPE_SECRET_KEY=\n",
                                       "src/app.ts": "export {}\n"})
    text = scan_repo(repo)
    assert "prisma/migrations/  (1 files, not main code)" in text
    assert "# File: prisma/schema.prisma" in text            # data model is read
    assert "STRIPE_SECRET_KEY" in text                       # .env.example names services


def test_more_stack_names(tmp_path):
    repo = make_repo(tmp_path, "mix", {
        "agent.py": "from google.adk.agents import Agent\nimport sqlite3\n",
        "package.json": json.dumps({"dependencies": {"stripe": "1", "zod": "3",
                                                     "@prisma/client": "6"}}),
    })
    assert {"Google ADK", "SQLite", "Stripe", "Zod", "Prisma"} <= set(detect_stack(repo))


def test_import_map_python_and_js(tmp_path):
    from proof.codemap import describe_imports, internal_imports
    from proof.scan import list_files, read_text
    repo = make_repo(tmp_path, "app", {
        "src/shop/__init__.py": "",
        "src/shop/cli.py": "from shop import orders\nfrom .db import connect\nimport json\n",
        "src/shop/orders.py": "from . import db\n",
        "src/shop/db.py": "import sqlite3\n",
        "web/src/app/page.tsx": 'import { db } from "@/lib/db";\nimport "./globals.css";\n',
        "web/src/app/globals.css": "body {}",
        "web/src/lib/db.ts": 'import x from "../util";\n',
        "web/src/util/index.ts": "export default 1\n",
    })
    edges = internal_imports(repo, list_files(repo), read_text)
    assert ("src/shop/cli.py", "src/shop/orders.py") in edges
    assert ("src/shop/cli.py", "src/shop/db.py") in edges
    assert ("src/shop/orders.py", "src/shop/db.py") in edges
    assert ("web/src/lib/db.ts", "web/src/util/index.ts") in edges
    assert not any(target.endswith(".css") for _, target in edges)
    assert "src/shop/cli.py -> " in describe_imports(edges)
    assert "# How the files connect" in scan_repo(repo)


def test_import_map_groups_big_projects_by_folder():
    from proof.codemap import MAX_EDGES, describe_imports
    edges = [(f"src/app/page{i}.tsx", f"src/lib/util{i % 50}.ts") for i in range(MAX_EDGES + 50)]
    text = describe_imports(sorted(edges))
    assert text.startswith("(grouped by folder)") and "src/app/ -> src/lib/" in text


def test_most_imported_modules_are_read_first(tmp_path):
    files = {f"src/pkg/m{i}.py": "from pkg import core\n" for i in range(5)}
    files["src/pkg/aaa.py"] = "x = 1\n"
    files["src/pkg/core.py"] = "y = 2\n"
    text = scan_repo(make_repo(tmp_path, "pkg", files))
    assert text.index("# File: src/pkg/core.py") < text.index("# File: src/pkg/aaa.py")


def test_scan_respects_budget(tmp_path):
    files = {f"src/m{i}.py": f'"""Module {i}."""\n' + "x = 1\n" * 500 for i in range(40)}
    text = scan_repo(make_repo(tmp_path, "big", files), budget=20_000)
    assert len(text) < 20_000
    assert "# Other main files" in text and ": Module " in text     # the rest, one line each


def test_ollama_budget_fits_its_context(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    assert llm.scan_budget("ollama") < 16384 * 3 < llm.scan_budget("anthropic")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "32768")
    assert llm.scan_budget("ollama") > 16384 * 3


def test_instructions_come_after_the_material():
    from proof.prompts import CASE_STUDY, PITCH, PROFILE
    assert CASE_STUDY.index("{repo_scan}") < CASE_STUDY.index("Task:")
    assert PITCH.index("{case_studies}") < PITCH.index("Rules:")
    assert PROFILE.index("{case_studies}") < PROFILE.index("Rules:")


# ---------------------------------------------------------------------------
# Tidying model output
# ---------------------------------------------------------------------------

def test_preamble_and_fence_are_removed():
    reply = ("Sure! Here's the case study:\n\n```markdown\n# App - does X\n## How it works\n"
             "```mermaid\nflowchart TD\nA --> B\n```\n## Results\n```\nHope this helps!")
    cleaned = llm.drop_preamble(llm.strip_wrapper(reply))
    assert cleaned.startswith("# App") and cleaned.endswith("## Results")
    assert "```mermaid" in cleaned
    assert llm.drop_preamble("Here you go:\n# Title\ntext") == "# Title\ntext"


def test_fix_mermaid_quotes_labels():
    text = ("Intro A[not touched]\n```mermaid\nflowchart TD\n"
            "A[API (FastAPI)] -->|reads (cached)| B[(Postgres)]\n"
            "B --> C[\"ok\"]\nC --> D[[sub]]\n```")
    fixed = llm.fix_mermaid(text)
    assert 'A["API (FastAPI)"] -->|"reads (cached)"| B[(Postgres)]' in fixed
    assert 'C["ok"]' in fixed and "D[[sub]]" in fixed
    assert "Intro A[not touched]" in fixed                     # outside the diagram


# ---------------------------------------------------------------------------
# Claims: numbers must come from somewhere
# ---------------------------------------------------------------------------

def test_unsupported_numbers():
    from proof.lint import unsupported_numbers
    sources = ["README: caught 17/20 regressions, 1200 requests. Uses qwen2.5", "62 commits"]
    text = ("Caught 17/20 regressions over 1,200 requests in 62 commits on Qwen 2.5. "
            "Cut latency by 40% and made it 3x faster with 3 agents. "
            "[add: 99 users]\n```mermaid\nA[\"Step 77\"]\n```\nWant a 15-minute call?")
    assert unsupported_numbers(text, sources) == ["40%", "3x"]


def test_case_study_check_flags_invented_numbers():
    from proof.lint import check_case_study
    text = "# X\n## Results\nServes 5,000 users with 99.9% uptime.\n"
    problems = " ".join(check_case_study(text, sources=["5000 users in README"]))
    assert "99.9%" in problems and "5,000" not in problems


def test_pitch_lint_checks_numbers_against_sources():
    pitch = "Your bot is slow. In rag-bot I cut answers to 200 ms and 40% cheaper. Quick call?"
    problems = lint_pitch(pitch, job="Speed up our bot", sources=["rag-bot: answers in 200 ms"])
    assert any("40%" in message and "200" not in message for _, message in problems)


# ---------------------------------------------------------------------------
# Facts, edits and caching
# ---------------------------------------------------------------------------

def test_facts_file_closes_gaps(repos, tmp_path):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    folder = tmp_path / "proof_output" / "rag-bot"
    facts = (folder / "facts.md").read_text()
    assert "- response time / users / accuracy: " in facts       # one line per gap

    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert "up to date" in out                                   # empty facts change nothing

    (folder / "facts.md").write_text(facts.replace("accuracy: ", "accuracy: 300 ms p95"))
    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert "writing case study" in out                           # new facts -> redo

    run("case", str(repos["rag"]), "--dry-run", cwd=tmp_path)
    prompt = (folder / "prompt.txt").read_text()
    assert "300 ms p95" in prompt and "who has this problem:" not in prompt


def test_read_facts_skips_empty_lines(tmp_path):
    from proof.facts import read_facts
    (tmp_path / "facts.md").write_text("<!-- help\ntext -->\n- users: 40\n- accuracy: \n"
                                       "Demo: https://x.dev\n")
    assert read_facts(tmp_path) == "- users: 40\nDemo: https://x.dev"
    assert read_facts(tmp_path / "missing") == ""


def test_edited_case_study_is_never_overwritten(repos, tmp_path):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    case_file = tmp_path / "proof_output" / "rag-bot" / "case_study.md"
    case_file.write_text("# rag-bot - my own words\n")
    commit_change(repos["rag"])
    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "you edited case_study.md" in out
    assert case_file.read_text() == "# rag-bot - my own words\n"
    assert (case_file.parent / "case_study.new.md").read_text().startswith("# rag-bot - (mock)")

    case_file.unlink()                                  # accept the new version
    (case_file.parent / "case_study.new.md").rename(case_file)
    commit_change(repos["rag"])
    code, out = run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert "you edited" not in out                      # unedited again -> normal overwrite


def test_case_from_url_checks_commit_without_cloning(repos, tmp_path):
    url = f"file://{repos['rag']}"
    code, out = run("case", url, "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "Cloning" in out, out
    assert (tmp_path / "proof_output" / "rag-bot" / "case_study.md").exists()
    code, out = run("case", url, "--provider", "mock", cwd=tmp_path)
    assert "up to date" in out and "Cloning" not in out


def test_mock_diagram_uses_real_imports(tmp_path):
    repo = make_repo(tmp_path, "app", {"main.py": "import db\n", "db.py": "x = 1\n"})
    run("case", str(repo), "--provider", "mock", cwd=tmp_path)
    text = (tmp_path / "proof_output" / "app" / "case_study.md").read_text()
    assert 'N0["main.py"] --> N1["db.py"]' in text


# ---------------------------------------------------------------------------
# Job posts from a paste or a URL; pitch log; profile
# ---------------------------------------------------------------------------

def test_pitch_from_pasted_text(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    code, out = run("pitch", "-", "--provider", "mock", cwd=tmp_path,
                    stdin="Need a FastAPI RAG chatbot!\nWith LangChain.")
    assert code == 0, out
    assert (tmp_path / "proof_output" / "pitches" / "need-a-fastapi-rag-chatbot.md").exists()


JOB_PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting", "title": "FastAPI developer",
 "description": "<p>Build a <b>RAG chatbot</b> with LangChain.</p>"}
</script></head><body><nav>Jobs Login</nav><p>Cookie banner</p></body></html>"""


def test_job_from_page_prefers_job_posting():
    from proof.jobpost import job_from_page
    expected = "FastAPI developer\n\nBuild a RAG chatbot with LangChain."
    assert job_from_page(JOB_PAGE) == (expected, True)
    plain = job_from_page("<body><nav>Menu</nav><h1>Job</h1><p>Use  Docker</p><script>x()</script>")
    assert plain == ("Job\nUse Docker", False)


def test_pitch_from_url(repos, tmp_path, fake_api):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    code, out = run("pitch", fake_api + "/jobs/fastapi-dev", "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    assert "fastapi" in out.split("Writing pitch")[0]           # matched on the page's text
    assert (tmp_path / "proof_output" / "pitches" / "fastapi-dev.md").exists()

    code, out = run("pitch", fake_api + "/login-wall", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "paste it instead" in out


def test_pitch_log(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    for name, text in [("rag-job", "FastAPI RAG chatbot"), ("rag-job-2", "LangChain RAG bot"),
                       ("shop-job", "React Tailwind store")]:
        (tmp_path / f"{name}.txt").write_text(text)
        run("pitch", f"{name}.txt", "--provider", "mock", "--top", "1", cwd=tmp_path)

    code, out = run("log", cwd=tmp_path)
    assert "rag-job" in out and "draft" in out and "Nothing marked as sent" in out

    run("log", "rag-job-2", "sent", cwd=tmp_path)
    run("log", "rag-job-2", "replied", "--note", "asked for a call", cwd=tmp_path)
    run("log", "shop", "sent", cwd=tmp_path)                    # unique prefix works
    code, out = run("log", "rag-job", "won", cwd=tmp_path)      # exact name wins over prefix
    assert code == 0 and "rag-job: won" in out

    code, out = run("log", cwd=tmp_path)
    assert "3 sent, 2 replies (66%), 1 won" in out
    assert "rag-bot" in out.split("By project")[1].splitlines()[1]
    log = json.loads((tmp_path / "proof_output" / "pitches" / "log.json").read_text())
    assert log["rag-job-2"]["notes"] == ["asked for a call"]

    code, out = run("log", "nope", "sent", cwd=tmp_path)
    assert code != 0 and "No single pitch" in out


def test_profile(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    code, out = run("profile", "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    profile = (tmp_path / "proof_output" / "profile.md").read_text()
    assert "## Resume bullets" in profile and "### rag-bot" in profile and "### shop-ui" in profile
    code, out = run("profile", "--provider", "mock", "--only", "shop-ui", cwd=tmp_path)
    assert "### rag-bot" not in (tmp_path / "proof_output" / "profile.md").read_text()


def test_api_retries_when_busy(fake_api, monkeypatch):
    monkeypatch.setattr(llm, "RETRY_WAITS", [0, 0])
    monkeypatch.setenv("OPENAI_BASE_URL", fake_api + "/busy-once/v1")
    FakeAPI.busy_once = True
    assert llm.ask_llm("hello", "openai", "m1") == "openai ok"
