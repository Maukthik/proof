"""
jobpost.py - get the text of a job post from a file, a web page, or a paste.

  read_job("upwork_job.txt")                -> text of the file
  read_job("https://boards.greenhouse...")  -> text of the job on that page
  read_job("-")                             -> whatever is pasted / piped in

Most job boards put the post in a schema.org "JobPosting" block for Google; we use that
when it's there, and otherwise take the page's visible text. Pages behind a login
(Upwork, most of LinkedIn) can't be read - then we say so and suggest pasting.
"""

import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

MIN_WORDS = 40          # less than this isn't a job post, it's a login wall
MAX_CHARS = 15000       # job posts are short; anything longer is page clutter


def read_job(arg):
    """Return (job_text, short_name). short_name names the pitch file."""
    if arg == "-":
        if sys.stdin.isatty():
            print("Paste the job post, then press Ctrl-D (Ctrl-Z then Enter on Windows):")
        text = sys.stdin.read().strip()
        if not text:
            sys.exit("Nothing was pasted.")
        return text, slug(text.split("\n")[0]) or datetime.now().strftime("job-%Y%m%d-%H%M")

    if arg.startswith(("http://", "https://")):
        text, is_job_posting = job_from_page(fetch(arg))
        if not is_job_posting and len(text.split()) < MIN_WORDS:
            sys.exit("Couldn't find a job post on that page (sites like Upwork and LinkedIn "
                     "need a login).\nCopy the post's text and paste it instead:  proof pitch -")
        return text[:MAX_CHARS], slug(arg.rstrip("/").split("/")[-1]) or "job"

    path = Path(arg)
    if not path.is_file():
        sys.exit(f"No such file: {arg}  (give a text file, a URL, or - to paste)")
    return path.read_text(encoding="utf-8"), path.stem


def slug(text, max_words=6):
    """'Need a FastAPI dev for RAG!' -> 'need-a-fastapi-dev-for-rag'"""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:max_words])


def fetch(url):
    try:
        response = requests.get(url, timeout=30,
                                headers={"User-Agent": "Mozilla/5.0 (proof job reader)"})
    except requests.RequestException as error:
        sys.exit(f"Couldn't open {url}: {error}")
    if response.status_code != 200:
        sys.exit(f"Couldn't open {url} (HTTP {response.status_code}). "
                 "Copy the post's text and paste it instead:  proof pitch -")
    return response.text


def job_from_page(html):
    """(text, True) from the page's JobPosting block, or (visible text, False) without one."""
    parser = PageText()
    parser.feed(html)
    for block in parser.json_blocks:
        posting = find_job_posting(block)
        if posting:
            description = PageText.text_of(posting.get("description", ""))
            return f"{posting.get('title', '')}\n\n{description}".strip(), True
    return parser.text(), False


def find_job_posting(raw_json):
    """The JobPosting object inside a JSON-LD block, or None. Blocks can be a single
    object, a list, or an {"@graph": [...]} wrapper."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        items = data.get("@graph", [data])
    else:
        items = data if isinstance(data, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            return item
    return None


class PageText(HTMLParser):
    """Collects a page's visible text, and its JSON-LD blocks on the side."""
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "header"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts, self.json_blocks = [], []
        self.skipping = 0             # >0 while inside <script>, <nav> ...
        self.in_json = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and ("type", "application/ld+json") in attrs:
            self.in_json = True
            self.json_blocks.append("")
        if tag in self.SKIP:
            self.skipping += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        if tag == "script":
            self.in_json = False

    def handle_data(self, data):
        if self.in_json:
            self.json_blocks[-1] += data
        elif not self.skipping:
            self.parts.append(data)

    def text(self):
        lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(self.parts).split("\n"))
        return "\n".join(line for line in lines if line)

    @staticmethod
    def text_of(html):
        """Plain text of an HTML snippet (a JobPosting description is HTML)."""
        parser = PageText()
        parser.feed(html)
        return parser.text()
