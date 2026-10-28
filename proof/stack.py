"""
stack.py - what a project is built with, from plain rules (no LLM).

  detect_stack(repo, files) -> ["Python", "FastAPI", "Docker", ...]

Sources, most reliable first: dependency files (requirements.txt, pyproject.toml,
package.json, go.mod, Cargo.toml, pom.xml / build.gradle, Gemfile, composer.json),
top-level Python imports, and which languages the code is written in.
"""

import json
import re

# File extension -> language
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".c": "C",
    ".cpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".kt": "Kotlin",
    ".swift": "Swift", ".ino": "Arduino", ".sql": "SQL", ".tf": "Terraform",
    ".ipynb": "Jupyter", ".dart": "Dart", ".scala": "Scala", ".vue": "Vue", ".svelte": "Svelte",
}

# Python import name -> nice name, when it differs from the pip name
IMPORT_NAMES = {
    "sklearn": "scikit-learn", "cv2": "OpenCV", "PIL": "Pillow", "bs4": "BeautifulSoup",
    "faiss": "FAISS", "llama_index": "LlamaIndex", "google.generativeai": "Gemini API",
    "google.genai": "Gemini API", "sentence_transformers": "Hugging Face", "keras": "Keras",
    "xgboost": "XGBoost", "gradio": "Gradio", "matplotlib": "matplotlib", "ollama": "Ollama",
    "sqlite3": "SQLite", "tkinter": "Tkinter", "google.adk": "Google ADK",
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
    "redis": "Redis", "celery": "Celery", "sqlalchemy": "SQLAlchemy", "sqlmodel": "SQLModel",
    "psycopg2": "PostgreSQL", "psycopg2-binary": "PostgreSQL", "psycopg": "PostgreSQL",
    "asyncpg": "PostgreSQL", "pymongo": "MongoDB", "alembic": "Alembic",
    "react": "React", "next": "Next.js", "vue": "Vue", "svelte": "Svelte",
    "tailwindcss": "Tailwind", "express": "Express", "prisma": "Prisma",
    "socket.io": "Socket.IO", "pytest": "pytest", "jest": "Jest",
    "contree-sdk": "Nebius ConTree", "groq": "Groq", "ollama": "Ollama",
    "google-generativeai": "Gemini API", "google-genai": "Gemini API", "gradio": "Gradio",
    "httpx": "httpx", "peft": "PEFT", "trl": "TRL", "vllm": "vLLM",
    "bitsandbytes": "bitsandbytes", "google-adk": "Google ADK", "pydantic": "Pydantic",
    "uvicorn": "Uvicorn", "selenium": "Selenium", "playwright": "Playwright", "scrapy": "Scrapy",
    "stripe": "Stripe", "twilio": "Twilio", "supabase": "Supabase", "firebase-admin": "Firebase",
    "mysql-connector-python": "MySQL", "pymysql": "MySQL", "opencv-python": "OpenCV",
    "werkzeug": "Werkzeug", "jinja2": "Jinja", "click": "Click", "typer": "Typer",
    "rich": "Rich", "aiohttp": "aiohttp", "websockets": "WebSockets",
    "djangorestframework": "Django REST",
    "@prisma/client": "Prisma", "zod": "Zod", "vitest": "Vitest", "recharts": "Recharts",
    "nodemailer": "Nodemailer", "next-auth": "NextAuth", "mongoose": "MongoDB",
    "@supabase/supabase-js": "Supabase", "firebase": "Firebase", "three": "Three.js",
    "@tanstack/react-query": "React Query", "redux": "Redux", "@reduxjs/toolkit": "Redux",
    "react-native": "React Native", "expo": "Expo", "electron": "Electron",
    "graphql": "GraphQL", "@apollo/client": "Apollo", "socket.io-client": "Socket.IO",
    "@anthropic-ai/sdk": "Claude API", "ai": "Vercel AI SDK", "playwright-core": "Playwright",
    "@playwright/test": "Playwright", "cypress": "Cypress", "vite": "Vite",
    "@angular/core": "Angular", "nuxt": "Nuxt", "@nestjs/core": "NestJS", "fastify": "Fastify",
    "drizzle-orm": "Drizzle", "@trpc/server": "tRPC", "contentlayer": "Contentlayer",
}

# go.mod module path (prefix) -> nice name
GO_MODULES = {
    "github.com/gin-gonic/gin": "Gin", "github.com/labstack/echo": "Echo",
    "github.com/gofiber/fiber": "Fiber", "github.com/go-chi/chi": "chi",
    "github.com/gorilla/mux": "Gorilla", "github.com/spf13/cobra": "Cobra",
    "github.com/spf13/viper": "Viper", "gorm.io/gorm": "GORM", "google.golang.org/grpc": "gRPC",
    "github.com/charmbracelet/bubbletea": "Bubble Tea",
    "github.com/charmbracelet/lipgloss": "Lip Gloss",
    "github.com/charmbracelet/glamour": "Glamour", "github.com/jackc/pgx": "PostgreSQL",
    "github.com/lib/pq": "PostgreSQL", "github.com/redis/go-redis": "Redis",
    "github.com/aws/aws-sdk-go": "AWS", "go.mongodb.org/mongo-driver": "MongoDB",
    "github.com/stretchr/testify": "testify", "github.com/prometheus/client_golang": "Prometheus",
}

# Cargo.toml dependency name -> nice name
CRATES = {
    "tokio": "Tokio", "serde": "Serde", "clap": "clap", "axum": "Axum", "actix-web": "Actix",
    "rocket": "Rocket", "reqwest": "reqwest", "sqlx": "SQLx", "diesel": "Diesel",
    "tauri": "Tauri", "bevy": "Bevy", "wasm-bindgen": "WebAssembly", "regex": "regex",
    "rayon": "Rayon", "tonic": "gRPC", "crossbeam-channel": "crossbeam",
}

# Text in pom.xml / build.gradle / libs.versions.toml -> nice name (JVM and Android)
JVM_MARKERS = {
    "spring-boot": "Spring Boot", "spring-boot-starter-data-jpa": "JPA / Hibernate",
    "spring-boot-starter-security": "Spring Security", "thymeleaf": "Thymeleaf",
    "mysql-connector": "MySQL", "postgresql": "PostgreSQL", "com.h2database": "H2",
    "junit": "JUnit", "lombok": "Lombok", "com.android.application": "Android",
    "androidx.compose": "Jetpack Compose", "androidx.room": "Room", "hilt": "Hilt",
    "retrofit": "Retrofit", "kotlinx-coroutines": "Kotlin Coroutines", "okhttp": "OkHttp",
    "androidx.work": "WorkManager", "kafka": "Kafka", "maven-plugin": "Maven",
}

# Gemfile / composer.json package -> nice name
GEMS = {"rails": "Ruby on Rails", "sinatra": "Sinatra", "rspec": "RSpec", "sidekiq": "Sidekiq"}
COMPOSER = {"laravel/framework": "Laravel", "symfony/": "Symfony", "phpunit/phpunit": "PHPUnit"}

DEPENDENCY_FILES = {"requirements.txt", "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
                    "pom.xml", "build.gradle", "build.gradle.kts", "libs.versions.toml",
                    "Gemfile", "composer.json"}

# Every nice name we can report (the job matcher treats these as tech terms)
ALL_NAMES = (set(LANGUAGES.values()) | set(IMPORT_NAMES.values()) | set(PACKAGES.values())
             | set(GO_MODULES.values()) | set(CRATES.values()) | set(JVM_MARKERS.values())
             | set(GEMS.values()) | set(COMPOSER.values()))

# Internals of a framework, often pinned in requirements.txt: with the framework named,
# listing them too is noise. (Not React under Next.js: clients search for React by name.)
PART_OF = {"Flask": {"Werkzeug", "Jinja", "Click"}}

# Config files written in a language don't make it "a JavaScript project"
CONFIG_FILE = re.compile(r"\.config\.[cm]?[jt]s$|^\.|rc\.[cm]?js$")
MIN_LANGUAGE_SHARE = 0.10    # a language with fewer code files than this is a side detail


# ---------------------------------------------------------------------------
# Reading dependency files
# ---------------------------------------------------------------------------

def packages_in_requirements(text):
    """'fastapi>=0.1  # web' -> 'fastapi'"""
    names = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.append(re.split(r"[<>=!~\[; ]", line)[0].strip().lower())
    return names


def load_toml(text):
    """Parsed TOML, or None (broken file, or Python older than 3.11)."""
    try:
        import tomllib
        return tomllib.loads(text)
    except Exception:
        return None


def packages_in_pyproject(text):
    """Runtime dependencies from pyproject.toml - NOT dev/test extras."""
    data = load_toml(text)
    if data is None:                       # rough fallback: look for known names
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


def names_in_go_mod(text):
    modules = re.findall(r"^\s*(?:require\s+)?([\w.\-]+\.[\w]+/[\w.\-/]+)\s+v", text, re.MULTILINE)
    return {name for module in modules for prefix, name in GO_MODULES.items()
            if module.startswith(prefix)}


def names_in_cargo(text):
    data = load_toml(text) or {}
    deps = {**data.get("dependencies", {}), **data.get("workspace", {}).get("dependencies", {})}
    return {CRATES[name] for name in deps if name in CRATES}


def names_by_marker(text, markers):
    """Plain substring rules, for build files too varied to parse (Gradle, Maven ...)."""
    text = text.lower()
    return {name for marker, name in markers.items() if marker in text}


def names_in_dependency_file(name, text):
    """Nice names from one dependency file, or an empty set if it isn't one."""
    if name == "requirements.txt":
        return {PACKAGES[p] for p in packages_in_requirements(text) if p in PACKAGES}
    if name == "pyproject.toml":
        return {PACKAGES[p] for p in packages_in_pyproject(text) if p in PACKAGES}
    if name == "package.json":
        return {PACKAGES[p] for p in packages_in_package_json(text) if p in PACKAGES}
    if name == "go.mod":
        return {"Go"} | names_in_go_mod(text)
    if name == "Cargo.toml":
        return names_in_cargo(text)
    if name in ("pom.xml", "build.gradle", "build.gradle.kts", "libs.versions.toml"):
        return names_by_marker(text, JVM_MARKERS) | ({"Maven"} if name == "pom.xml" else {"Gradle"})
    if name == "Gemfile":
        return {nice for gem, nice in GEMS.items() if re.search(rf"gem ['\"]{gem}['\"]", text)}
    if name == "composer.json":
        return names_by_marker(text, COMPOSER)
    return set()


def packages_in_imports(code):
    """Find top-level `import x` / `from x import y` in Python code, return nice names.
    Indented imports (inside functions) are skipped: those are usually optional
    integrations the project *supports*, not what it's built with."""
    found = set()
    for name in re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", code, flags=re.MULTILINE):
        top = name.split(".")[0]
        dotted = [key for key in IMPORT_NAMES if "." in key and (name + ".").startswith(key + ".")]
        if dotted:                                # google.generativeai, google.adk
            found.add(IMPORT_NAMES[dotted[0]])
        elif top.startswith("langchain"):         # langchain_openai, langchain_core ...
            found.add("LangChain")
        elif top in IMPORT_NAMES:
            found.add(IMPORT_NAMES[top])
        elif top.lower().replace("_", "-") in PACKAGES:
            found.add(PACKAGES[top.lower().replace("_", "-")])
    return found


# ---------------------------------------------------------------------------
# The whole stack
# ---------------------------------------------------------------------------

def main_languages(files):
    """Languages with a real share of the code. One Homebrew formula doesn't make
    ripgrep a Ruby project, and tailwind.config.js doesn't make an app JavaScript."""
    counts = {}
    for f in files:
        if f.suffix in LANGUAGES and not CONFIG_FILE.search(f.name):
            counts[LANGUAGES[f.suffix]] = counts.get(LANGUAGES[f.suffix], 0) + 1
    total = sum(counts.values())
    return {lang for lang, count in counts.items()
            if count >= MIN_LANGUAGE_SHARE * total or count == max(counts.values())}


def detect(repo, files, read_text, is_side):
    """Guess the tech stack. `is_side(f)` says if f is a test/example/benchmark file:
    those often use other frameworks, so they don't count (unless that's all there is)."""
    main_files = [f for f in files if not is_side(f)]
    if any(f.suffix in LANGUAGES for f in main_files):
        files = main_files
    stack = main_languages(files)
    if any(f.suffix == ".ipynb" for f in files):
        stack.add("Python")

    python_files = [f for f in files if f.suffix in (".py", ".ipynb")][:300]
    for f in python_files:
        stack |= packages_in_imports(read_text(repo / f, limit=200_000))

    for f in files:
        if f.name in DEPENDENCY_FILES:
            stack |= names_in_dependency_file(f.name, read_text(repo / f, limit=200_000))
        if f.name == "Dockerfile" or f.name.startswith("docker-compose"):
            stack.add("Docker")
        if ".github" in f.parts and "workflows" in f.parts:
            stack.add("GitHub Actions")
        if f.suffix in (".yml", ".yaml") and "kind: Deployment" in read_text(repo / f):
            stack.add("Kubernetes")
        if f.suffix == ".tf":
            stack.add("Terraform")
    for framework, parts in PART_OF.items():
        if framework in stack:
            stack -= parts
    return sorted(stack)
