"""
Tests for the proof tool. Run from the proof folder:   python -m pytest -q
No LLM or internet needed - uses the mock provider and a tiny fake HTTP server.
"""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

TOOL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL))

import llm                                             # noqa: E402
from lint import lint_pitch                            # noqa: E402
from match import rank_projects                        # noqa: E402
from portfolio import build_site                       # noqa: E402
from scan import detect_stack, scan_repo               # noqa: E402


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
    (repo / "CHANGE.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "change"], check=True)


def run(*args, cwd):
    """Run the CLI and return (exit code, output)."""
    result = subprocess.run([sys.executable, str(TOOL / "proof.py"), *args],
                            cwd=cwd, capture_output=True, text=True)
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
    assert "1 commits" in text
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
    assert code != 0 and "Run `python proof.py case" in out


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
    from portfolio import to_html
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

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAPI.last_request = (self.path, dict(self.headers), body)
        if self.path == "/v1/chat/completions":
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

def test_workflow_is_valid_yaml():
    wf = yaml.safe_load((TOOL / "templates" / "proof-workflow.yml").read_text())
    steps = wf["jobs"]["case-study"]["steps"]
    assert wf["permissions"]["contents"] == "write"
    assert any("proof.py case ." in s.get("run", "") for s in steps)
