"""
tracker.py - remember which pitches you sent and what happened, to learn what works.

Every `proof pitch` adds an entry to proof_output/pitches/log.json (status "draft").
You update it as things happen:

  proof log need-a-fastapi-dev sent
  proof log need-a-fastapi-dev replied
  proof log need-a-fastapi-dev won

and `proof log` shows every pitch plus which projects and tech terms get replies.
"""

import json
from datetime import date
from pathlib import Path

STATUSES = ["draft", "sent", "replied", "won", "ignored"]
GOT_REPLY = {"replied", "won"}


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


def report(log):
    """Text table of all pitches, then what's working."""
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
    return "\n".join(lines)
