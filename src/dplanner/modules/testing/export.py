"""The test roster written out: one file a QA team can read without DPlanner.

**Why this is not the report.** ``cli/report/`` publishes *the plan* — figures, the graph,
a timeline, and a table naming every test in one line. This writes *the tests*, filed under
their categories, with each body in full, for the reader who is going to execute them or
load them into a test management system. A row in the report and a script somebody follows
by hand are not one document at two lengths.

Two formats, and both are deliberate:

- **Markdown** is what an agent reads back and what a repository keeps under version
  control, and it is what the next agent converts into whatever TestRail or Xray wants.
- **HTML** is what a person opens: one self-contained page, every test a ``<details>`` that
  opens on its body, so a hundred tests are a page you can scan and not a scroll.

Neither embeds pictures. A test body's images live in the step's file area, and an export
that inlined them would be a publication — which is the report's job, and which is why
``![](assets/…)`` is left as it is written, pointing at a plan a reader of this file may
well have beside them.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Final

from dplanner.core.markdown import render as markdown
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    Test,
    audience_words,
    covered,
    for_audiences,
    project_tests,
)
from dplanner.modules.testing.categories import Category, catalog, category_of

# What `--format` takes, and the suffix each one writes. Ordered as they are offered.
FORMATS: Final[tuple[str, ...]] = ("md", "html")
SUFFIXES: Final[dict[str, str]] = {"md": ".md", "html": ".html"}
FORMAT_LABELS: Final[dict[str, str]] = {"md": "Markdown", "html": "HTML page"}

NOT_RUN = "not run"
NOTHING = "No tests match."


@dataclass(frozen=True)
class Exported:
    """What the export was asked for, so the file can say so at the top.

    A test list narrowed to QA and headed with nothing is a list somebody will later read
    as the whole roster. The narrowing is part of the document.
    """

    project: Project
    pairs: Sequence[tuple[Step, Test]]
    outcomes: Mapping[str, runs.Outcome]
    audiences: Sequence[str] = ()  # The audience labels asked for; empty is everyone.
    archived: bool = False
    scope: str = ""  # The collector the list was narrowed to, by title; "" is the project.


def suffix_for(fmt: str) -> str:
    return SUFFIXES.get(fmt, SUFFIXES["md"])


def narrowed(
    library: Library,
    project: Project,
    *,
    scope: StepId = "",
    audiences: Sequence[str] = (),
    archived: bool = False,
) -> list[tuple[Step, Test]]:
    """The tests an export covers: the scope's, for these audiences, archived or not.

    One reader for both halves of the verb — ``dplanner test export`` takes the narrowing
    as flags, the window's takes it from what the Tests tab is showing — because two copies
    of this walk would one day disagree about what an export of "the QA tests" contains.
    """
    within = project.step(scope) if scope else None
    pairs = (
        project_tests(project, archived=archived)
        if within is None
        else covered(library, project, within.id, archived=archived)
    )
    return for_audiences(pairs, audiences)


def render(exported: Exported, fmt: str) -> str:
    """The whole file, in ``fmt``. An unknown format is markdown — the readable default."""
    return _html(exported) if fmt == "html" else _markdown(exported)


# -- what both formats agree on ---------------------------------------------------------


def _title(exported: Exported) -> str:
    return f"{exported.project.title or 'Untitled project'} — Tests"


def _narrowing(exported: Exported) -> list[str]:
    """The lines under the title saying what this list is, and is not."""
    said = []
    if exported.scope:
        said.append(f"Scope: {exported.scope}")
    said.append(
        f"Audience: {', '.join(exported.audiences)}" if exported.audiences else "Audience: all"
    )
    if exported.archived:
        said.append("Archived tests included")
    counts = runs.tally([_status(exported, test) for _step, test in exported.pairs])
    total = len(exported.pairs)
    tally = ", ".join(f"{count} {status}" for status, count in counts.items() if count)
    said.append(f"{total} test{'' if total == 1 else 's'} — {tally}" if total else "No tests")
    return said


def _status(exported: Exported, test: Test) -> str:
    outcome = exported.outcomes.get(test.id)
    return outcome.result.status if outcome is not None else "pending"


def _result_words(exported: Exported, test: Test) -> str:
    outcome = exported.outcomes.get(test.id)
    if outcome is None:
        return NOT_RUN
    where = outcome.run.label or outcome.run.id
    return f"{outcome.result.status} ({where})"


def _filed(exported: Exported) -> list[tuple[Category, list[tuple[Step, Test]]]]:
    """The tests grouped under their categories, in the catalogue's order.

    A group nobody filed anything into is left out — the catalogue is a plan for where
    tests will go, and an export is a record of where they are. *Uncategorised* sorts last,
    where ``catalog()`` puts everything it does not name.
    """
    known = {category.name.casefold(): category for category in catalog(exported.project)}
    places = {name: index for index, name in enumerate(known)}
    held: dict[str, list[tuple[Step, Test]]] = {}
    for step, test in exported.pairs:
        held.setdefault(category_of(test), []).append((step, test))
    ordered = sorted(
        held, key=lambda name: (places.get(name.casefold(), len(places)), name.casefold())
    )
    return [(known.get(name.casefold(), Category(name)), held[name]) for name in ordered]


# -- markdown ---------------------------------------------------------------------------


def _markdown(exported: Exported) -> str:
    out = [f"# {_title(exported)}", ""]
    out += [f"*{line}*  " for line in _narrowing(exported)]
    out.append("")
    if not exported.pairs:
        return "\n".join([*out, NOTHING, ""])
    for category, pairs in _filed(exported):
        out += [f"## {category.name}", ""]
        for step, test in pairs:
            out.append(f"### {test.id} — {test.title or 'Untitled test'}")
            out.append("")
            facts = [
                f"Step: {step.title or 'Untitled step'}",
                f"Audience: {audience_words(test)}",
                f"Result: {_result_words(exported, test)}",
            ]
            if test.archived:
                facts.append("Archived")
            out += [f"- {fact}" for fact in facts]
            out.append("")
            if test.body.strip():
                out += [test.body.rstrip(), ""]
    return "\n".join(out)


# -- html -------------------------------------------------------------------------------

# One page, no requests: the reader may well open it off a memory stick. Both schemes are
# declared, because a test list is read in whatever the reader's machine is set to.
_STYLE = """
:root { color-scheme: light dark; --ink: #1a1c1e; --quiet: #5c6166; --line: #d7dade;
        --ground: #ffffff; --well: #f6f7f9; --ok: #2ea044; --failed: #db4435;
        --skipped: #d29922; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e6e8ea; --quiet: #9aa0a6; --line: #32363b; --ground: #16181a;
          --well: #1e2124; }
}
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 32px 20px 64px; max-width: 54rem; background: var(--ground);
       color: var(--ink); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.1rem; margin: 32px 0 8px; padding-bottom: 6px;
     border-bottom: 1px solid var(--line); display: flex; align-items: baseline; gap: 8px; }
h2 .count { color: var(--quiet); font-weight: normal; font-size: .85rem; }
.narrowing { color: var(--quiet); font-size: .85rem; margin: 0 0 24px; }
.narrowing span { margin-right: 14px; white-space: nowrap; }
details { border: 1px solid var(--line); border-radius: 6px; margin: 6px 0;
          background: var(--well); }
details[open] { background: var(--ground); }
summary { cursor: pointer; padding: 8px 12px; display: flex; gap: 10px; align-items: baseline;
          flex-wrap: wrap; }
summary::marker { color: var(--quiet); }
.key { font-variant-numeric: tabular-nums; color: var(--quiet); font-size: .85rem; }
.name { font-weight: 600; flex: 1 1 14rem; }
.meta { color: var(--quiet); font-size: .8rem; }
.result { font-size: .8rem; font-weight: 600; }
.result.ok { color: var(--ok); }
.result.failed { color: var(--failed); }
.result.skipped { color: var(--skipped); }
.body { padding: 0 12px 12px 12px; border-top: 1px solid var(--line); margin-top: 2px; }
.body :first-child { margin-top: 12px; }
.body pre { background: var(--well); padding: 10px; border-radius: 4px; overflow-x: auto; }
.body img { max-width: 100%; }
.none { color: var(--quiet); }
"""


def _html(exported: Exported) -> str:
    out = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(_title(exported))}</title>",
        f"<style>{_STYLE}</style></head><body>",
        f"<h1>{escape(_title(exported))}</h1>",
        '<p class="narrowing">'
        + "".join(f"<span>{escape(line)}</span>" for line in _narrowing(exported))
        + "</p>",
    ]
    if not exported.pairs:
        out.append(f'<p class="none">{escape(NOTHING)}</p>')
    for category, pairs in _filed(exported):
        out.append(f'<h2>{escape(category.name)}<span class="count">{len(pairs)}</span></h2>')
        out += [_html_test(exported, step, test) for step, test in pairs]
    out.append("</body></html>")
    return "\n".join(out)


def _html_test(exported: Exported, step: Step, test: Test) -> str:
    status = _status(exported, test)
    meta = [f"Step: {step.title or 'Untitled step'}", audience_words(test)]
    if test.archived:
        meta.append("Archived")
    body = markdown(test.body)
    return (
        "<details>"
        f'<summary><span class="key">{escape(test.id)}</span>'
        f'<span class="name">{escape(test.title or "Untitled test")}</span>'
        f'<span class="meta">{escape(" · ".join(meta))}</span>'
        f'<span class="result {escape(status)}">{escape(_result_words(exported, test))}</span>'
        "</summary>" + (f'<div class="body">{body}</div>' if body else "") + "</details>"
    )
