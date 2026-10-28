"""
portfolio.py - build a one-page portfolio (index.html) from all your case studies.

Markdown is turned into HTML here in Python; only the Mermaid diagrams are drawn
in the browser. Host the output folder on GitHub Pages, Netlify, or anywhere.
"""

import html
import json
import re
from pathlib import Path

import markdown

from .facts import read_facts

MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"


def load_case_studies(out_dir):
    """Read every <out_dir>/<project>/case_study.md (+ meta.json and facts.md if there)."""
    projects = []
    for md_file in sorted(Path(out_dir).glob("*/case_study.md")):
        folder = md_file.parent
        meta_file = folder / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        text = md_file.read_text(encoding="utf-8")

        title_line = re.search(r"^# (.+)$", text, flags=re.MULTILINE)
        title = title_line.group(1).strip() if title_line else folder.name
        name, _, tagline = title.partition(" - ")

        projects.append({
            "slug": folder.name, "name": name.strip(), "tagline": tagline.strip(),
            "text": text, "stack": meta.get("stack", []), "facts": read_facts(folder),
            "placeholders": len(re.findall(r"\[add:", text)),
        })
    return projects


def fix_lists(md_text):
    """LLMs often start a list right under a sentence, with no blank line.
    Python-Markdown then glues the bullets into the paragraph - add the blank line."""
    out, in_code = [], False
    is_item = lambda s: re.match(r"\s*([-*+]|\d+\.)\s", s) is not None   # noqa: E731
    for line in md_text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        if (not in_code and is_item(line) and out and out[-1].strip()
                and not is_item(out[-1]) and not out[-1].startswith(("#", "```"))):
            out.append("")
        out.append(line)
    return "\n".join(out)


def to_html(md_text):
    """Markdown -> HTML, with ```mermaid blocks turned into diagrams."""
    body = markdown.markdown(fix_lists(md_text), extensions=["fenced_code", "tables"])
    body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>', diagram_html,
                  body, flags=re.DOTALL)
    # Make unfilled placeholders impossible to miss
    body = re.sub(r"\[add:[^\]]*\]", lambda m: f"<mark>{m.group(0)}</mark>", body)
    return body


# `click A "https://..." _blank` lines that diagram.py adds (HTML-escaped by now)
CLICK_LINE = re.compile(r'^\s*click (\w+) (?:&quot;|")(https://[^"&]+)(?:&quot;|").*$\n?',
                        re.MULTILINE)


def diagram_html(match):
    """A Mermaid block, with its box links moved into data-links. Mermaid's own links need
    its 'loose' security mode, which would also let a label carry HTML; so the page's
    script adds the links after drawing, and only https ones."""
    source = match.group(1)
    links = dict(CLICK_LINE.findall(source))                  # https links only
    source = re.sub(r"^\s*click\s.*$\n?", "", source, flags=re.MULTILINE)   # drop them all
    data = f" data-links='{html.escape(json.dumps(links))}'" if links else ""
    notes = (["Click a box to see its code."] if links else []) + \
        (["Dashed arrows: described, but not shown by an import in the code."]
         if "-.-&gt;" in source or "-.->" in source else [])
    caption = f'<p class="diagram-note">{" ".join(notes)}</p>' if notes else ""
    return f'<pre class="mermaid"{data}>{source}</pre>{caption}'


# Tools every project has, or that no client searches for: shown after the rest
MINOR_TOOLS = {"GitHub Actions", "pytest", "Jest", "Vitest", "Nodemailer", "httpx", "Pydantic",
               "Uvicorn", "NumPy", "pandas", "matplotlib", "Pillow", "Zod", "Vite", "Jupyter",
               "Gradle", "Maven", "JUnit", "Serde", "Alembic", "SQL"}


def headline_stack(stack, count=6):
    """The 6 stack items for a project card: frameworks and services first."""
    return sorted(stack, key=lambda name: name in MINOR_TOOLS)[:count]


def build_site(out_dir, owner="My projects", contact=""):
    projects = load_case_studies(out_dir)
    if not projects:
        raise SystemExit(f"No case studies in {out_dir}. Run `python proof.py case <repo>` first.")

    cards, sections = [], []
    for p in projects:
        chips = "".join(f"<span class='chip'>{html.escape(s)}</span>"
                        for s in headline_stack(p["stack"]))
        cards.append(f"""<a class="card" href="#{p['slug']}">
  <h3>{html.escape(p['name'])}</h3>
  <p>{html.escape(p['tagline'])}</p>
  <div class="chips">{chips}</div>
</a>""")
        sections.append(f'<article id="{p["slug"]}">{to_html(p["text"])}'
                        f'<a class="top" href="#">Back to top</a></article>')

    contact_html = f'<p class="contact">{html.escape(contact)}</p>' if contact else ""
    count = f"{len(projects)} project" + ("" if len(projects) == 1 else "s")
    page = PAGE.format(owner=html.escape(owner), contact=contact_html,
                       count=count, cards="\n".join(cards),
                       sections="\n".join(sections), mermaid_js=MERMAID_JS)

    site_dir = Path(out_dir) / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(page, encoding="utf-8")
    return site_dir / "index.html", projects


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{owner} - Projects</title>
<style>
  :root {{ --bg:#fafaf9; --card:#ffffff; --text:#1c1917; --muted:#57534e;
          --border:#e7e5e4; --accent:#2563eb; --chip:#eff6ff; --mark:#fef08a; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0c0a09; --card:#1c1917; --text:#f5f5f4; --muted:#a8a29e;
            --border:#292524; --accent:#60a5fa; --chip:#1e293b; --mark:#854d0e; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font:16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 48px 16px; }}
  header h1 {{ font-size: 2.2rem; margin: 0 0 4px; }}
  header p {{ color: var(--muted); margin: 0; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(240px,1fr));
          gap:16px; margin: 32px 0 56px; }}
  .card {{ display:block; background:var(--card); border:1px solid var(--border);
          border-radius:12px; padding:18px; color:inherit; text-decoration:none;
          transition: border-color .15s; }}
  .card:hover {{ border-color: var(--accent); }}
  .card h3 {{ margin:0 0 6px; }}
  .card p {{ margin:0 0 12px; color:var(--muted); font-size:.95rem; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .chip {{ background:var(--chip); color:var(--accent); border-radius:999px;
          padding:2px 10px; font-size:.8rem; }}
  article {{ background:var(--card); border:1px solid var(--border); border-radius:12px;
            padding: 8px 28px 24px; margin-bottom: 32px; overflow-wrap: anywhere; }}
  article h1 {{ font-size: 1.6rem; }}
  article h2 {{ font-size: 1.15rem; margin-top: 28px; }}
  pre {{ overflow-x:auto; }}
  pre.mermaid {{ background:transparent; text-align:center; }}
  mark {{ background: var(--mark); color: inherit; padding: 0 3px; border-radius: 3px; }}
  a[href*="/blob/"] {{ font-size: .75em; color: var(--muted); }}   /* claim source links */
  .diagram-note {{ text-align: center; font-size: .8rem; color: var(--muted); margin-top: -4px; }}
  a {{ color: var(--accent); }}
  .top {{ font-size:.85rem; }}
  .contact {{ margin-top: 8px !important; }}
  @media (max-width: 600px) {{ article {{ padding: 4px 16px 18px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{owner}</h1>
    <p>{count} - what I built, how it works, and what came of it.</p>
    {contact}
  </header>
  <div class="grid">
{cards}
  </div>
{sections}
</div>
<script src="{mermaid_js}"></script>
<script>
  // Draw the diagrams. One with a syntax error is left out: a client should never
  // see Mermaid's error picture. (Open the browser console to see what was wrong.)
  if (window.mermaid) {{
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({{ startOnLoad: false, theme: dark ? "dark" : "default" }});
    (async () => {{
      for (const diagram of document.querySelectorAll("pre.mermaid")) {{
        try {{
          await mermaid.parse(diagram.textContent);
        }} catch (error) {{
          console.warn("Diagram left out, it has a Mermaid syntax error:", error);
          diagram.remove();
        }}
      }}
      await mermaid.run({{ querySelector: "pre.mermaid" }});
      linkBoxes();
    }})();
  }}

  // Boxes that name a real file open it on GitHub (links from diagram.py, https only)
  function linkBoxes() {{
    for (const diagram of document.querySelectorAll("pre.mermaid[data-links]")) {{
      const links = JSON.parse(diagram.dataset.links);
      for (const [id, url] of Object.entries(links)) {{
        if (!url.startsWith("https://")) continue;
        const box = diagram.querySelector(`g.node[id^="flowchart-${{id}}-"]`);
        if (!box) continue;
        box.style.cursor = "pointer";
        box.addEventListener("click", () => window.open(url, "_blank", "noopener"));
        const tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
        tip.textContent = "Open the code on GitHub";
        box.prepend(tip);
      }}
    }}
  }}
</script>
</body>
</html>
"""
