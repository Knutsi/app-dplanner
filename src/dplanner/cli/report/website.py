"""The reports of one plan repository, laid out as a site anyone can browse.

::

    <plan repository root>/reports/
    ├── index.html            the site: every project's headline, one card each
    ├── <slug>/index.html     one project's full report
    └── <slug>/summary.js     that project's headline figures, one small script

**Per-project state lives only in per-project files, and the index depends only on the
set of projects.** A Save rewrites the reports of the projects in that repository and
nothing of any other; the index is rendered from the sorted set of ``*/summary.js`` present
on disk — a static page with one ``<script src>`` per project and a few lines of
client-side rendering, which works from ``file://`` and from GitHub Pages alike where
``fetch()`` does not. Its bytes change only when a project joins or leaves, so two people
saving two projects never both touch it, and a pull that brings a colleague's new project
is picked up by the next run. That is what keeps a shared plan repository free of merge
conflicts over a generated page.

**The directory is a constant, not a setting.** The window's preferences are QSettings,
which ``dplanner report site`` cannot read; a per-user name would let the two surfaces
write two sites into one repository. ``FORMAT.md``'s rule says the same thing: a convention
a colleague should see never lives in a preference.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from importlib import resources
from pathlib import Path

from dplanner.core.fsio import slugify, write_atomic
from dplanner.identity import APP_NAME, APP_VERSION

REPORTS_DIR = "reports"
INDEX_NAME = "index.html"
SUMMARY_NAME = "summary.js"

_INDEX_STYLE = """
.plans { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.plan { display: block; color: inherit; text-decoration: none; background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius); padding: 16px;
  box-shadow: var(--shadow); }
.plan:hover { border-color: var(--border-strong); }
.plan h3 { margin: 0 0 4px; }
.plan .summary { color: var(--secondary); font-size: 13px; margin: 0 0 12px; }
.plan .figures { grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin: 0; }
.plan .figure { padding: 10px; box-shadow: none; }
.plan .figure .value { font-size: 18px; }
.plan .asof { color: var(--secondary); font-size: 12px; margin: 12px 0 0; }
"""

_INDEX_SCRIPT = """
(function () {
  var list = (window.dplannerProjects || []).slice().sort(function (a, b) {
    return a.title.localeCompare(b.title);
  });
  var root = document.getElementById("plans");
  function t(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  list.forEach(function (p) {
    var a = document.createElement("a");
    a.className = "plan";
    a.href = encodeURIComponent(p.slug) + "/__INDEX__";
    var figs = (p.figures || []).map(function (f) {
      return '<div class="figure tone-' + t(f.tone || "quiet") + '"><div class="value">' +
        t(f.value) + '</div><div class="label">' + t(f.label) + "</div></div>";
    }).join("");
    a.innerHTML = "<h3>" + t(p.title) + '</h3><p class="summary">' + t(p.summary) + "</p>" +
      '<div class="figures">' + figs + '</div><p class="asof">' + t(p.steps) +
      " steps · plan as of " + t(p.day) + "</p>";
    root.appendChild(a);
  });
  if (!list.length) {
    root.innerHTML = '<p class="note">No project has been saved yet.</p>';
  }
})();
"""


@dataclass(frozen=True)
class SiteReport:
    """One project's rendered pages, ready to write."""

    slug: str
    page: str
    summary: str


def slug_for(project_dir: Path, repo_root: Path) -> str:
    """The project directory's path relative to the repository root with its separators
    folded; the repository directory's own name when the project *is* the root. Stable
    across renames, readable in a URL."""
    try:
        relative = project_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        relative = Path(project_dir.name)
    parts = [part for part in relative.parts if part not in ("", ".")]
    if not parts:
        return slugify(repo_root.resolve().name, fallback="plan")
    return slugify("-".join(parts), fallback="plan")


def write(repo_root: Path, reports: Sequence[SiteReport]) -> list[str]:
    """Write each project's pages, regenerate the index from what is now on disk, and
    return the repository-relative pathspecs a commit should carry."""
    site = repo_root / REPORTS_DIR
    for report in reports:
        directory = site / report.slug
        directory.mkdir(parents=True, exist_ok=True)
        write_atomic(directory / INDEX_NAME, report.page)
        write_atomic(directory / SUMMARY_NAME, report.summary)
    write_atomic(site / INDEX_NAME, index_html(slugs_present(site)))
    return [REPORTS_DIR]


def slugs_present(site: Path) -> list[str]:
    """Every project directory under the site, by the summary each one carries."""
    if not site.is_dir():
        return []
    return sorted(
        child.name
        for child in site.iterdir()
        if child.is_dir() and (child / SUMMARY_NAME).is_file()
    )


def index_html(slugs: Sequence[str]) -> str:
    """The site index: a function of the slug set and nothing else."""
    scripts = "".join(
        f'<script src="{escape(slug, quote=True)}/{SUMMARY_NAME}"></script>' for slug in slugs
    )
    links = "".join(
        f'<li><a href="{escape(slug, quote=True)}/{INDEX_NAME}">{escape(slug)}</a></li>'
        for slug in slugs
    )
    css = resources.files(__package__).joinpath("report.css").read_text(encoding="utf-8")
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Plans</title>"
        f'<meta name="generator" content="{escape(APP_NAME)} {escape(APP_VERSION)}">'
        f"<style>{css}</style><style>{_INDEX_STYLE}</style></head><body>"
        '<header class="top"><div class="brand"><h1>Plans</h1>'
        '<p class="summary">Every project in this repository, as of its last save</p></div>'
        "</header>"
        f'<main><noscript><ul>{links}</ul></noscript><div class="plans" id="plans"></div></main>'
        f"{scripts}<script>{_INDEX_SCRIPT.replace('__INDEX__', INDEX_NAME)}</script>"
        "</body></html>\n"
    )


def summary_record(summary_js: str) -> dict[str, object]:
    """The record a ``summary.js`` pushes — a test's way to read one back."""
    start, end = summary_js.index("push(") + len("push("), summary_js.rindex(")")
    loaded: dict[str, object] = json.loads(summary_js[start:end])
    return loaded
