"""
tracker.py - remember which pitches you sent and what happened, to learn what works.

Every `proof pitch` adds an entry to proof_output/pitches/log.json (status "draft").
You update it as things happen:

  proof log need-a-fastapi-dev sent
  proof log need-a-fastapi-dev followed-up
  proof log need-a-fastapi-dev replied
  proof log need-a-fastapi-dev won

and `proof log` shows every pitch, which projects and tech terms get replies, and what
to do next: pitches due a follow-up, and ones to give up on.
"""

import json
from datetime import date
from pathlib import Path

STATUSES = ["draft", "sent", "followed-up", "replied", "won", "ignored"]
GOT_REPLY = {"replied", "won"}
FOLLOW_UP_DAYS = 4       # no reply this long after sending: send one short follow-up
GIVE_UP_DAYS = 10        # still nothing this long after the follow-up: mark it ignored


def log_file(out_dir):
    return Path(out_dir) / "pitches" / "log.json"


def load_log(out_dir):
    path = log_file(out_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_log(out_dir, log):
    path = log_file(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def record_pitch(out_dir, name, source, projects, matched, job_tech=()):
    """Called after writing a pitch. Re-writing a pitch keeps its status and notes.
    job_tech: every technology the job asked for (`proof suggest` uses it to see what
    clients want that your projects don't show yet)."""
    log = load_log(out_dir)
    entry = log.get(name, {"status": "draft", "notes": []})
    entry.update({"source": source, "projects": projects, "matched": matched,
                  "job_tech": sorted(job_tech), "written": date.today().isoformat()})
    log[name] = entry
    save_log(out_dir, log)


def find_pitch(log, name):
    """Exact name, or a unique start of one ('need-a' for 'need-a-fastapi-dev')."""
    if name in log:
        return name
    matches = [key for key in log if key.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    choices = ", ".join(matches or log) or "none yet"
    raise SystemExit(f"No single pitch called '{name}'. Pitches: {choices}")


def update_status(out_dir, name, status, note=""):
    if status not in STATUSES:
        raise SystemExit(f"Status must be one of: {', '.join(STATUSES)}")
    log = load_log(out_dir)
    key = find_pitch(log, name)
    log[key]["status"] = status
    log[key][status] = date.today().isoformat()     # e.g. "sent": "2026-10-28"
    if note:
        log[key].setdefault("notes", []).append(note)
    save_log(out_dir, log)
    return key


def days_since(entry, event, today):
    """Days since the date stored for `event` ("sent", "followed-up"), or None."""
    try:
        return (today - date.fromisoformat(entry[event])).days
    except (KeyError, ValueError):
        return None


def to_do(log, today=None):
    """(pitches due a follow-up, pitches to give up on), as (name, days) lists.
    One follow-up per pitch: a second one rarely helps and starts to annoy."""
    today = today or date.today()
    follow_up, give_up = [], []
    for name, entry in sorted(log.items()):
        if entry["status"] == "sent":
            days = days_since(entry, "sent", today)
            if days is not None and days >= FOLLOW_UP_DAYS:
                follow_up.append((name, days))
        elif entry["status"] == "followed-up":
            days = days_since(entry, "followed-up", today)
            if days is not None and days >= GIVE_UP_DAYS:
                give_up.append((name, days))
    return follow_up, give_up


def reply_rates(log, field):
    """For each project (field="projects") or tech term (field="matched"):
    (sent, replies, wins) over all pitches that went out."""
    rates = {}
    for entry in log.values():
        if entry["status"] == "draft":
            continue
        for item in entry.get(field, []):
            sent, replies, wins = rates.get(item, (0, 0, 0))
            rates[item] = (sent + 1,
                           replies + (entry["status"] in GOT_REPLY),
                           wins + (entry["status"] == "won"))
    return sorted(rates.items(), key=lambda kv: (-kv[1][1] / kv[1][0], -kv[1][0]))


def report(log, today=None):
    """Text table of all pitches, what's working, then what to do next."""
    if not log:
        return "No pitches yet. Write one with:  proof pitch <job file, URL or ->"
    lines = [f"{'pitch':<34} {'status':<8} {'written':<11} projects"]
    for name, entry in sorted(log.items(), key=lambda kv: kv[1].get("written", "")):
        lines.append(f"{name[:34]:<34} {entry['status']:<8} {entry.get('written', ''):<11} "
                     f"{', '.join(entry.get('projects', []))}")

    sent = [e for e in log.values() if e["status"] != "draft"]
    if not sent:
        lines.append("\nNothing marked as sent yet:  proof log <pitch> sent")
        return "\n".join(lines)

    replies = sum(e["status"] in GOT_REPLY for e in sent)
    wins = sum(e["status"] == "won" for e in sent)
    lines.append(f"\n{len(sent)} sent, {replies} replies ({100 * replies // len(sent)}%), "
                 f"{wins} won")
    for title, field in [("By project", "projects"), ("By matched tech", "matched")]:
        rows = [(item, counts) for item, counts in reply_rates(log, field) if counts[0] >= 2]
        if rows:
            lines.append(f"\n{title} (used in 2+ sent pitches):")
            lines += [f"  {item:<28} {r}/{s} replies, {w} won" for item, (s, r, w) in rows]

    followed = [e for e in sent if "followed-up" in e]
    if followed:
        answered = sum(e["status"] in GOT_REPLY for e in followed)
        lines.append(f"\nFollow-ups: {len(followed)} sent, {answered} then got a reply")
    lines += to_do_lines(*to_do(log, today))
    return "\n".join(lines)


def to_do_lines(follow_up, give_up):
    lines = []
    if follow_up:
        lines.append(f"\nDue a follow-up (sent {FOLLOW_UP_DAYS}+ days ago, no reply):")
        lines += [f"  {name:<34} {days} days  ->  proof followup {name}"
                  for name, days in follow_up]
    if give_up:
        lines.append(f"\nNo reply {GIVE_UP_DAYS}+ days after your follow-up - let them go:")
        lines += [f"  {name:<34} {days} days  ->  proof log {name} ignored"
                  for name, days in give_up]
    return lines
