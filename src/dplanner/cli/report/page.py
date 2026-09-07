"""One HTML file: the report, with its stylesheet, its script and its pictures inside.

A bystander opens this from a mail, a file share or a plan repository's site with no
server behind it, so it loads nothing from anywhere: the CSS and JS beside this module are
inlined, every picture a description refers to travels as a data URI (within a budget —
past it the alt text says the image was omitted), and the drawings are inline SVG from
``drawings.py``. Every user string passes through ``html.escape``.

**The page has one selection.** Each node, row, chart mark and timeline span that is about
a step carries ``data-step``; the script selects a step everywhere at once and opens the
drawer on its card — the window's "one context" rule, in a browser. The cards live in a
``<template>`` so a page with the script disabled is still the whole report, readable and
printable, and a search finds every step.

The information architecture answers four readers in order: the sponsor's "on track?"
(the overview's figures and chart), the product owner's "what is in each milestone and
what was decided" (timeline, notes), the tester's "what is ready and what did the
last run say" (steps, tests), the developer's "how does it hang together" (plan, order),
and the last section tells anyone how to get the tool and open the plan.
"""

import json
from base64 import b64encode
from collections.abc import Iterable
from datetime import date
from html import escape
from importlib import resources

from dplanner.cli.report.assemble import Report, StepCard
from dplanner.cli.report.drawings import LIGHT, Colors, chart_svg, graph_svg, timeline_svg
from dplanner.cli.report.parts import (
    SLOT_TITLES,
    SLOTS,
    Chart,
    Facet,
    Figure,
    Graph,
    Image,
    Part,
    Prose,
    Table,
    Timeline,
)
from dplanner.core.markdown import render as markdown
from dplanner.domain.schedule import format_date
from dplanner.identity import APP_NAME, APP_VERSION

IMAGE_CAP = 512 * 1024
IMAGE_BUDGET = 8 * 1024 * 1024
ABOUT_ID = "about"
NOTHING_MORE = '<p class="note">Nothing more recorded.</p>'


def render(report: Report, *, colors: Colors = LIGHT, about: str = "") -> str:
    """The whole page. ``about`` is markdown for the last section; :func:`about_text`
    fills the shipped one in for this report."""
    budget = _ImageBudget()
    sections = []
    for slot in SLOTS:
        parts = report.sections.get(slot, ())
        if not parts:
            continue
        body = "".join(_parts(parts, colors, budget, slot, report.day))
        sections.append(f'<section id="{slot}"><h2>{_t(SLOT_TITLES[slot])}</h2>{body}</section>')
    if about:
        sections.append(
            f'<section id="{ABOUT_ID}" class="about"><h2>About this report</h2>'
            f'<div class="md">{markdown(about)}</div></section>'
        )
    nav = "".join(
        f'<a href="#{slot}">{_t(SLOT_TITLES[slot])}</a>'
        for slot in SLOTS
        if report.sections.get(slot)
    )
    if about:
        nav += f'<a href="#{ABOUT_ID}">About</a>'
    summary = f'<p class="summary">{_t(report.summary)}</p>' if report.summary else ""
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_t(report.title)} — plan report</title>"
        f'<meta name="generator" content="{_t(APP_NAME)} {_t(APP_VERSION)}">'
        f"<style>{_asset('report.css')}</style></head>"
        f'<body data-day="{report.day.isoformat()}">'
        '<header class="top"><div class="brand">'
        f"<h1>{_t(report.title)}</h1>{summary}</div>"
        f'<div class="asof">Plan as of <time datetime="{report.day.isoformat()}">'
        f"{_t(format_date(report.day, today=report.day))} {report.day.year}</time></div>"
        f"<nav>{nav}</nav></header>"
        f"<main>{''.join(sections)}</main>"
        '<aside id="drawer" hidden><button class="close" type="button" aria-label="Close">&times;'
        '</button><div class="drawer-body"></div></aside>'
        f'<template id="cards">{"".join(_card(card, budget) for card in report.steps)}'
        "</template>"
        f"<script>{_asset('report.js')}</script></body></html>\n"
    )


def about_text(report: Report) -> str:
    """The shipped onboarding page, filled in for this plan."""
    text = _asset("about.md")
    clone = (
        f"```\ngit clone {report.plan_remote}\ndplanner library add <the project's directory>\n```"
        if report.plan_remote
        else "```\ndplanner library add <the project's directory>\n```\n\n"
        "(Ask the team where the plan repository lives; this report was written from a "
        "checkout without a remote.)"
    )
    return text.replace("{{title}}", report.title).replace("{{clone}}", clone)


def summary_script(report: Report, slug: str) -> str:
    """What the site index learns about this project: one script that pushes a record."""
    figures = [part for part in report.sections.get("overview", ()) if isinstance(part, Figure)]
    record = {
        "slug": slug,
        "title": report.title,
        "summary": report.summary,
        "day": report.day.isoformat(),
        "steps": len(report.steps),
        "figures": [
            {"label": f.label, "value": f.value, "note": f.note, "tone": f.tone} for f in figures
        ],
    }
    return (
        "window.dplannerProjects = window.dplannerProjects || [];\n"
        f"window.dplannerProjects.push({json.dumps(record, ensure_ascii=False, sort_keys=True)});\n"
    )


# -- parts -------------------------------------------------------------------------------------


def _parts(
    parts: Iterable[Part], colors: Colors, budget: "_ImageBudget", slot: str, today: date
) -> list[str]:
    out: list[str] = []
    figures: list[Figure] = []
    for part in parts:
        if isinstance(part, Figure):
            figures.append(part)
            continue
        if figures:
            out.append(_figures(figures))
            figures = []
        out.append(_part(part, colors, budget, slot, today))
    if figures:
        out.append(_figures(figures))
    return out


def _part(part: Part, colors: Colors, budget: "_ImageBudget", slot: str, today: date) -> str:
    if isinstance(part, Table):
        return _table(part, slot, today)
    if isinstance(part, Chart):
        return (
            f'<figure class="chart" id="chart-{_t(part.id)}"><figcaption>{_t(part.title)}'
            f"</figcaption>{chart_svg(part, colors)}"
            f'<div class="tooltip" hidden></div>{_note(part.note)}</figure>'
        )
    if isinstance(part, Timeline):
        return (
            f'<figure class="timeline" id="timeline-{_t(part.id)}"><figcaption>'
            f"{_t(part.title)}</figcaption>{timeline_svg(part, colors)}</figure>"
        )
    if isinstance(part, Graph):
        return _graph(part, colors)
    if isinstance(part, Prose):
        meta = f'<p class="meta">{_t(part.meta)}</p>' if part.meta else ""
        return (
            f'<article class="prose" id="prose-{_t(part.id)}"><h3>{_t(part.title)}</h3>{meta}'
            f'<div class="md">{_markdown(part.markdown, part.images, budget)}</div></article>'
        )
    return ""


def _figures(figures: list[Figure]) -> str:
    tiles = "".join(
        f'<div class="figure tone-{figure.tone or "quiet"}"><div class="value">{_t(figure.value)}'
        f'</div><div class="label">{_t(figure.label)}</div>'
        f"{f'<div class=note>{_t(figure.note)}</div>' if figure.note else ''}</div>"
        for figure in figures
    )
    return f'<div class="figures">{tiles}</div>'


def _table(table: Table, slot: str, today: date) -> str:
    head = "".join(
        f'<th class="kind-{column.kind}">{_t(column.label)}</th>' for column in table.columns
    )
    rows = []
    for row in table.rows:
        cells = "".join(
            f'<td class="kind-{column.kind}">{_cell(column.kind, text, today)}</td>'
            for column, text in zip(table.columns, row.cells, strict=True)
        )
        attrs = f' data-step="{_t(row.step_id)}"' if row.step_id else ""
        attrs += ' class="strong"' if row.strong else ""
        rows.append(f"<tr{attrs}>{cells}</tr>")
    tools = (
        '<div class="filter"><input id="step-filter" type="search" placeholder="Filter steps">'
        '<select id="status-filter"><option value="">Any status</option>'
        '<option value="pending">Pending</option><option value="in-progress">In progress</option>'
        '<option value="done">Done</option><option value="blocked">Blocked</option></select></div>'
        if slot == "steps" and table.id == "steps"
        else ""
    )
    return (
        f'<figure class="table" id="table-{_t(table.id)}"><figcaption>{_t(table.title)}'
        f"</figcaption>{tools}"
        f'<div class="scroll"><table class="data"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>{_note(table.note)}</figure>"
    )


def _cell(kind: str, text: str, today: date | None = None) -> str:
    if kind == "date" and text and today is not None:
        try:
            return _t(format_date(date.fromisoformat(text), today=today))
        except ValueError:
            return _t(text)
    if kind == "status" and text:
        return f'<span class="status status-{_t(text)}">{_t(text.replace("-", " "))}</span>'
    if kind == "key" and text:
        return f'<span class="key">{_t(text)}</span>'
    return _t(text)


def _graph(graph: Graph, colors: Colors) -> str:
    legend = (
        '<div class="legend">'
        '<span class="swatch kind-milestone">milestone</span>'
        '<span class="swatch kind-feature">feature</span>'
        '<span class="swatch status-done">done</span>'
        '<span class="swatch status-in-progress">in progress</span>'
        '<span class="swatch status-blocked">blocked</span>'
        '<span class="swatch edge-requires">requires</span>'
        '<span class="swatch edge-relates">relates</span>'
        "</div>"
    )
    return (
        '<figure class="graph-frame"><div class="tools">'
        '<button type="button" data-zoom="in" aria-label="Zoom in">+</button>'
        '<button type="button" data-zoom="out" aria-label="Zoom out">&minus;</button>'
        '<button type="button" data-zoom="fit">Fit</button>'
        '<span class="hint">Drag to pan · wheel to zoom · click a card</span></div>'
        f'<div class="viewport">{graph_svg(graph, colors)}</div>{legend}</figure>'
    )


def _card(card: StepCard, budget: "_ImageBudget") -> str:
    facets = "".join(_facet(facet, budget) for facet in card.facets)
    status = card.status.replace("-", " ")
    kind = f'<span class="badge kind-{_t(card.kind)}">{_t(card.kind)}</span>' if card.kind else ""
    return (
        f'<article class="card" data-step="{_t(card.id)}" data-key="{_t(card.key)}">'
        f'<header><span class="key">{_t(card.key)}</span><h3>{_t(card.title)}</h3>'
        f'<div class="badges">{kind}<span class="status status-{_t(card.status)}">{_t(status)}'
        f"</span></div></header>"
        f"{f'<dl class=facets>{facets}</dl>' if facets else NOTHING_MORE}"
        "</article>"
    )


def _facet(facet: Facet, budget: "_ImageBudget") -> str:
    if facet.kind == "markdown":
        value = f'<div class="md">{_markdown(facet.value, facet.images, budget)}</div>'
    elif facet.kind == "link" and facet.url:
        value = f'<a href="{_t(facet.url)}" rel="noopener" target="_blank">{_t(facet.value)}</a>'
    elif facet.kind == "status":
        value = _cell("status", facet.value)
    else:
        value = _t(facet.value)
    return f"<dt>{_t(facet.label)}</dt><dd>{value}</dd>"


def _markdown(text: str, images: tuple[Image, ...], budget: "_ImageBudget") -> str:
    by_name = {image.name: image for image in images}

    def source(name: str) -> str | None:
        image = by_name.get(name)
        return budget.data_uri(image) if image is not None else None

    return markdown(text, image_src=source)


def _note(note: str) -> str:
    return f'<p class="note">{_t(note)}</p>' if note else ""


class _ImageBudget:
    """Pictures are inlined until the page would grow past the budget; then the alt text
    stands in, and the page says so rather than silently dropping them."""

    def __init__(self) -> None:
        self._spent = 0

    def data_uri(self, image: Image) -> str | None:
        size = len(image.data)
        if size > IMAGE_CAP or self._spent + size > IMAGE_BUDGET:
            return None
        self._spent += size
        return f"data:{image.mime};base64,{b64encode(image.data).decode('ascii')}"


def _asset(name: str) -> str:
    return resources.files(__package__).joinpath(name).read_text(encoding="utf-8")


def _t(text: str) -> str:
    return escape(text, quote=True)
