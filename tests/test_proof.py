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
    assert "Writing pitch using: rag-bot ..." in out           # shop-ui shares no tech
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
        if self.path.startswith("/gh/"):                 # a fake GitHub API
            return self.github(self.path[len("/gh"):])
        page = {"/jobs/fastapi-dev": JOB_PAGE,
                "/login-wall": "<html><body><h1>Please log in</h1></body></html>",
                "/jobs.rss": todays_feed(),
                "/broken.rss": "<rss><channel><item><title>Job</title></item>"
                               "<item><title>Job 2</title></item></channel></rss>",
                "/api/tags": json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]})}
        self.reply(200, page.get(self.path, "not found").encode(), "text/html")

    def github(self, path):
        if path.startswith("/repos/me/blocked"):
            return self.reply(403, b'{"message": "blocked"}', "application/json")
        answers = {
            "/repos/me/app": {"default_branch": "main", "open_issues_count": 3,
                              "html_url": "https://github.com/me/app"},
            "/repos/me/app/pulls": [{"number": 7}],
            "/repos/me/app/actions/runs": {"workflow_runs": [
                {"status": "completed", "conclusion": "failure", "name": "CI",
                 "html_url": "https://github.com/me/app/actions/runs/1"}]},
            "/repos/me/app/issues": [{"number": 5, "title": "Login breaks on Safari",
                                      "body": "Steps: open in Safari."},
                                     {"number": 7, "title": "A PR", "pull_request": {}}],
        }
        answer = answers.get(path.split("?")[0])
        if answer is None:
            return self.reply(404, b'{"message": "Not Found"}', "application/json")
        self.reply(200, json.dumps(answer).encode(), "application/json")

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
        if self.path == "/missing/api/chat":
            return self.reply(404, b'{"error": "model not found, try pulling it first"}',
                              "application/json")
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
    assert "# Outlines of other main files" in text and ": Module " in text   # the rest, briefly


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
    code, out = run("profile", "--provider", "mock", "--only", "nope", cwd=tmp_path)
    assert code != 0 and "No case studies called nope" in out


def test_api_retries_when_busy(fake_api, monkeypatch):
    monkeypatch.setattr(llm, "RETRY_WAITS", [0, 0])
    monkeypatch.setenv("OPENAI_BASE_URL", fake_api + "/busy-once/v1")
    FakeAPI.busy_once = True
    assert llm.ask_llm("hello", "openai", "m1") == "openai ok"


def test_api_routes_before_ui_kit(tmp_path):
    files = {f"src/app/p{i}/page.tsx": 'import { Button } from "@/components/ui/button";\n'
             for i in range(5)}
    files["src/components/ui/button.tsx"] = "export const Button = 1\n"
    files["src/app/api/webhooks/stripe/route.ts"] = "export async function POST() {}\n"
    text = scan_repo(make_repo(tmp_path, "web", files))
    assert (text.index("# File: src/app/api/webhooks/stripe/route.ts")
            < text.index("# File: src/components/ui/button.tsx"))


# ---------------------------------------------------------------------------
# Other stacks and repo shapes (found by scanning 19 real repos)
# ---------------------------------------------------------------------------

def test_spring_project_under_samples_package(tmp_path):
    base = "src/main/java/org/acme/samples/clinic"
    repo = make_repo(tmp_path, "clinic", {
        "pom.xml": "<artifactId>spring-boot-starter-data-jpa</artifactId><artifactId>thymeleaf"
                   "</artifactId><artifactId>postgresql</artifactId>",
        f"{base}/ClinicApplication.java": "package x;\nclass ClinicApplication {}",
        f"{base}/owner/Owner.java": "package x;\nimport org.acme.samples.clinic.model.Person;\n"
                                    "class Owner extends Person { Pet pet; }",
        f"{base}/owner/Pet.java": "class Pet {}",
        f"{base}/model/Person.java": "class Person {}",
        f"{base}/package-info.java": "package x;",
        "src/test/java/org/acme/samples/clinic/OwnerTests.java": "class OwnerTests {}",
        "src/main/resources/db/data.sql": "INSERT INTO owners VALUES (1);",
        "src/main/resources/db/schema.sql": "CREATE TABLE owners (id int);",
    })
    expected = {"Java", "Spring Boot", "JPA / Hibernate", "Thymeleaf", "PostgreSQL", "Maven"}
    assert expected <= set(detect_stack(repo))
    text = scan_repo(repo)
    read = [line[8:] for line in text.splitlines() if line.startswith("# File: ")]
    assert read.index(f"{base}/ClinicApplication.java") < read.index(f"{base}/model/Person.java")
    assert read.index(f"{base}/model/Person.java") < read.index(f"{base}/package-info.java")
    db = "src/main/resources/db/"
    assert read.index(db + "schema.sql") < read.index(db + "data.sql")
    assert "(all paths are under src/main/java/org/acme/samples/clinic/)" in text
    assert "owner/Owner.java -> model/Person.java, owner/Pet.java" in text   # same-package use


def test_android_stack_from_version_catalog(tmp_path):
    repo = make_repo(tmp_path, "garden", {
        "gradle/libs.versions.toml": 'compose = { module = "androidx.compose.ui:ui" }\n'
                                     'room = { module = "androidx.room:room-runtime" }\n'
                                     'hilt = { module = "com.google.dagger:hilt-android" }\n',
        "app/src/main/java/com/acme/garden/MainActivity.kt": "class MainActivity",
        "macrobenchmark/src/main/java/com/acme/Bench.kt": "class Bench",
        ".github/ISSUE_TEMPLATE/bug.yml": "name: bug",
        ".github/workflows/android.yml": "on: push",
    })
    assert {"Kotlin", "Jetpack Compose", "Room", "Hilt", "Gradle"} <= set(detect_stack(repo))
    text = scan_repo(repo)
    assert "macrobenchmark/  (1 files, not main code)" in text
    assert ".github/  (1 files, not main code)" in text                  # issue templates
    assert ".github/workflows/android.yml\n" in text                      # CI stays visible


def test_go_project(tmp_path):
    repo = make_repo(tmp_path, "glowish", {
        "go.mod": "module github.com/acme/glowish\n\nrequire (\n"
                  "\tgithub.com/spf13/cobra v1.8.0\n"
                  "\tgithub.com/charmbracelet/bubbletea v1.0.0\n)\n",
        "main.go": 'package main\n\nimport (\n\t"fmt"\n\t"github.com/acme/glowish/ui"\n'
                   '\tu "github.com/acme/glowish/utils"\n)\n',
        "ui/ui.go": 'package ui\n\nimport "github.com/acme/glowish/utils"\n',
        "ui/pager.go": "package ui\n",
        "utils/utils.go": "package utils\n",
        "utils/utils_test.go": "package utils\n",
    })
    assert {"Go", "Cobra", "Bubble Tea"} <= set(detect_stack(repo))
    text = scan_repo(repo)
    assert "main.go -> ui/, utils/" in text and "ui/ui.go -> utils/" in text
    assert text.index("# File: utils/utils.go") < text.index("# File: ui/pager.go")  # imported most


def test_rust_workspace(tmp_path):
    repo = make_repo(tmp_path, "rg", {
        "Cargo.toml": '[package]\nname = "rg"\n[dependencies]\nserde = "1"\n'
                      'grep = { path = "crates/grep" }\n',
        "crates/core/main.rs": "mod flags;\nuse grep::Searcher;\nfn main() {}\n",
        "crates/core/flags/mod.rs": "use crate::search;\n",
        "crates/core/search.rs": "pub fn search() {}",
        "crates/grep/Cargo.toml": '[package]\nname = "grep"\n',
        "crates/grep/src/lib.rs": "pub struct Searcher;",
        "pkg/brew/rg.rb": "class Rg < Formula\nend\n",
        "fuzz/fuzz_targets/glob.rs": "fn fuzz() {}",
        **{f"crates/grep/src/part{i}.rs": "" for i in range(10)},   # Rust is >90% of the code
    })
    stack = detect_stack(repo)
    assert {"Rust", "Serde"} <= set(stack) and "Ruby" not in stack       # 1 formula file
    text = scan_repo(repo)
    assert "crates/core/main.rs -> crates/core/flags/mod.rs, crates/grep/src/lib.rs" in text
    assert "crates/core/flags/mod.rs -> crates/core/search.rs" in text
    assert text.index("# File: crates/core/search.rs") < text.index("# File: pkg/brew/rg.rb")
    assert "fuzz/  (1 files, not main code)" in text


def test_generated_and_config_files_are_read_last(tmp_path):
    repo = make_repo(tmp_path, "web", {
        "package.json": json.dumps({"dependencies": {"next": "14"}}),
        "tsconfig.json": "{}",
        "app/page.tsx": 'import { db } from "@/lib/db";\n'
                        'import { api } from "@/client/sdk.gen";\n',
        "lib/db.ts": "export const db = 1\n",
        "client/sdk.gen.ts": "// This file is auto-generated by openapi-ts\nexport const api = 1\n",
        "client/types.ts": "// Code generated by a tool. DO NOT EDIT.\nexport type T = 1\n",
        "tailwind.config.js": "module.exports = {}\n",
        "notebooks/a.ipynb": "{}",
    })
    text = scan_repo(repo)
    assert "app/page.tsx -> client/sdk.gen.ts, lib/db.ts" in text        # "@/" = package root
    assert "# File: client/sdk.gen.ts" not in text and "# File: client/types.ts" not in text
    assert text.index("# File: lib/db.ts") < text.index("# File: tailwind.config.js")
    assert "JavaScript" not in detect_stack(repo)                       # just a config file


def test_second_copies_are_read_last():
    from proof.scan import first_copies_first
    files = [Path(p) for p in ["notebooks/a.ipynb", "notebooks_v1/a.ipynb", "notebooks/b.ipynb",
                               "api/route.ts", "web/route.ts"]]
    order = [f.as_posix() for f in first_copies_first(files)]
    assert order == ["notebooks/a.ipynb", "notebooks/b.ipynb", "api/route.ts", "web/route.ts",
                     "notebooks_v1/a.ipynb"]


def test_files_follow_gitignore_and_secrets_never_listed(tmp_path):
    from proof.scan import list_files
    repo = make_repo(tmp_path, "app", {"main.py": "x = 1\n", ".gitignore": "data/\n",
                                       ".env.example": "KEY=\n"})
    (repo / "data").mkdir()
    (repo / "data" / "big.csv").write_text("1,2")
    (repo / "new.py").write_text("y = 2\n")                   # untracked but not ignored
    (repo / ".env").write_text("KEY=secret")
    (repo / "server.pem").write_text("-----BEGIN")
    names = {f.as_posix() for f in list_files(repo)}
    assert names == {".gitignore", ".env.example", "main.py", "new.py"}

    plain = tmp_path / "plain"                                # not a git repo: walk it
    (plain / "node_modules" / "x").mkdir(parents=True)
    (plain / "node_modules" / "x" / "i.js").write_text("")
    (plain / "app.py").write_text("")
    (plain / ".env").write_text("KEY=secret")
    assert [f.as_posix() for f in list_files(plain)] == ["app.py"]


def test_huge_files_are_not_read(tmp_path):
    from proof.scan import MAX_READ_BYTES, read_text
    (tmp_path / "dump.py").write_text("x" * (MAX_READ_BYTES + 1))
    assert read_text(tmp_path / "dump.py") == ""


def test_repo_with_nothing_to_write_about_is_skipped(tmp_path):
    empty = make_repo(tmp_path, "hello", {"README.md": "# hello\n", "notes.txt": "hi"})
    code, out = run("case", str(empty), "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "skipped: no code" in out
    assert not (tmp_path / "proof_output" / "hello" / "case_study.md").exists()
    readme_only = make_repo(tmp_path, "essay", {"README.md": "word " * 200})
    code, out = run("case", str(readme_only), "--provider", "mock", cwd=tmp_path)
    assert "saved" in out


def test_matching_case_sensitive_terms_and_weak_tools():
    from proof.match import tech_in
    assert {"Room", "Hilt", "Go"} <= tech_in("Kotlin app with Room and Hilt, backend in Go")
    assert not {"Room", "Go", "Rich"} & tech_in("room to grow, rich features, let's go")
    ranked = rank_projects("Go CLI with Cobra, Docker and GitHub Actions",
                           [{"name": "cli", "text": "Go Cobra Docker"},
                            {"name": "web", "text": "Docker GitHub Actions React"}])
    assert ranked[0]["name"] == "cli" and ranked[1]["score"] < ranked[0]["score"] / 2


def test_pitch_uses_only_strong_second_projects(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    (tmp_path / "job.txt").write_text("FastAPI LangChain RAG bot with Docker and a React page")
    code, out = run("pitch", "job.txt", "--provider", "mock", cwd=tmp_path)
    assert "Writing pitch using: rag-bot ..." in out          # shop-ui only shares React


def test_framework_internals_not_listed(tmp_path):
    repo = make_repo(tmp_path, "api", {"requirements.txt": "flask==3.0\nwerkzeug==3.0\n"
                                                           "jinja2==3.1\nclick==8.1\n",
                                       "app.py": "from flask import Flask\n"})
    assert detect_stack(repo) == ["Flask", "Python"]


def test_profile_fits_the_context(tmp_path):
    for i in range(20):                         # 20 long case studies: ~120K characters
        folder = tmp_path / "proof_output" / f"p{i:02}"
        folder.mkdir(parents=True)
        gaps = "[add: users]" if i % 2 else ""
        (folder / "case_study.md").write_text(f"# p{i:02} - a project\n{gaps}\n" + "word " * 1200)
    code, out = run("profile", "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "Left out" in out
    used = out.split("Writing profile from: ")[1].split(" ...")[0].split(", ")
    left_out = out.split("Left out (they don't fit the model's context): ")[1].split(".")[0]
    assert all(f"p{i:02}" in used for i in range(0, 20, 2))   # complete ones go first
    assert all(int(name[1:]) % 2 for name in left_out.split(", "))


def test_non_ascii_file_names(tmp_path):
    from proof.scan import list_files
    repo = make_repo(tmp_path, "intl", {"résumé.py": "x = 1\n", "main.py": "import json\n"})
    assert {f.name for f in list_files(repo)} == {"résumé.py", "main.py"}


def test_thinking_is_removed():
    reply = "<think>\nThe user wants a pitch. # Not a title\n</think>\n\nYour API is slow."
    assert llm.strip_wrapper(reply) == "Your API is slow."
    assert llm.strip_wrapper("planning...\n</think>\n# Title\ntext") == "# Title\ntext"


def test_ollama_missing_model(fake_api, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", fake_api + "/missing")
    with pytest.raises(SystemExit, match="ollama list"):
        llm.ask_llm("hello", "ollama", "qwen2.5-coder:7b")


def test_mistyped_folder_stops_before_any_work(repos, tmp_path):
    code, out = run("case", str(repos["rag"]), "no-such-repo", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "Not a folder: no-such-repo" in out
    assert not (tmp_path / "proof_output").exists()          # rag-bot wasn't written either


# ---------------------------------------------------------------------------
# Real model output (llama3.1:8b on Mauk's laptop, doppel, 2026-10-28)
# ---------------------------------------------------------------------------

DOPPEL_README_BITS = """Test mode was run on 30 open-source Python web apps.
Where it works, it ran up to 10,214 tests and recorded thousands of requests per app without
a single false difference. BugsInPy bugs that ran (22 of 37 didn't run: harness and connection
errors, and failed installs). It caught 0 of 14 recent real fixes.
A live pull request on a fresh repo: all 44 tests pass, Doppel fails the check."""


def test_real_llama_output_problems_are_caught():
    from proof.lint import check_case_study
    text = (TOOL / "tests" / "fixtures" / "llama3.1-8b_doppel.md").read_text()
    problems = "\n".join(check_case_study(text, [DOPPEL_README_BITS]))
    assert "22, 37: meaning may be turned around" in problems
    assert "22 of 37 didn't run" in problems
    assert "Engineering highlights name no real file" in problems
    assert "daunting" in problems and "here is a mermaid" in problems
    assert "10,214" not in problems                    # "without" is too far from the number


def test_negation_must_be_close_to_the_number():
    from proof.lint import flipped_numbers
    source = "A live PR: all 44 tests pass, Doppel fails the check."
    assert flipped_numbers("All 44 tests passed.", [source]) == []      # "fails" is another clause
    flip = [("44", "44 tests didn't run")]
    assert flipped_numbers("Ran 44 tests.", ["44 tests didn't run"]) == flip
    assert flipped_numbers("44 tests didn't run.", ["44 tests didn't run"]) == []


def test_specific_highlights_pass():
    from proof.lint import vague_highlights
    assert not vague_highlights("## Engineering highlights\n- `diff.py` ignores noisy fields\n")
    assert not vague_highlights("## Engineering highlights\n- settle() is idempotent\n")
    assert vague_highlights("## Engineering highlights\n- Built a comparison tool\n## Results\n")


def test_pitch_lint_catches_flipped_numbers():
    pitch = "Your tests miss bugs. Doppel caught 22 of 37 BugsInPy bugs. Quick call?"
    problems = lint_pitch(pitch, sources=["BugsInPy bugs that ran (22 of 37 didn't run)"])
    assert any("22" in message and "wrong meaning" in message for _, message in problems)


# llama3.1:8b, second run: it copied the prompt's examples into both case studies
OLD_PROMPT_EXAMPLES = """Good: "`sync/queue.py` retries failed uploads with backoff and resumes from
the last chunk, so a dropped connection never loses a file." Label each box with what it does
and its file, e.g. A["Web API (app/main.py)"]. Keep each number with what it measured:
"12 of 40 tests didn't run" must NOT become "passed 12 of 40 tests"."""
CLIENT_DESK_FILES = ["prisma/schema.prisma", "src/lib/dal.ts", "src/app/(portal)/page.tsx",
                     "src/app/(portal)/dashboard/page.tsx", "src/app/api/webhooks/stripe/route.ts"]


def test_real_llama_copying_is_caught():
    from proof.lint import check_case_study
    text = (TOOL / "tests" / "fixtures" / "llama3.1-8b_client-desk_v2.md").read_text()
    readme = "ClientDesk: Next.js 16, React 19, Prisma 6, PostgreSQL, Stripe. Uploads up to 50 MB."
    problems = "\n".join(check_case_study(text, [readme], files=CLIENT_DESK_FILES,
                                          prose=[readme], prompt=OLD_PROMPT_EXAMPLES))
    assert "files that aren't in the repo: app/main.py, src/app/portal/" in problems
    assert "sync/queue.py" in problems
    assert "Results numbers the README and your facts don't state: 12, 40, 100%, 30" in problems
    assert "copied from the prompt" in problems


def test_paths_that_are_not_files():
    from proof.lint import missing_files
    text = ("Skills: CI/CD, AI/ML. Uses Next.js and Node.js. Reads `tox.ini`. See "
            "doppel/sandbox.py and https://github.com/x/y.py and `nope.py`.")
    files = ["src/doppel/sandbox.py"]
    assert missing_files(text, files, sources=["finds the test command in tox.ini"]) == ["nope.py"]


def test_case_study_is_repaired_once(repos, tmp_path, monkeypatch, capsys):
    from proof import casestudy, cli
    bad = ("# rag-bot - answers questions over PDFs\n## The problem\nTeams lose time.\n"
           "## What I built\nA bot.\n## How it works\nFastAPI app.\n```mermaid\nflowchart TD\n"
           'A["API (app/main.py)"]\n```\n## Tech stack\n- FastAPI\n## Engineering highlights\n'
           "- `sync/queue.py` retries uploads.\n## Results\n- [add: users]\n"
           "## Skills shown\nFastAPI\n")
    good = bad.replace("`sync/queue.py` retries uploads", "`app/main.py` serves the API")
    replies = [bad, good]
    prompts = []
    def fake_llm(prompt, provider, model):
        prompts.append(prompt)
        return replies.pop(0)
    monkeypatch.setattr(casestudy, "ask_llm", fake_llm)
    monkeypatch.chdir(tmp_path)
    cli.main(["case", str(repos["rag"]), "--provider", "openai", "--model", "m"])
    out = capsys.readouterr().out
    assert "asking the model to fix them" in out and "WARN" not in out
    assert "sync/queue.py" in prompts[1] and "=== CASE STUDY ===" in prompts[1]
    saved = (tmp_path / "proof_output" / "rag-bot" / "case_study.md").read_text()
    assert "`app/main.py` serves the API" in saved


def test_worse_repair_is_thrown_away(repos, tmp_path, monkeypatch, capsys):
    from proof import casestudy, cli
    bad = ("# rag-bot - x\n## The problem\nx\n## What I built\nx\n## How it works\nx\n```mermaid\n"
           "flowchart TD\nA\n```\n## Tech stack\nx\n## Engineering highlights\n- `sync/q.py` x\n"
           "## Results\nx\n## Skills shown\nx\n")
    replies = [bad, "Sorry, I can't help with that."]
    monkeypatch.setattr(casestudy, "ask_llm", lambda prompt, provider, model: replies.pop(0))
    monkeypatch.chdir(tmp_path)
    cli.main(["case", str(repos["rag"]), "--provider", "openai", "--model", "m"])
    saved = (tmp_path / "proof_output" / "rag-bot" / "case_study.md").read_text()
    assert saved.startswith("# rag-bot - x")
    assert "files that aren't in the repo: sync/q.py" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Claim links: each Results line points to the README line it comes from
# ---------------------------------------------------------------------------

LINK_README = """# Tool
<img alt="architecture: 17 parts, 20 arrows">
| Arm | Caught | False alarms |
| Tool | 17/20 | 2/10 |
| Tests alone | 12/20 | 0/10 |
Gaps were fixed against these apps: 1/10 before, 8/10 after.
BugsInPy bugs that ran (22 of 37 didn't run: harness errors).
It ran up to 10,214 tests per app without a single false difference."""


def test_claim_links_point_to_the_right_lines():
    from proof.claims import add_source_links
    case_study = ("# Tool\n## Results\n- Caught 17/20 regressions, against 12/20 for tests alone.\n"
                  "- 8 of 10 apps worked after fixing gaps.\n- Caught 22 of 37 BugsInPy bugs.\n"
                  "- Ran 10,214 tests.\n- Serves 900 users.\n- [add: response time]\n"
                  "## Skills shown\nPython\n")
    linked = add_source_links(case_study, LINK_README, "README.md", "- users: 900",
                              "https://github.com/me/tool", "abc123")
    url = "https://github.com/me/tool/blob/abc123/README.md#L"
    assert f"12/20 for tests alone. ([source]({url}4)) ([source]({url}5))" in linked
    assert f"after fixing gaps. ([source]({url}6))" in linked
    assert "- Caught 22 of 37 BugsInPy bugs.\n" in linked          # meaning flipped: no link
    assert f"Ran 10,214 tests. ([source]({url}8))" in linked
    assert "Serves 900 users. (self-reported)" in linked
    assert "#L2" not in linked                                      # HTML alt text isn't a source
    assert linked.endswith("## Skills shown\nPython\n")             # other sections untouched


def test_claim_links_without_a_web_address():
    from proof.claims import add_source_links
    linked = add_source_links("## Results\n- Ran 10,214 tests.\n", LINK_README, "README.md",
                              "", None, None)
    assert "Ran 10,214 tests. (README.md line 8)" in linked


def test_web_url_and_pushed_commit(tmp_path):
    from proof.scan import pushed_commit, web_url
    assert web_url("https://github.com/me/app.git", None) == "https://github.com/me/app"
    repo = make_repo(tmp_path, "app", {"main.py": "x = 1\n"})
    assert web_url(str(repo), repo) is None                         # no remote
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "git@github.com:me/app.git"], check=True)
    assert web_url(str(repo), repo) == "https://github.com/me/app"
    assert pushed_commit(repo) == "HEAD"                            # not on any remote yet


# ---------------------------------------------------------------------------
# proof eval
# ---------------------------------------------------------------------------

def test_eval_scores_models_and_compares_with_last_run(repos, tmp_path, monkeypatch, capsys):
    from proof import casestudy, evaluate
    clean = ("# rag-bot - answers questions over PDFs\n## The problem\nSupport teams answer the "
             "same PDF questions all day.\n## What I built\nA chatbot.\n## How it works\nA FastAPI "
             "app.\n```mermaid\nflowchart TD\nA[\"API (app/main.py)\"]\n```\n## Tech stack\n- "
             "FastAPI\n## Engineering highlights\n- `app/main.py` serves the API.\n## Results\n"
             "- [add: users]\n## Skills shown\nFastAPI\n")
    invented = clean.replace("`app/main.py` serves", "`sync/queue.py` retries")
    replies = {"good-model": clean, "bad-model": invented}
    monkeypatch.setattr(casestudy, "ask_llm", lambda prompt, provider, model: replies[model])

    out = tmp_path / "out"
    rows = evaluate.run([str(repos["rag"])], ["good-model", "bad-model"], "openai", out, 70_000,
                        tmp_path / "clones")
    assert [len(r["problems"]) for r in rows] == [0, 1]
    printed = capsys.readouterr().out
    assert "bad-model                    rag-bot" in printed and "invented files x1" in printed
    assert "good-model: 0 problems in drafts, 0 after repair, 1/1 clean" in printed

    run_dir = next((out / "eval").iterdir())
    assert (run_dir / "prompts" / "rag-bot.txt").exists()
    assert "sync/queue.py" in (run_dir / "bad-model" / "rag-bot" / "draft.md").read_text()
    assert json.loads((run_dir / "results.json").read_text())[1]["model"] == "bad-model"

    time.sleep(1.1)                                   # a new eval folder (named by the second)
    replies["bad-model"] = clean                      # e.g. after a prompt fix
    evaluate.run([str(repos["rag"])], ["bad-model"], "openai", out, 70_000, tmp_path / "c2")
    assert "(last eval: 1 after repair - better)" in capsys.readouterr().out


def test_problem_kinds():
    from proof.evaluate import kind_of
    assert kind_of("files that aren't in the repo: a.py - name only real files") == "invented files"
    assert kind_of("22, 37: meaning may be turned around - the repo says") == "flipped number"
    assert kind_of("something new") == "other"


# ---------------------------------------------------------------------------
# proof dataset (fine-tuning data)
# ---------------------------------------------------------------------------

def test_dataset_keeps_only_trusted_case_studies(repos, tmp_path, monkeypatch):
    from proof import casestudy, cli
    from proof.dataset import collect, summary, write
    good = ("# x - y\n## The problem\nTeams answer PDF questions by hand.\n"
            "## What I built\nA bot.\n"
            "## How it works\nAn API.\n```mermaid\nflowchart TD\nA[\"API (app/main.py)\"]\n```\n"
            "## Tech stack\n- FastAPI\n## Engineering highlights\n- `app/main.py` serves it.\n"
            "## Results\n- [add: users]\n## Skills shown\nFastAPI\n")
    bad = good.replace("app/main.py", "nope.py")
    replies = iter([good, bad, bad])            # rag-bot clean; shop-ui bad even after repair
    monkeypatch.setattr(casestudy, "ask_llm", lambda prompt, provider, model: next(replies))
    monkeypatch.chdir(tmp_path)
    cli.main(["case", str(repos["rag"]), "--provider", "openai", "--model", "m"])    # clean
    cli.main(["case", str(repos["shop"]), "--provider", "openai", "--model", "m"])   # not clean
    shop = tmp_path / "proof_output" / "shop-ui"
    assert [e["repo"] for e in collect([tmp_path / "proof_output"])] == ["rag-bot"]

    (shop / "case_study.md").write_text("# shop-ui - fixed by hand\n")              # you edit it
    examples = collect([tmp_path / "proof_output"])
    assert [(e["repo"], e["rank"]) for e in examples] == [("shop-ui", 1), ("rag-bot", 2)]
    assert [e["repo"] for e in collect([tmp_path / "proof_output"], exclude={"shop-ui"})] \
        == ["rag-bot"]

    write(examples, tmp_path / "data.jsonl")
    lines = [json.loads(line) for line in (tmp_path / "data.jsonl").read_text().splitlines()]
    assert lines[1]["messages"][0]["content"].startswith("Below is a scan")
    assert lines[1]["messages"][1]["content"] == good
    assert "only 2 examples" in summary(examples, "data.jsonl")


def test_dataset_strips_source_links():
    from proof.dataset import without_links
    text = ("## Results\n- Ran 10,214 tests. ([source](https://g/b/c/README.md#L8))\n"
            "- 900 users (self-reported)\n- 3 apps (README.md line 4)\n")
    assert without_links(text) == "## Results\n- Ran 10,214 tests.\n- 900 users\n- 3 apps\n"


def test_repo_lists(repos, tmp_path):
    (tmp_path / "list.txt").write_text(f"# my repos\n{repos['rag']}\n\n{repos['shop']}  # shop\n")
    code, out = run("case", "@list.txt", "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "[rag-bot] saved" in out and "[shop-ui] saved" in out
    code, out = run("case", "@missing.txt", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "No such list of repos" in out


def test_training_repo_list_is_valid():
    from proof.cli import expand_repo_lists
    repos = expand_repo_lists([f"@{TOOL / 'training' / 'repos.txt'}"])
    assert len(repos) >= 30 and all(r.startswith("https://github.com/") for r in repos)
    assert not any("maukthik" in r.lower() for r in repos)      # your repos are the test set


# ---------------------------------------------------------------------------
# proof suggest
# ---------------------------------------------------------------------------

def test_checklist_on_a_bare_and_a_ready_repo(tmp_path):
    from proof.scan import list_files
    from proof.suggest import checklist
    bare = make_repo(tmp_path, "bare", {"README.md": "# Bare\nA tool.",
                                        "app.py": 'import os\nkey = os.environ["OPENAI_API_KEY"]\n'
                                                  'rank = os.environ.get("RANK")\n'})
    missing = [what for ok, what, _, _ in checklist(bare, list_files(bare), tmp_path) if not ok]
    assert {"Results section in the README", "Automated tests", ".env.example", "License",
            "Live demo or video link"} <= set(missing)

    readme = ("# Ready\n" + "word " * 160 + "\n![shot](shot.png)\nTry it: https://ready.vercel.app\n"
              "## Quick start\npip install ready\n## Results\n40% faster.\n")
    ready = make_repo(tmp_path, "ready", {"README.md": readme, "LICENSE": "MIT",
                                          "app.py": 'import os\nrank = os.environ.get("RANK")\n',
                                          "tests/test_app.py": "", "Dockerfile": "FROM python",
                                          ".github/workflows/ci.yml": "on: push"})
    assert all(ok for ok, *_ in checklist(ready, list_files(ready), tmp_path))


def test_unfilled_facts_count(tmp_path):
    from proof.suggest import unfilled_facts
    (tmp_path / "facts.md").write_text("<!-- help: x -->\n- users: 40\n- accuracy: \n- speed:\n")
    assert unfilled_facts(tmp_path) == 2


def test_what_clients_asked_for(repos, tmp_path):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    jobs = ["FastAPI RAG bot on AWS with Redis", "LangChain RAG bot, deploy to AWS"]
    for i, job in enumerate(jobs):
        (tmp_path / f"job{i}.txt").write_text(job)
        run("pitch", f"job{i}.txt", "--provider", "mock", cwd=tmp_path)
    code, out = run("suggest", str(repos["rag"]), "--no-ai", cwd=tmp_path)
    assert code == 0, out
    report = (tmp_path / "proof_output" / "rag-bot" / "suggestions.md").read_text()
    assert "also asked for: aws (2), redis (1)" in report
    assert "## Ideas" not in report                                  # --no-ai


def test_suggest_with_ideas_and_tasks(repos, tmp_path):
    code, out = run("suggest", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    report = (tmp_path / "proof_output" / "rag-bot" / "suggestions.md").read_text()
    assert "## Checklist (" in report and "### Add a usage example" in report
    assert "## Tasks for a coding assistant" in report and "In the rag-bot repo:" in report
    assert "WARN" not in out                                         # examples/demo.md is (new)


def test_ideas_naming_unknown_files_are_flagged():
    from proof.suggest import parse_ideas, unknown_files
    text = ("### Faster search\n- What: cache results.\n- Where: app/main.py, cache.py (new), "
            "lib/ghost.py\n- Size: small (hours)\n- Done when: second search is instant.\n")
    ideas = parse_ideas(text)
    assert ideas[0]["title"] == "Faster search" and ideas[0]["Size"] == "small (hours)"
    assert unknown_files(ideas, ["app/main.py"], []) == ["lib/ghost.py"]


# ---------------------------------------------------------------------------
# Secrets, outlines (ideas from repomix/secretlint and aider's repo map)
# ---------------------------------------------------------------------------

def test_known_key_formats_are_removed():
    from proof.redact import REMOVED, redact
    text = ('OPENAI = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"\n'
            'aws = "AKIAABCDEFGHIJKLMNOP"\nghp = "ghp_' + "a" * 36 + '"\n'
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"
            "stripe = 'sk_live_" + "b" * 24 + "'\n")
    cleaned, found = redact(text)
    assert "sk-proj-" not in cleaned and "AKIA" not in cleaned and "ghp_" not in cleaned
    assert "MIIabc" not in cleaned and "sk_live_" not in cleaned
    assert cleaned.count(REMOVED) == 5
    assert set(found) == {"OpenAI key", "AWS access key", "GitHub token", "private key",
                          "Stripe key"}


def test_passwords_but_not_placeholders():
    from proof.redact import redact
    text = ('password = "hunter2hunter2"\napi_key = "your-api-key-here"\n'
            'DB = "postgres://app:s3cretPass@prod.db.example.net/app"\n'
            'LOCAL = "postgresql://dev:dev@localhost:5432/dev"\n'
            'token = os.environ["TOKEN"]\n')
    cleaned, found = redact(text)
    assert "hunter2" not in cleaned and "s3cretPass" not in cleaned
    assert "your-api-key-here" in cleaned and "dev:dev@localhost" in cleaned
    assert len(found) == 2
    example, found = redact('password = "hunter2hunter2"', path=".env.example")
    assert found == []                                          # example files hold placeholders


def test_scan_keeps_secrets_out_of_the_prompt(tmp_path):
    repo = make_repo(tmp_path, "leaky", {"config.py": 'OPENAI_KEY = "sk-' + "x" * 40 + '"\n',
                                         "main.py": "import config\n"})
    removed = []
    text = scan_repo(repo, removed=removed)
    assert "sk-xxxx" not in text and "[secret removed by proof]" in text
    assert removed == [("config.py", "OpenAI key")]
    code, out = run("case", str(repo), "--provider", "mock", cwd=tmp_path)
    assert "SECRET  config.py: OpenAI key" in out


def test_outlines():
    from proof.outline import outline
    py = ('"""Doc."""\nimport os\n\nclass Store(Base):\n    """Keeps things."""\n'
          "    def get(self, key: str) -> str:\n        return 1\n    def _hidden(self):\n"
          "        pass\n\nasync def fetch(url, retries=3):\n    pass\n")
    assert outline(Path("a.py"), py) == ("class Store(Base)  # Keeps things.\n"
                                         "    def get(self, key: str)\n"
                                         "async def fetch(url, retries=3)")
    ts = "import x\nexport async function load(id: string) {\n  return 1\n}\nconst y = 2\n"
    assert outline(Path("a.ts"), ts) == "export async function load(id: string)"
    go = "package ui\nfunc (m *model) View() string {\n}\ntype model struct {\n"
    assert outline(Path("a.go"), go) == "func (m *model) View() string\ntype model struct"
    assert outline(Path("a.py"), "def broken(:\n") == "def broken(:"         # falls back to lines


def test_files_that_dont_fit_are_outlined(tmp_path):
    files = {f"src/m{i}.py": f"def handler_{i}(request):\n    pass\n" + "x = 1\n" * 600
             for i in range(20)}
    text = scan_repo(make_repo(tmp_path, "big", files), budget=20_000)
    assert "# Outlines of other main files" in text and "def handler_19(request)" in text


# ---------------------------------------------------------------------------
# Diagrams checked against the imports (an idea from gitdiagram)
# ---------------------------------------------------------------------------

DIAGRAM = '''# X
```mermaid
flowchart TD
    U["User"] --> A["CLI (doppel/cli.py)"]
    A --> B["Runner (doppel/runner.py)"] --> C["Diff (doppel/diff.py)"]
    C -->|"feeds"| D["Report (src/doppel/report.py)"]
    B --> E["Ghost (doppel/ghost.py)"]
    D --> L["Shared code (src/lib/)"]
```
'''
DIAGRAM_FILES = ["src/doppel/cli.py", "src/doppel/runner.py", "src/doppel/diff.py",
                 "src/doppel/report.py", "src/lib/util.py"]
DIAGRAM_EDGES = [("src/doppel/cli.py", "src/doppel/runner.py"),
                 ("src/doppel/report.py", "src/doppel/diff.py"),
                 ("src/doppel/report.py", "src/lib/util.py")]


def test_diagram_arrows_need_an_import():
    from proof.diagram import check_and_link
    out, dashed = check_and_link(DIAGRAM, DIAGRAM_FILES, DIAGRAM_EDGES)
    assert dashed == 1
    assert 'A --> B["Runner (doppel/runner.py)"] -.-> C' in out     # runner never imports diff
    assert 'C -->|"feeds"| D' in out                                # report imports diff
    assert 'D --> L["Shared code (src/lib/)"]' in out              # a folder counts
    assert 'B --> E["Ghost' in out and 'U["User"] --> A' in out    # not two real files: kept
    assert "click" not in out                                       # no web address: no links


def test_diagram_boxes_link_to_their_files():
    from proof.diagram import check_and_link
    out, _ = check_and_link(DIAGRAM, DIAGRAM_FILES, DIAGRAM_EDGES, "https://github.com/me/x", "c1")
    assert 'click B "https://github.com/me/x/blob/c1/src/doppel/runner.py" _blank' in out
    assert 'click L "https://github.com/me/x/tree/c1/src/lib/" _blank' in out
    assert "click E " not in out and "click U " not in out          # not real files
    again, _ = check_and_link(out, DIAGRAM_FILES, DIAGRAM_EDGES, "https://github.com/me/x", "c1")
    assert again.count("click B ") == 1                             # running twice adds nothing


def test_portfolio_turns_click_lines_into_links():
    from proof.portfolio import to_html
    md = ('```mermaid\nflowchart TD\n    A["CLI (cli.py)"] -.-> B\n'
          '    click A "https://github.com/me/x/blob/c/cli.py" _blank\n'
          '    click B "javascript:alert(1)" _blank\n```\n')
    page = to_html(md)
    assert "data-links=" in page and "https://github.com/me/x/blob/c/cli.py" in page
    assert "click A" not in page and "javascript:" not in page.split("data-links=")[1][:200]
    assert "Click a box to see its code." in page and "Dashed arrows" in page


# ---------------------------------------------------------------------------
# Agent mode: proof scan + proof check (an idea from REA: agents call the tool)
# ---------------------------------------------------------------------------

AGENT_CASE_STUDY = """# rag-bot - answers questions about PDFs
## The problem
Support teams answer the same PDF questions by hand.
## What I built
A chatbot over PDFs.
## How it works
A FastAPI app.
```mermaid
flowchart TD
    U["User"] --> A["API (app/main.py)"]
```
## Tech stack
- FastAPI
## Engineering highlights
- `app/main.py` serves the API.
## Results
- [add: users]
## Skills shown
FastAPI
"""


def test_scan_prints_what_the_model_sees(repos, tmp_path):
    code, out = run("scan", str(repos["rag"]), cwd=tmp_path)
    assert code == 0 and out.startswith("# Repo name: rag-bot")
    code, out = run("scan", str(repos["rag"]), "--prompt", cwd=tmp_path)
    assert "=== REPOSITORY SCAN ===" in out and "Output only the case study" in out


def test_check_gates_and_saves_an_agents_case_study(repos, tmp_path):
    (tmp_path / "bad.md").write_text(AGENT_CASE_STUDY.replace("app/main.py", "sync/queue.py"))
    code, out = run("check", "bad.md", "--repo", str(repos["rag"]), cwd=tmp_path)
    assert code == 1 and "sync/queue.py" in out

    (tmp_path / "good.md").write_text(AGENT_CASE_STUDY)
    code, out = run("check", "good.md", "--repo", str(repos["rag"]), "--save", cwd=tmp_path)
    assert code == 0 and "no problems found" in out and "[rag-bot] saved" in out
    meta = json.loads((tmp_path / "proof_output" / "rag-bot" / "meta.json").read_text())
    assert meta["provider"] == "agent" and meta["problems"] == []
    code, out = run("site", cwd=tmp_path)                       # the rest of proof uses it
    assert code == 0 and "1 project" in out


def test_agent_skill_file_is_valid():
    skill = (TOOL / "agents" / "proof-case-study" / "SKILL.md").read_text()
    front = yaml.safe_load(skill.split("---")[1])
    assert front["name"] == "proof-case-study" and "case study" in front["description"]
    assert "proof check" in skill and "--save" in skill


# ---------------------------------------------------------------------------
# apply (job boards), follow-ups, call prep
# ---------------------------------------------------------------------------

FEEDS = TOOL / "tests" / "fixtures" / "feeds"
PROJECTS = [  # as the matcher sees them (cli.searchable)
    {"name": "ClientDesk", "text": "Next.js TypeScript Stripe webhooks Prisma PostgreSQL "
                                   "role-based access React Tailwind"},
    {"name": "Doppel", "text": "Python FastAPI LLM agents GitHub Actions REST API pytest"},
]


def all_fixture_jobs():
    from proof import feeds
    return (feeds.remotive_jobs(json.loads((FEEDS / "remotive.json").read_text()))
            + feeds.remoteok_jobs(json.loads((FEEDS / "remoteok.json").read_text()))
            + feeds.rss_jobs("wwr", (FEEDS / "wwr.rss").read_text())
            + feeds.hn_thread_jobs("hn-freelance",
                                   json.loads((FEEDS / "hn_freelance_thread.json").read_text())))


def todays_feed():
    """The We Work Remotely sample, posted today (so --days doesn't drop it)."""
    from datetime import date
    today = date.today().strftime("%d %b %Y")
    return (FEEDS / "wwr.rss").read_text().replace("27 Oct 2026", today)


def test_feed_readers():
    jobs = {job["id"]: job for job in all_fixture_jobs()}
    paybright = jobs["remotive:2001"]
    assert paybright["company"] == "Paybright" and paybright["posted"] == "2026-10-26"
    assert "Stripe subscriptions and webhooks" in paybright["text"]       # HTML -> text
    assert "Tags: nextjs, typescript" in paybright["text"]
    assert not any(job["title"] == "" for job in jobs.values())          # Remote OK's notice
    acme = jobs["wwr:https://weworkremotely.com/remote-jobs/acme-labs-backend-developer"]
    assert (acme["company"], acme["title"]) == ("Acme Labs", "Backend Developer (FastAPI, PostgreSQL)")
    assert acme["posted"] == "2026-10-27" and acme["where"] == "Anywhere in the World"
    hn = [job for job in jobs.values() if job["board"] == "hn-freelance"]
    assert [job["title"] for job in hn] == ["Small design agency | Remote",
                                            "Shopify theme tweaks, Liquid templates."]
    assert "hello@example.com" in hn[0]["text"]                           # entities decoded


def test_hn_hiring_titles_and_atom_feeds():
    from proof import feeds
    thread = {"children": [{"id": 1, "created_at": "2026-10-01T00:00:00Z",
                            "text": "Acme | Senior Python Engineer | Remote | $150k<p>Django.</p>"}]}
    job = feeds.hn_thread_jobs("hn", thread)[0]
    assert (job["company"], job["title"]) == ("Acme", "Senior Python Engineer | Remote")
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:x,1</id>
      <title>Go developer</title><link href="https://jobs.example.com/1"/>
      <updated>2026-10-20T08:00:00Z</updated><summary>Go and gRPC.</summary></entry></feed>"""
    job = feeds.rss_jobs("https://jobs.example.com/feed", atom)[0]
    assert (job["title"], job["url"], job["posted"]) == ("Go developer", "https://jobs.example.com/1",
                                                         "2026-10-20")
    with pytest.raises(feeds.FeedError, match="DTD"):
        feeds.rss_jobs("x", '<!DOCTYPE r [<!ENTITY a "aaaa">]><rss>&a;</rss>')
    with pytest.raises(feeds.FeedError, match="unknown board"):
        feeds.read_board("upwork", "/tmp")


def test_find_fits_ranks_explains_and_filters():
    from datetime import date
    from proof.apply import find_fits
    fits = find_fits(all_fixture_jobs(), PROJECTS, seen={}, days=14, min_tech=2,
                     today=date(2026, 10, 28))
    titles = [job["title"] for job, _ in fits]
    assert titles[0] == "Senior Full-Stack Engineer (Next.js / Stripe)"
    assert titles.count(titles[0]) == 1                  # on Remotive and Remote OK: kept once
    assert fits[0][0]["board"] == "remotive"             # the copy with the fuller post
    assert fits[0][1]["missing"] == ["kubernetes"]
    assert fits[0][1]["projects"][0][0] == "ClientDesk"
    assert "Python Developer - LLM evaluation tooling" in titles
    for not_a_fit in ["Data Engineer", "Golang Backend Engineer", "Rails Developer",
                      "Next.js + Stripe developer",       # posted in August: too old
                      "Small design agency | Remote"]:    # posted 25 days ago
        assert not_a_fit not in titles
    seen = {fits[0][0]["id"]: "2026-10-28"}
    again = find_fits(all_fixture_jobs(), PROJECTS, seen, 14, 2, today=date(2026, 10, 28))
    assert fits[0][0]["id"] not in [job["id"] for job, _ in again]


def test_seen_list_forgets_old_ids(tmp_path):
    from datetime import date
    from proof.apply import load_seen, save_seen
    save_seen(tmp_path, {"old:1": "2026-01-01", "recent:2": "2026-10-01"},
              [{"id": "new:3"}], today=date(2026, 10, 28))
    assert load_seen(tmp_path) == {"recent:2": "2026-10-01", "new:3": "2026-10-28"}


def test_apply_end_to_end(repos, tmp_path, fake_api):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    facts = tmp_path / "proof_output" / "rag-bot" / "facts.md"
    facts.write_text("Built REST API endpoints in FastAPI on PostgreSQL.\n")
    feed = fake_api + "/jobs.rss"
    code, out = run("apply", feed, "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    assert "1 fit your projects" in out and "Acme Labs" in out and "Rails" not in out
    pitches = tmp_path / "proof_output" / "pitches"
    assert (pitches / "acme-labs-backend-developer-fastapi-postgresql.md").exists()
    assert "FastAPI" in (pitches / "acme-labs-backend-developer-fastapi-postgresql.job.txt").read_text()
    digest = next((tmp_path / "proof_output" / "jobs").glob("20*.md")).read_text()
    assert "[127.0.0.1:" in digest and "Pitch draft:" in digest

    code, out = run("apply", feed, "--provider", "mock", cwd=tmp_path)   # nothing new
    assert "saved copy" in out and "0 new job(s)" in out and "--refresh" in out
    code, out = run("apply", feed, "--provider", "mock", "--all", cwd=tmp_path)
    assert "Acme Labs" in out and "Drafting" not in out                  # already has a pitch

    code, out = run("apply", "nope", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "unknown board" in out


def test_follow_up_reminders():
    from datetime import date
    from proof.tracker import report, to_do
    log = {"a": {"status": "sent", "sent": "2026-10-20", "projects": []},
           "b": {"status": "sent", "sent": "2026-10-27", "projects": []},
           "c": {"status": "followed-up", "sent": "2026-10-01", "followed-up": "2026-10-10",
                 "projects": []},
           "d": {"status": "replied", "sent": "2026-10-01", "followed-up": "2026-10-06",
                 "projects": []}}
    today = date(2026, 10, 28)
    assert to_do(log, today) == ([("a", 8)], [("c", 18)])
    text = report(log, today)
    assert "proof followup a" in text and "proof log c ignored" in text
    assert "Follow-ups: 2 sent, 1 then got a reply" in text


def test_lint_followup_and_prep():
    from proof.lint import lint_followup, lint_prep
    first = "You need a client portal. In ClientDesk I built role-based access for 3 roles."
    sources = ["--- PROJECT: ClientDesk ---\nStripe webhooks in app/api/stripe/route.ts. "
               "12 of 40 tests didn't run."]
    stale = lint_followup("Just checking in - in ClientDesk I built role-based access for 3 "
                          "roles. Any thoughts?", first, sources)
    messages = " ".join(message for _, message in stale)
    assert "no reason to reply" in messages and "Repeats your first message" in messages
    good = lint_followup("Hi Sam, one more detail: ClientDesk handles Stripe webhooks, which "
                         "your payments step needs. Want a quick look on Thursday?", first, sources)
    assert good == []

    brief = ("### Have you used Stripe?\nYes: app/api/stripe/route.ts handles webhooks, and "
             "12 of 40 tests caught bugs. It served 5,000 users from lib/cache.ts.")
    messages = " ".join(message for _, message in lint_prep(brief, sources))
    assert "5,000" in messages and "lib/cache.ts" in messages and "route.ts" not in messages
    assert "wrong meaning" in messages                     # "didn't run" became "caught"
    assert lint_prep("## 30-second intro\nI built ClientDesk.", sources) == []   # a heading


def test_followup_and_prep_commands(repos, tmp_path):
    run("case", str(repos["rag"]), str(repos["shop"]), "--provider", "mock", cwd=tmp_path)
    (tmp_path / "job.txt").write_text("FastAPI RAG chatbot with LangChain on Kubernetes")
    run("pitch", "job.txt", "--provider", "mock", cwd=tmp_path)
    code, out = run("followup", "job", "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "isn't marked as sent" in out
    assert (tmp_path / "proof_output" / "pitches" / "job.followup.md").exists()

    run("log", "job", "sent", cwd=tmp_path)
    run("log", "job", "replied", "--note", "asked if I know Terraform", cwd=tmp_path)
    code, out = run("followup", "job", "--provider", "mock", cwd=tmp_path)
    assert code != 0 and "proof prep job" in out
    code, out = run("prep", "job", "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    brief = (tmp_path / "proof_output" / "prep" / "job.md").read_text()
    assert "Projects to talk about: rag-bot" in brief
    assert "Not shown in any project: chatbot, kubernetes, terraform" in brief  # + reply
    assert "## Questions to ask them" in brief

    (tmp_path / "other.txt").write_text("React Tailwind storefront")
    code, out = run("prep", "other.txt", "--no-ai", "--provider", "mock", cwd=tmp_path)
    assert code == 0 and "Projects to talk about: shop-ui" in out and "## What they need" not in out


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def test_doctor_all_good(repos, tmp_path, fake_api):
    run("case", str(repos["rag"]), "--provider", "mock", cwd=tmp_path)
    code, out = run("doctor", fake_api + "/jobs.rss", "--provider", "mock", cwd=tmp_path)
    assert code == 0, out
    assert "127.0.0.1:" in out and "2 jobs" in out
    assert "1 case studies: rag-bot (" in out and "0 problem(s)" in out


def test_doctor_model_checks(fake_api, monkeypatch):
    from proof import doctor
    monkeypatch.setenv("OLLAMA_URL", fake_api)
    checks = doctor.model_checks("ollama", "qwen2.5-coder:7b", offline=False)
    assert [level for level, _ in checks] == ["ok", "ok", "ok"]
    assert "test prompt answered" in checks[-1][1]
    level, text = doctor.model_checks("ollama", "llama3.1:8b", offline=False)[-1]
    assert level == "FAIL" and "Installed: qwen2.5-coder:7b" in text
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")            # nothing listens there
    assert "start the Ollama app" in doctor.model_checks("ollama", "x", offline=False)[0][1]
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert doctor.model_checks("openai", "m", offline=False)[0][0] == "FAIL"
    assert doctor.model_checks("openai", "", offline=False)[0][1].startswith("no model")


def test_doctor_spots_broken_boards_and_log(tmp_path, fake_api):
    from proof import doctor
    level, text = doctor.board_checks([fake_api + "/broken.rss"])[0]
    assert level == "warn" and "format may have changed" in text
    assert doctor.board_checks(["nope"])[0][0] == "FAIL"
    log = tmp_path / "pitches" / "log.json"
    log.parent.mkdir()
    log.write_text("{broken")
    assert doctor.log_checks(tmp_path)[0][0] == "FAIL"
    log.write_text(json.dumps({"x": {"status": "sent", "sent": "2026-01-01"}}))
    assert "proof followup x" in doctor.log_checks(tmp_path)[1][1]


# ---------------------------------------------------------------------------
# status / task / new: your projects
# ---------------------------------------------------------------------------

def git_in(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t.t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


PY_PROJECT = {
    "README.md": "# Calc\nAdds numbers.\n",
    "pyproject.toml": "[project]\nname = \"calc\"\n\n[tool.pytest.ini_options]\npythonpath = [\".\"]\n",
    "calc.py": "def add(a, b):\n    # TODO: handle strings\n    return a + b\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
}


def test_status_local(tmp_path):
    projects = tmp_path / "projects"
    app = make_repo(projects, "calc", PY_PROJECT)
    make_repo(projects, "other", {"README.md": "# Other\n"})
    out = tmp_path / "work"
    (out / "proof_output" / "calc").mkdir(parents=True)
    first = subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"], capture_output=True,
                           text=True).stdout.strip()
    (out / "proof_output" / "calc" / "meta.json").write_text(json.dumps({"commit": first}))
    for _ in range(10):
        commit_change(app)
    (app / "calc.py").write_text("changed\n")

    code, text = run("status", str(projects), "--offline", cwd=out)
    assert code == 0, text
    assert "Now tracking 2 more project(s)" in text
    row = next(line for line in text.splitlines() if line.startswith("calc "))
    assert "today" in row and "1 changed" in row
    assert "calc: 1 uncommitted change(s)" in text
    assert "calc: case study is 10 commits old" in text
    assert "other: not on GitHub yet" in text
    assert (out / "proof_output" / "status.md").exists()
    code, again = run("status", "--offline", cwd=out)               # remembered
    assert code == 0 and "other" in again and "Now tracking" not in again


def test_status_github(tmp_path, fake_api, monkeypatch):
    from proof import status
    monkeypatch.setenv("GITHUB_API_URL", fake_api + "/gh")
    app = make_repo(tmp_path, "app", {"README.md": "# App\n"})
    git_in(app, "remote", "add", "origin", "https://github.com/me/app.git")
    statuses, notes = status.collect([app], tmp_path / "out")
    gh = statuses[0]["github"]
    assert (gh["ci"], gh["issues"], gh["prs"]) == ("failure", 2, 1)
    assert "CI is failing on GitHub: https://github.com/me/app/actions/runs/1" in \
        status.needs_you(statuses[0])

    blocked = make_repo(tmp_path, "blocked", {"README.md": "# B\n"})
    git_in(blocked, "remote", "add", "origin", "git@github.com:me/blocked.git")
    statuses, notes = status.collect([blocked, app], tmp_path / "out")
    assert notes == ["GitHub answered HTTP 403 - CI, issues and PRs left out"]
    assert "github" not in statuses[1]                         # not asked again after that


def test_task_import_and_brief(tmp_path, fake_api, monkeypatch):
    from proof import tasks
    monkeypatch.setenv("GITHUB_API_URL", fake_api + "/gh")
    app = make_repo(tmp_path, "calc", PY_PROJECT)
    git_in(app, "remote", "add", "origin", "https://github.com/me/app")
    out = tmp_path / "proof_output"
    (out / "calc").mkdir(parents=True)
    (out / "calc" / "suggestions.md").write_text(
        "# x\n## Ideas\n\n### Add subtraction\n- What: a sub() next to add().\n"
        "- Where: calc.py\n- Size: small (hours)\n- Done when: sub(5, 3) == 2\n")
    task_list = []
    for found in tasks.candidates(app, out):
        tasks.add_task(task_list, **found)
    titles = [t["title"] for t in task_list]
    assert titles[:3] == ["Fix failing CI (CI)", "#5 Login breaks on Safari", "Add subtraction"]
    assert "A PR" not in " ".join(titles)
    assert "handle strings (calc.py:2)" in titles
    assert any(t.startswith("Client-ready: CI on GitHub") for t in titles)
    assert not any("facts" in t for t in titles)
    assert tasks.add_task(task_list, "Add subtraction") is None          # no duplicates

    idea = task_list[2]
    text = tasks.brief(idea, app, branch="task/3-add-subtraction")
    assert "a sub() next to add()." in text and "- calc.py (named in the task)" in text
    assert "Done when\n- sub(5, 3) == 2" in text and "-m pytest -q`" in text
    assert "task/3-add-subtraction" in text and "Never delete, skip or weaken a test" in text
    assert tasks.related_files(app, {"title": "Handle strings in calc"}) == ["calc.py"]


def test_task_start_check_done(tmp_path):
    projects = tmp_path / "projects"
    app = make_repo(projects, "calc", PY_PROJECT)
    out = tmp_path / "work"
    out.mkdir()
    run("status", str(projects), "--offline", cwd=out)
    code, text = run("task", "add", "calc", "Add subtraction", "--done-when", "sub works", cwd=out)
    assert "Added task 1" in text

    (app / "calc.py").write_text("dirty\n")
    code, text = run("task", "start", "calc", "1", cwd=out)
    assert code != 0 and "uncommitted changes" in text
    git_in(app, "checkout", "--", "calc.py")

    code, text = run("task", "start", "calc", "1", cwd=out)
    assert code == 0, text
    assert "task/1-add-subtraction" in text and "claude \"Do the task described in" in text
    brief = (out / "proof_output" / "calc" / "tasks" / "T1.md").read_text()
    assert "Work on the branch `task/1-add-subtraction`" in brief

    code, text = run("task", "check", "calc", "1", cwd=out)
    assert code != 0 and "Nothing has changed yet" in text

    (app / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n"
                                 "    return a - b\n")
    git_in(app, "commit", "-qam", "Add sub")
    code, text = run("task", "check", "calc", "1", "--done", cwd=out)
    assert code == 0, text
    assert "1 commit(s), 1 file(s) changed" in text and "passed" in text
    assert "Task 1 marked done" in text
    task = json.loads((out / "proof_output" / "calc" / "tasks.json").read_text())[0]
    assert task["status"] == "done" and task["commit"]

    run("task", "add", "calc", "Remove the old test", cwd=out)
    run("task", "start", "calc", "2", cwd=out)
    git_in(app, "rm", "-q", "tests/test_calc.py")
    code, text = run("task", "check", "calc", "2", cwd=out)
    assert code != 0 and "tests deleted: tests/test_calc.py" in text


def test_failure_summary_explains_missing_packages():
    from proof.tasks import failure_summary
    output = "\n".join(["collecting ..."] + ["E   ModuleNotFoundError: No module named 'calc'"] * 3
                       + [f"ERROR tests/test_{i}.py" for i in range(20)] + ["20 errors"])
    summary = failure_summary(output)
    assert summary.count("No module named 'calc'") == 1                  # once, not 3 times
    assert "20 errors" in summary and "Hint: a package isn't installed" in summary


def test_new_project(tmp_path):
    out = tmp_path / "work"
    out.mkdir()
    code, text = run("new", "a tool that turns lecture notes into flashcards", "--provider",
                     "mock", "--where", str(tmp_path), cwd=out)
    assert code == 0, text
    app = tmp_path / "mockapp"
    for name in ["README.md", "PLAN.md", "pyproject.toml", "src/mockapp/__init__.py",
                 "tests/test_smoke.py", ".github/workflows/ci.yml", ".gitignore"]:
        assert (app / name).exists(), name
    readme = (app / "README.md").read_text()
    assert "## The problem\n(mock) a tool that turns lecture notes" in readme
    assert "## Results" in readme and "## Quick start" in readme
    log = subprocess.run(["git", "-C", str(app), "log", "--oneline"], capture_output=True,
                         text=True).stdout
    assert "Start mockapp (proof new)" in log
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=app, capture_output=True,
                           text=True)
    assert tests.returncode == 0, tests.stdout                     # the starter test passes
    task_list = json.loads((out / "proof_output" / "mockapp" / "tasks.json").read_text())
    assert [t["title"] for t in task_list] == ["Write the core function", "Add a test for it"]
    assert str(app) in (out / "proof_output" / "projects.txt").read_text()

    code, text = run("new", "same idea", "--provider", "mock", "--where", str(tmp_path),
                     "--name", "mockapp", cwd=out)
    assert code != 0 and "isn't empty" in text
    code, text = run("new", "a shop", "--no-ai", "--stack", "node", "--name", "shop",
                     "--where", str(tmp_path), cwd=out)
    assert code == 0, text
    assert json.loads((tmp_path / "shop" / "package.json").read_text())["scripts"]["test"] == \
        "node --test"
    assert "[add:" in (tmp_path / "shop" / "PLAN.md").read_text()
