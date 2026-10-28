"""
feeds.py - read job posts from public job boards, for `proof apply`.

Built-in boards (free, no login, no key):
  remotive      Remotive's API: software-dev jobs (Remotive shows them 24 hours late)
  remoteok      Remote OK's API: the latest ~100 remote jobs
  wwr           We Work Remotely's RSS feed, all categories
  hn-freelance  this month's Hacker News "Freelancer? Seeking freelancer?" thread -
                only the "SEEKING FREELANCER" posts (clients looking for someone)
  hn            this month's Hacker News "Who is hiring?" thread (mostly full-time jobs)
Or any RSS / Atom feed URL, e.g. a saved search on a board that offers one.

Upwork closed its RSS feeds in 2024 and LinkedIn needs a login: copy those posts and
use `proof pitch -` instead.

The boards ask to be credited and not hammered: every job keeps its link and its board's
name, and each board is fetched at most once every CACHE_HOURS (Remotive asks for no
more than 4 times a day).

A job is a dict: {"id", "board", "title", "company", "url", "text", "posted", "where"}.
"""

import json
import time
import xml.etree.ElementTree as ElementTree
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .jobpost import PageText

REMOTIVE = "https://remotive.com/api/remote-jobs?category=software-dev"
REMOTEOK = "https://remoteok.com/api"
WWR = "https://weworkremotely.com/remote-jobs.rss"
HN_THREADS = ("https://hn.algolia.com/api/v1/search_by_date"
              "?tags=story,author_whoishiring&hitsPerPage=20")
HN_ITEM = "https://hn.algolia.com/api/v1/items/{}"
# The monthly threads posted by the "whoishiring" account
HN_TITLES = {"hn": "Ask HN: Who is hiring?",
             "hn-freelance": "Ask HN: Freelancer? Seeking freelancer?"}

BOARDS = ["remotive", "remoteok", "wwr", "hn-freelance", "hn"]
DEFAULT_BOARDS = ["remotive", "remoteok", "wwr", "hn-freelance"]
BOARD_NAMES = {"remotive": "Remotive", "remoteok": "Remote OK", "wwr": "We Work Remotely",
               "hn-freelance": "Hacker News (freelance)", "hn": "Hacker News"}
CACHE_HOURS = 6


class FeedError(Exception):
    """A board couldn't be read. `proof apply` warns and carries on with the others."""


def read_board(board, cache_dir, refresh=False):
    """(jobs on one board, True if they came from the cache). `board` is a built-in name
    or a feed URL. A copy saved less than CACHE_HOURS ago is used unless refresh."""
    cache = Path(cache_dir) / f"{cache_name(board)}.json"
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < CACHE_HOURS * 3600:
        return json.loads(cache.read_text(encoding="utf-8")), True
    if board == "remotive":
        jobs = remotive_jobs(get_json(REMOTIVE))
    elif board == "remoteok":
        jobs = remoteok_jobs(get_json(REMOTEOK))
    elif board == "wwr":
        jobs = rss_jobs("wwr", get(WWR))
    elif board in HN_TITLES:
        jobs = hn_jobs(board)
    elif board.startswith(("http://", "https://")):
        jobs = rss_jobs(board, get(board))
    else:
        raise FeedError(f"unknown board '{board}' (use {', '.join(BOARDS)}, or a feed URL)")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(jobs), encoding="utf-8")
    return jobs, False


def cache_name(board):
    """'remotive' -> 'remotive'; a URL -> a safe file name."""
    return "".join(c if c.isalnum() else "-" for c in board)[:80]


def get(url):
    try:
        response = requests.get(url, timeout=30,
                                headers={"User-Agent": "Mozilla/5.0 (proof job reader)"})
    except requests.RequestException as error:
        # requests' own message is several lines of pool details; its kind says enough
        raise FeedError(f"couldn't reach {url} ({type(error).__name__})") from None
    if response.status_code != 200:
        raise FeedError(f"{url} answered HTTP {response.status_code}")
    return response.text


def get_json(url):
    try:
        return json.loads(get(url))
    except json.JSONDecodeError:
        raise FeedError(f"{url} didn't send JSON") from None


def make_job(board, job_id, title, company, url, html, posted, where=""):
    return {"id": f"{board}:{job_id}", "board": board, "title": (title or "").strip(),
            "company": (company or "").strip(), "url": url or "",
            "text": PageText.text_of(html or ""), "posted": (posted or "")[:10],
            "where": (where or "").strip()}


# ---------------------------------------------------------------------------
# One reader per board. Each takes what the board sent, so tests can use saved copies.
# ---------------------------------------------------------------------------

def remotive_jobs(data):
    """{"job-count": n, "jobs": [{"id", "title", "company_name", "url", "description",
    "publication_date", "candidate_required_location", "tags", ...}]}"""
    jobs = []
    for job in data.get("jobs", []):
        tags = ", ".join(job.get("tags") or [])
        html = (job.get("description") or "") + (f"<p>Tags: {tags}</p>" if tags else "")
        jobs.append(make_job("remotive", job.get("id"), job.get("title"),
                             job.get("company_name"), job.get("url"), html,
                             job.get("publication_date"), job.get("candidate_required_location")))
    return jobs


def remoteok_jobs(data):
    """A list: first a legal notice, then jobs {"id", "position", "company", "tags",
    "description", "url", "date", "location", ...}."""
    jobs = []
    for job in data if isinstance(data, list) else []:
        if not isinstance(job, dict) or not job.get("position"):
            continue                                       # the legal notice
        tags = ", ".join(job.get("tags") or [])
        html = (job.get("description") or "") + (f"<p>Tags: {tags}</p>" if tags else "")
        url = job.get("url") or f"https://remoteok.com/remote-jobs/{job.get('id')}"
        jobs.append(make_job("remoteok", job.get("id"), job.get("position"), job.get("company"),
                             url, html, job.get("date"), job.get("location")))
    return jobs


def rss_jobs(board, xml_text):
    """Items of an RSS 2.0 feed, or entries of an Atom feed. We Work Remotely titles
    read "Company: Job title"."""
    # A feed never needs a DTD; refusing one blocks entity tricks (XXE, "billion laughs")
    # without needing defusedxml
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise FeedError(f"{board} declares a DTD - not a normal feed, skipped")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        raise FeedError(f"{board} isn't an RSS or Atom feed") from None
    jobs = []
    for item in root.iter():
        if local_name(item.tag) not in ("item", "entry"):
            continue
        fields = {local_name(child.tag): child for child in item}

        def text(name):
            return (fields[name].text or "") if name in fields else ""

        title, company = text("title"), ""
        if board == "wwr" and ": " in title:
            company, _, title = title.partition(": ")
        link = text("link") or (fields["link"].get("href", "") if "link" in fields else "")
        html = text("description") or text("encoded") or text("content") or text("summary")
        extra = [f"{name.title()}: {text(name)}" for name in ("region", "skills", "type")
                 if text(name)]                              # We Work Remotely adds these
        if extra:
            html += "".join(f"<p>{line}</p>" for line in extra)
        jobs.append(make_job(board, text("guid") or text("id") or link, title, company, link,
                             html, feed_date(text("pubDate") or text("published")
                                             or text("updated")), text("region")))
    return jobs


def local_name(tag):
    """'{http://www.w3.org/2005/Atom}entry' -> 'entry'"""
    return tag.rsplit("}", 1)[-1]


def feed_date(value):
    """'Tue, 27 Oct 2026 10:00:00 +0000' (RSS) or '2026-10-27T10:00:00Z' (Atom) -> '2026-10-27'"""
    value = value.strip()
    if value[:4].isdigit():
        return value[:10]
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def hn_jobs(board):
    """Find this month's thread, then read its top-level comments: one post each."""
    title = HN_TITLES[board]
    threads = [hit for hit in get_json(HN_THREADS).get("hits", [])
               if (hit.get("title") or "").startswith(title)]
    if not threads:
        return []
    return hn_thread_jobs(board, get_json(HN_ITEM.format(threads[0]["objectID"])))


def hn_thread_jobs(board, thread):
    """Top-level comments of a thread. In the freelance thread only "SEEKING FREELANCER"
    posts are clients; the "SEEKING WORK" ones are other freelancers."""
    jobs = []
    for comment in thread.get("children", []):
        text = PageText.text_of(comment.get("text") or "")
        if not text:
            continue                                       # deleted
        first_line = text.split("\n")[0]
        if board == "hn-freelance":
            if not first_line.upper().startswith("SEEKING FREELANCER"):
                continue
            title, company = first_line[len("SEEKING FREELANCER"):].strip(" -|:"), ""
        else:
            # "Acme | Senior Python Engineer | Remote | $150k": company first
            parts = [part.strip() for part in first_line.split("|")]
            company = parts[0] if len(parts) > 1 else ""
            title = " | ".join(parts[1:3]) if len(parts) > 1 else first_line
        jobs.append(make_job(board, comment.get("id"), title[:100], company,
                             f"https://news.ycombinator.com/item?id={comment.get('id')}",
                             comment.get("text"), comment.get("created_at")))
    return jobs
