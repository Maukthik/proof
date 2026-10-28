"""
redact.py - keep keys and passwords that are written into the code out of every prompt.

proof already never reads .env files. But a key pasted straight into config.py would
still be sent to the model - and with a cloud provider, that means to someone else's
server. So every piece of text that goes into a prompt passes through redact() first.

Known key formats are always removed. Passwords in assignments and database URLs are
removed too, unless they're obviously placeholders ("your-key-here", localhost dev URLs).
"""

import re

REMOVED = "[secret removed by proof]"

# Formats that are a secret wherever they appear
KEY_FORMATS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
                               r"(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("Stripe key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("Groq key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
]

# api_key = "...", "password": "...", SECRET_TOKEN='...'  (the value is group 2)
ASSIGNED = re.compile(r"""(?i)\b([\w-]*(?:api[_-]?key|secret|token|password|passwd)[\w-]*)"""
                      r"""["']?\s*[:=]\s*["']([^"'\s]{8,})["']""")
# postgres://user:PASSWORD@host  (the password is group 2, the host group 3)
URL_PASSWORD = re.compile(r"\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/@]+:)"
                          r"([^@\s]+)@([^/:\s]+)")
# Values that are clearly not real secrets
PLACEHOLDER = re.compile(r"(?i)your|xxx|example|change.?me|dummy|placeholder|test|<|\$\{|\{\{|"
                         r"process\.env|os\.environ|getenv|^\*+$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "db", "postgres", "mysql", "redis", "mongo"}


def redact(text, path=""):
    """Return (text without secrets, [kinds of secret removed])."""
    found = []

    for kind, pattern in KEY_FORMATS:
        text, count = pattern.subn(REMOVED, text)
        found += [kind] * count

    if not re.search(r"\.(example|sample|template)$", path):   # those hold placeholders only
        def assigned(match):
            if not looks_secret(match.group(1), match.group(2)):
                return match.group(0)
            found.append(f"hardcoded {match.group(1)}")
            return match.group(0).replace(match.group(2), REMOVED)

        def url_password(match):
            if match.group(3) in LOCAL_HOSTS or PLACEHOLDER.search(match.group(2)):
                return match.group(0)
            found.append("password in a database URL")
            return f"{match.group(1)}{REMOVED}@{match.group(3)}"

        text = ASSIGNED.sub(assigned, text)
        text = URL_PASSWORD.sub(url_password, text)
    return text, found


def looks_secret(name, value):
    """A value assigned to a secret-sounding name that looks like a real secret: random-
    looking (letters and digits mixed), not a URL, not a placeholder. Real repos are
    full of token = "access_token" and access_token_url = "https://..." - not secrets."""
    if REMOVED in value or PLACEHOLDER.search(value) or "://" in value:
        return False
    if re.search(r"(?i)(url|uri|endpoint|name|field|header|type|path|key_id)$", name):
        return False
    return bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))
