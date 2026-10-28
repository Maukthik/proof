"""
scan.py - read a repo and summarise it for the LLM.

Main functions:
  get_repo(arg)       -> local Path (clones GitHub URLs)
  detect_stack(repo)  -> ["Python", "FastAPI", "Docker", ...]   (no LLM needed)
  scan_repo(repo)     -> one big text block: tree + stack + key files
  head_commit(repo)   -> current commit id, used for caching
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Folders we never look inside
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist",
    "build", ".next", ".idea", ".vscode", "target", ".mypy_cache", ".pytest_cache",
    "proof_output",
}

# Files that tell us the stack / how it's deployed - read these first
IMPORTANT_FILES = [
    "requirements.txt", "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Makefile", "CMakeLists.txt",
]

# File extension -> language
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".c": "C",
    ".cpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".kt": "Kotlin",
    ".swift": "Swift", ".ino": "Arduino", ".sql": "SQL", ".tf": "Terraform",
    ".ipynb": "Jupyter",
}
CODE_EXTENSIONS = set(LANGUAGES) | {".h", ".yml", ".yaml"}

# Python import name -> nice name, when it differs from the pip name
IMPORT_NAMES = {
    "sklearn": "scikit-learn", "cv2": "OpenCV", "PIL": "Pillow", "bs4": "BeautifulSoup",
    "faiss": "FAISS", "llama_index": "LlamaIndex", "google.generativeai": "Gemini API",
    "sentence_transformers": "Hugging Face", "keras": "Keras", "xgboost": "XGBoost",
    "gradio": "Gradio", "matplotlib": "matplotlib", "ollama": "Ollama",
}

# Package name (as written in requirements.txt / package.json) -> nice name
PACKAGES = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "streamlit": "Streamlit",
    "langchain": "LangChain", "langgraph": "LangGraph", "llama-index": "LlamaIndex",
    "chromadb": "Chroma", "pinecone": "Pinecone", "pinecone-client": "Pinecone",
    "faiss-cpu": "FAISS", "torch": "PyTorch", "tensorflow": "TensorFlow",
    "transformers": "Hugging Face", "sentence-transformers": "Hugging Face",
    "scikit-learn": "scikit-learn", "pandas": "pandas", "numpy": "NumPy",
    "anthropic": "Claude API", "openai": "OpenAI SDK", "boto3": "AWS",
    "redis": "Redis", "celery": "Celery", "sqlalchemy": "SQLAlchemy",
    "psycopg2": "PostgreSQL", "psycopg2-binary": "PostgreSQL", "pymongo": "MongoDB",
    "react": "React", "next": "Next.js", "vue": "Vue", "svelte": "Svelte",
    "tailwindcss": "Tailwind", "express": "Express", "prisma": "Prisma",
    "socket.io": "Socket.IO", "pytest": "pytest", "jest": "Jest",
    "contree-sdk": "Nebius ConTree", "groq": "Groq", "ollama": "Ollama",
    "google-generativeai": "Gemini API", "gradio": "Gradio", "httpx": "httpx",
}

# Folders that support the project but aren't the product itself
SIDE_DIRS = {
    "test", "tests", "testing", "spec", "bench", "benchmark", "benchmarks", "example",
    "examples", "demo", "demos", "docs", "doc", "fixtures", "samples", "sample",
    "scripts", "vendor", "third_party", "migrations", "notebooks_old",
}
# File names that are usually the heart of a project
ENTRYPOINTS = {"main.py", "app.py", "cli.py", "__main__.py", "server.py", "manage.py",
               "index.js", "index.ts", "main.go", "main.rs", "App.jsx", "App.tsx"}

MAX_TREE_LINES = 200     # paths listed in the file tree
MAX_FILE_CHARS = 6000    # max characters read from one file (README, configs)
MAX_CODE_CHARS = 2500    # per code file - the top (imports, docstring, main defs) says most
MAX_TOTAL_CHARS = 60000  # total code budget sent to the LLM


# ---------------------------------------------------------------------------
# Getting the repo
# ---------------------------------------------------------------------------

def get_repo(repo_arg):
    """Return a local Path to the repo. Clones it first if it's a URL."""
    if repo_arg.startswith(("http://", "https://", "git@")):
        # "https://github.com/you/my-app.git" -> "my-app"
        name = repo_arg.rstrip("/").split("/")[-1].removesuffix(".git")
        target = Path(tempfile.mkdtemp(prefix="proof_")) / name
        print(f"Cloning {repo_arg} ...")
        result = subprocess.run(["git", "clone", "--quiet", repo_arg, str(target)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"git clone failed:\n{result.stderr}")
        return target

    path = Path(repo_arg).expanduser().resolve()
    if not path.is_dir():
        sys.exit(f"Not a folder: {path}")
    return path


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def list_files(repo):
    """All files in the repo, skipping junk folders. Paths are relative to repo."""
    files = []
    for path in sorted(repo.rglob("*")):
        relative = path.relative_to(repo)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_file():
            files.append(relative)
    return files


def notebook_to_text(raw):
    """Jupyter notebook JSON -> plain text of its cells (outputs dropped, they're huge)."""
    try:
        cells = json.loads(raw).get("cells", [])
    except json.JSONDecodeError:
        return ""
    parts = []
    for cell in cells:
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else source
        if source.strip():
            parts.append(f"# [{cell.get('cell_type', 'cell')} cell]\n{source.strip()}")
    return "\n\n".join(parts)


def read_text(path, limit=MAX_FILE_CHARS):
    """Read a file as text, cut to `limit` characters. Returns '' for binary files."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    if path.suffix == ".ipynb":
        text = notebook_to_text(text)
    if len(text) > limit:
        text = text[:limit] + "\n... [cut]"
    return text


def git(repo, *args):
    """Run a git command in the repo, return its output ('' if it fails)."""
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def head_commit(repo):
    return git(repo, "rev-parse", "HEAD")


def git_stats(repo):
    """Commit count and date range - evidence of sustained work."""
    count = git(repo, "rev-list", "--count", "HEAD")
    if not count:
        return "No git history found."
    first = git(repo, "log", "--reverse", "--format=%ad", "--date=short").splitlines()[:1]
    last = git(repo, "log", "-1", "--format=%ad", "--date=short")
    return f"{count} commits, from {first[0] if first else '?'} to {last}."


# ---------------------------------------------------------------------------
# Stack detection (plain rules, no LLM)
# ---------------------------------------------------------------------------

def packages_in_requirements(text):
    """'fastapi>=0.1  # web' -> 'fastapi'"""
    names = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.append(re.split(r"[<>=!~\[; ]", line)[0].strip().lower())
    return names


def packages_in_pyproject(text):
    """Runtime dependencies from pyproject.toml - NOT dev/test extras."""
    try:
        import tomllib                      # Python 3.11+
        data = tomllib.loads(text)
    except Exception:                       # older Python or broken file: rough fallback
        text = text.lower()
        return [p for p in PACKAGES if re.search(rf'["\s]{re.escape(p)}[\s"<>=~\[]', text)]

    project = data.get("project", {})
    deps = list(project.get("dependencies", []))
    for group, items in project.get("optional-dependencies", {}).items():
        if not re.search(r"dev|test|lint|doc|bench", group.lower()):
            deps += items
    deps += list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
    return packages_in_requirements("\n".join(deps))


def packages_in_package_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    return [name.lower() for name in deps]


def packages_in_imports(code):
    """Find top-level `import x` / `from x import y` in Python code, return nice names.
    Indented imports (inside functions) are skipped: those are usually optional
    integrations the project *supports*, not what it's built with."""
    found = set()
    for name in re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", code, flags=re.MULTILINE):
        top = name.split(".")[0]
        if name.startswith("google.generativeai"):
            found.add("Gemini API")
        elif top.startswith("langchain"):         # langchain_openai, langchain_core ...
            found.add("LangChain")
        elif top in IMPORT_NAMES:
            found.add(IMPORT_NAMES[top])
        elif top.lower().replace("_", "-") in PACKAGES:
            found.add(PACKAGES[top.lower().replace("_", "-")])
    return found


def detect_stack(repo, files=None):
    """Guess the tech stack from file types, dependency files and Python imports."""
    files = files if files is not None else list_files(repo)
    # Tests, benchmarks and examples often use other frameworks - don't count them
    main_files = [f for f in files if not is_side_folder(f)]
    if any(f.suffix in LANGUAGES for f in main_files):   # else: all code is in side folders
        files = main_files
    stack = set()

    python_files = [f for f in files if f.suffix in (".py", ".ipynb")][:300]
    for f in python_files:
        stack |= packages_in_imports(read_text(repo / f, limit=200_000))

    for f in files:
        if f.suffix in LANGUAGES:
            stack.add(LANGUAGES[f.suffix])
        if f.suffix == ".ipynb":
            stack.add("Python")

        packages = []
        if f.name == "requirements.txt":
            packages = packages_in_requirements(read_text(repo / f, limit=100_000))
        elif f.name == "package.json":
            packages = packages_in_package_json(read_text(repo / f, limit=100_000))
        elif f.name == "pyproject.toml":
            packages = packages_in_pyproject(read_text(repo / f, limit=100_000))
        for p in packages:
            if p in PACKAGES:
                stack.add(PACKAGES[p])

        if f.name == "Dockerfile" or f.name.startswith("docker-compose"):
            stack.add("Docker")
        if f.name == "go.mod":
            stack.add("Go")
        if ".github" in f.parts and "workflows" in f.parts:
            stack.add("GitHub Actions")
        if f.suffix in (".yml", ".yaml") and "kind: Deployment" in read_text(repo / f):
            stack.add("Kubernetes")

    return sorted(stack)


# ---------------------------------------------------------------------------
# The full scan
# ---------------------------------------------------------------------------

def is_side_folder(f):
    """True for files under tests/, bench/, examples/ ... - not the main product code."""
    return any(part.lower() in SIDE_DIRS for part in f.parts[:-1])


def code_priority(f):
    """Lower number = read earlier."""
    if is_side_folder(f):
        return 3                                  # tests, benchmarks, examples: last
    if f.name in ENTRYPOINTS or (f.parts[0] == "src" and len(f.parts) > 1):
        return 0                                  # cli.py, main.py, anything in src/
    if f.suffix in (".yml", ".yaml"):
        return 2                                  # config, after real code
    return 1


def pick_files_to_read(files):
    """README, dependency files, up to 2 CI workflows, then code - main code first."""
    readme = [f for f in files if f.name.lower().startswith("readme")][:1]
    important = [f for f in files if f.name in IMPORTANT_FILES
                 and len(f.parts) <= 2 and not is_side_folder(f)]   # root, or backend/...
    workflows = [f for f in files if ".github" in f.parts and f.suffix in (".yml", ".yaml")][:2]

    already = set(readme + important + workflows)
    code = [f for f in files if f.suffix in CODE_EXTENSIONS and f not in already]
    code.sort(key=lambda f: (code_priority(f), len(f.parts), f.name))

    return readme + important + workflows + code


def summarise_tree(files):
    """File tree, but big side folders (bench/, tests/ ...) shrink to one line each."""
    lines, side_counts = [], {}
    for f in files:
        if is_side_folder(f):
            top = f.parts[0] + "/"
            side_counts[top] = side_counts.get(top, 0) + 1
        else:
            lines.append(str(f))
    if len(lines) > MAX_TREE_LINES:
        lines = lines[:MAX_TREE_LINES] + [f"... and {len(lines) - MAX_TREE_LINES} more files"]
    lines += [f"{folder}  ({count} files: tests/benchmarks/examples)"
              for folder, count in sorted(side_counts.items())]
    return "\n".join(lines)


def scan_repo(repo):
    """Build one big text summary of the repo for the LLM."""
    files = list_files(repo)
    tree = summarise_tree(files)

    parts = [
        f"# Repo name: {repo.name}",
        f"# Detected stack: {', '.join(detect_stack(repo, files)) or 'unknown'}",
        f"# Git history: {git_stats(repo)}",
        f"# File tree ({len(files)} files):\n{tree}",
    ]

    used = 0
    not_read = []
    for f in pick_files_to_read(files):
        is_code = f.suffix in CODE_EXTENSIONS and f.suffix not in (".yml", ".yaml")
        if f.name.lower().startswith("readme") and len(f.parts) == 1:
            text = readme_extract(read_text(repo / f, limit=1_000_000))
        else:
            text = read_text(repo / f, limit=MAX_CODE_CHARS if is_code else MAX_FILE_CHARS)
        if not text.strip():
            continue
        if used + len(text) > MAX_TOTAL_CHARS:
            not_read.append(f)
            continue
        parts.append(f"# File: {f}\n```\n{text}\n```")
        used += len(text)

    # Files that didn't fit: still give one line each, so the LLM knows they exist
    summaries = [f"- {f}: {first_line_summary(repo / f)}" for f in not_read
                 if not is_side_folder(f) and first_line_summary(repo / f)][:60]
    if summaries:
        parts.append("# Other main files (not shown, first line of each):\n" + "\n".join(summaries))

    return "\n\n".join(parts)


RESULT_HEADINGS = re.compile(r"result|benchmark|evaluat|performance|metric|impact|demo|accuracy|numbers",
                             re.IGNORECASE)


def readme_extract(text, intro_chars=3500, section_chars=3500, total_chars=11000):
    """Long READMEs: keep the intro, plus any Results/Benchmark/Demo sections wherever they are.
    Real numbers usually live deep in a README - exactly what a case study needs."""
    if len(text) <= intro_chars + section_chars:
        return text
    sections = re.split(r"(?m)^(?=#{2,3} )", text)
    kept = [sections[0][:intro_chars]]
    for section in sections[1:]:
        heading = section.splitlines()[0]
        if RESULT_HEADINGS.search(heading) and sum(map(len, kept)) < total_chars:
            kept.append(section[:section_chars] + ("\n... [cut]" if len(section) > section_chars else ""))
    return "\n".join(kept)


def first_line_summary(path):
    """First line of a file's docstring or top comment - its own one-line description."""
    text = read_text(path, limit=1500)
    match = re.search(r'^\s*(?:"""|\'\'\'|//+|#+(?!!)|/\*+)\s*(\S[^\n]*)', text)
    return match.group(1).strip().rstrip('"\'*/').strip()[:120] if match else ""
