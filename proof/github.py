"""
github.py - the few GitHub API calls proof makes (status, issues as tasks).

Public repos need no token. For private repos, or more than 60 requests an hour, set
GITHUB_TOKEN (a fine-grained token with read-only access is enough).
"""

import os

import requests

GITHUB_API = "https://api.github.com"     # GITHUB_API_URL overrides it (GitHub Enterprise)


class GitHubError(Exception):
    """GitHub couldn't be asked (no network, blocked, or the hourly limit is used up):
    skip GitHub for the rest of this run, and say why once."""


def gh_get(path):
    """GET from the GitHub API: the JSON, or None if it doesn't exist (GitHub also says
    that for a private repo when there's no token). Raises GitHubError when GitHub
    can't be asked at all."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "proof"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        base = os.environ.get("GITHUB_API_URL", GITHUB_API).rstrip("/")
        response = requests.get(base + path, headers=headers, timeout=20)
    except requests.RequestException as error:
        raise GitHubError(f"couldn't reach GitHub ({type(error).__name__})") from None
    if response.status_code == 404:
        return None
    if response.headers.get("X-RateLimit-Remaining") == "0":
        raise GitHubError("GitHub's hourly limit is used up - set GITHUB_TOKEN for 5,000 an hour")
    if response.status_code == 401:
        raise GitHubError("GitHub didn't accept GITHUB_TOKEN - check or renew it")
    if response.status_code != 200:
        raise GitHubError(f"GitHub answered HTTP {response.status_code}")
    return response.json()
