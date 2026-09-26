"""SVG for the report: the graph as the canvas draws it, the progress chart, the timeline.

One drawing code path for screen and paper. The page inlines these; the window's PDF
renders the same strings through ``QSvgRenderer``. QtSvg reads no CSS variables and no
``<style>``, so every shape carries explicit ``fill`` and ``stroke`` from a :class:`Colors`
— and a class beside them, so the page's stylesheet can restyle the same shapes for a dark
theme, which wins over a presentation attribute.

The grammar is the window's (``project_editor/renderers.py``, ``time_estimates/work_view.py``):
cards with an 8 px radius, a 26 px spine carrying the key rotated a quarter turn and washed
by status, the body tinted by kind — a milestone its own shade of the project's colour map,
teal a feature, green a done step —
the estimate at the bottom right; cubic edges with a head for ``requires`` and dashes for
``relates``; 2 px lines, 8 px end markers ringed with the surface, hairline grid, the axis
marked at calendar boundaries. Text is measured by an average glyph width, which is what a
renderer without a font engine can do; the wrap errs towards the ellipsis.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from math import cos, pi, sin

from dplanner.cli.report.parts import (
    AMOUNT_PLOTS,
    Chart,
    Graph,
    Node,
    Plot,
    PlotKind,
    Series,
    Stretch,
    Timeline,
)
from dplanner.domain.schedule import (
    SATURDAY,
    Tick,
    axis_ticks,
    format_date,
    format_days,
    short_date,
)


@dataclass(frozen=True)
class Colors:
    ink: str
    secondary: str
    surface: str
    elevated: str
    border: str
    accent: str
    good: str
    busy: str
    bad: str
    milestone: str
    feature: str
    plan: str
    attention: str
    warm: str
    cool: str


# The hex twins of ``theme/themes.py``'s LIGHT and DARK and ``theme/tones.py``'s tones.
# Copied rather than imported: ``theme/__init__.py`` loads Qt, and this layer may not.
_TONES = {
    "good": "#78c88c",
    "busy": "#6ea0dc",
    "bad": "#dc6e6e",
    # The family a milestone wears where a project deals no shade of its own; a dealt one
    # arrives on the node (``Node.color``) and wins. Also the *kind* swatch in the legend,
    # which stands for "milestone" and not for any one of them.
    "milestone": "#9682dc",
    "feature": "#50b4af",
    "plan": "#5f87d7",
    # The attention amber, the hex twin of ``theme/tones.py``'s CHIP_ATTENTION_TINT: a
    # change worth noticing that is not a problem.
    "attention": "#dcaa5a",
    # The work plots' tints, the twins of ``time_estimates/plotting.py``'s WARM and COOL:
    # the plan holding more work than the plan compared with, and less.
    "warm": "#e89646",
    "cool": "#2fa0aa",
}
LIGHT = Colors(
    ink="#23262b",
    secondary="#5d6169",
    surface="#fcfbf9",
    elevated="#e9e7e2",
    border="#d7d4cd",
    accent="#a07c33",
    **_TONES,
)
DARK = Colors(
    ink="#e6e8ec",
    secondary="#a8b0bd",
    surface="#14161a",
    elevated="#1b1e24",
    border="#2b303a",
    accent="#c8a45c",
    **_TONES,
)

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
GLYPH = 0.56  # An average glyph's width as a share of the font size, for wrapping.

# -- the graph ---------------------------------------------------------------------------------

NODE_FONT = 13.0
SPINE_W = 26.0
RADIUS = 8.0
PADDING = 12.0
PAD_Y = 8.0
LINE_H = 17.0
STAT_FONT = 11.0
PILL_H = 14.0
GRAPH_MARGIN = 48.0
EDGE_REACH_MIN = 40.0
HEAD = 8.0


def graph_bounds(graph: Graph) -> tuple[float, float, float, float]:
    """The drawing's viewBox — every card and region, with a margin — as x, y, width, height."""
    xs = [node.x for node in graph.nodes] + [region.x for region in graph.regions]
    ys = [node.y for node in graph.nodes] + [region.y for region in graph.regions]
    rights = [node.x + node.w for node in graph.nodes] + [r.x + r.w for r in graph.regions]
    bottoms = [node.y + node.h for node in graph.nodes] + [r.y + r.h for r in graph.regions]
    x0, y0 = min(xs) - GRAPH_MARGIN, min(ys) - GRAPH_MARGIN
    x1, y1 = max(rights) + GRAPH_MARGIN, max(bottoms) + GRAPH_MARGIN
    return x0, y0, x1 - x0, y1 - y0


def graph_svg(graph: Graph, colors: Colors) -> str:
    """The plan as the canvas shows it, in one ``<svg>`` whose viewBox is the graph's bounds."""
    if not graph.nodes:
        return ""
    x0, y0, width, height = graph_bounds(graph)
    by_id = {node.id: node for node in graph.nodes}
    out = [
        f'<svg class="graph" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_n(x0)} {_n(y0)} {_n(width)} {_n(height)}" '
        f'width="{_n(width)}" height="{_n(height)}" font-family="{FONT}" '
        f'font-size="{_n(NODE_FONT)}">'
    ]
    for region in graph.regions:
        out.append(
            f'<g class="region"><rect x="{_n(region.x)}" y="{_n(region.y)}" '
            f'width="{_n(region.w)}" height="{_n(region.h)}" rx="{_n(RADIUS)}" '
            f'fill="{colors.ink}" fill-opacity="0.04" stroke="{colors.ink}" '
            f'stroke-opacity="0.24" stroke-width="1"/>'
            f'<text x="{_n(region.x + 10)}" y="{_n(region.y + 17)}" fill="{colors.secondary}" '
            f'font-size="12" font-weight="600">{_t(region.title)}</text></g>'
        )
    for edge in graph.edges:
        source, target = by_id.get(edge.source), by_id.get(edge.target)
        if source is None or target is None:
            continue
        out.append(_edge(source, target, edge.kind, colors))
    for node in graph.nodes:
        out.append(_card(node, colors))
    out.append("</svg>")
    return "".join(out)


def _edge(source: Node, target: Node, kind: str, colors: Colors) -> str:
    # The near edges face each other, mid-height, as the scene's anchor_toward picks them.
    forward = source.x + source.w / 2 <= target.x + target.w / 2
    sx = source.x + source.w if forward else source.x
    tx = target.x if forward else target.x + target.w
    sy, ty = source.y + source.h / 2, target.y + target.h / 2
    reach = max(EDGE_REACH_MIN, abs(tx - sx) / 2)
    c1x = sx + reach if forward else sx - reach
    c2x = tx - reach if forward else tx + reach
    path = f"M{_n(sx)},{_n(sy)} C{_n(c1x)},{_n(sy)} {_n(c2x)},{_n(ty)} {_n(tx)},{_n(ty)}"
    dash = ' stroke-dasharray="6 4"' if kind == "relates" else ""
    out = (
        f'<g class="edge edge-{kind}" data-from="{_t(source.id)}" data-to="{_t(target.id)}">'
        f'<path d="{path}" fill="none" stroke="{colors.ink}" stroke-opacity="0.5" '
        f'stroke-width="1.4"{dash}/>'
    )
    if kind == "requires":
        # The curve arrives level, so the head points along the x axis, into the card.
        out += _arrow_head(tx, ty, 0.0 if forward else pi, colors.ink)
    return out + "</g>"


def _arrow_head(x: float, y: float, angle: float, color: str) -> str:
    left = (x - HEAD * cos(angle - 0.45), y - HEAD * sin(angle - 0.45))
    right = (x - HEAD * cos(angle + 0.45), y - HEAD * sin(angle + 0.45))
    points = f"{_n(x)},{_n(y)} {_n(left[0])},{_n(left[1])} {_n(right[0])},{_n(right[1])}"
    return f'<polygon points="{points}" fill="{color}" fill-opacity="0.6"/>'


def _card(node: Node, colors: Colors) -> str:
    x, y, w, h = node.x, node.y, node.w, node.h
    done = node.status == "done"
    tone = _body_tone(node, colors)
    spine = {"in-progress": colors.busy, "blocked": colors.bad, "done": colors.good}.get(
        node.status
    )
    out = [
        f'<g class="node kind-{node.kind or "step"} status-{node.status or "pending"}" '
        f'data-step="{_t(node.id)}"><title>{_t(node.key + " " + node.title)}</title>'
        f'<rect class="shadow" x="{_n(x)}" y="{_n(y + 2)}" width="{_n(w)}" height="{_n(h)}" '
        f'rx="{_n(RADIUS)}" fill="{colors.ink}" fill-opacity="0.06"/>'
        f'<rect class="body" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
        f'rx="{_n(RADIUS)}" fill="{colors.surface}" stroke="{colors.border}" stroke-width="1"/>'
    ]
    if tone is not None:
        out.append(
            f'<rect class="tint" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
            f'rx="{_n(RADIUS)}" fill="{tone}" fill-opacity="0.16"/>'
        )
    # The spine: rounded on the card's left corners, square against the body.
    r = RADIUS
    spine_path = (
        f"M{_n(x + r)},{_n(y)} H{_n(x + SPINE_W)} V{_n(y + h)} H{_n(x + r)} "
        f"Q{_n(x)},{_n(y + h)} {_n(x)},{_n(y + h - r)} V{_n(y + r)} "
        f"Q{_n(x)},{_n(y)} {_n(x + r)},{_n(y)} Z"
    )
    if spine is not None:
        out.append(f'<path class="spine" d="{spine_path}" fill="{spine}" fill-opacity="0.38"/>')
    else:
        out.append(
            f'<path class="spine" d="{spine_path}" fill="{colors.ink}" fill-opacity="0.06"/>'
        )
    cx, cy = x + SPINE_W / 2, y + h / 2
    out.append(
        f'<text class="key" x="{_n(cx)}" y="{_n(cy)}" transform="rotate(-90 {_n(cx)} {_n(cy)})" '
        f'text-anchor="middle" dominant-baseline="central" font-size="11" font-weight="700" '
        f'fill="{colors.ink}" fill-opacity="0.85">{_t(node.key)}</text>'
    )
    inner_x = x + SPINE_W + 4 + PAD_Y
    inner_w = w - SPINE_W - 4 - PAD_Y - PADDING
    reserved = LINE_H if (node.stat or node.status in ("in-progress", "blocked")) else 0.0
    max_lines = max(1, int((h - 2 * PAD_Y - reserved) // LINE_H))
    title = ("✓ " if done else "") + node.title
    lines = _wrap(title, inner_w, NODE_FONT, max_lines)
    first_y = y + PAD_Y + NODE_FONT
    ink_opacity = "0.55" if done else "1"
    # One <text> per line rather than <tspan> breaks: QtSvg honours neither dy nor a
    # tspan's x, and ran the lines together on paper.
    out.extend(
        f'<text class="title" x="{_n(inner_x)}" y="{_n(first_y + index * LINE_H)}" '
        f'fill="{colors.ink}" fill-opacity="{ink_opacity}">{_t(line)}</text>'
        for index, line in enumerate(lines)
    )
    if node.stat:
        out.append(
            f'<text class="stat" x="{_n(x + w - PADDING)}" y="{_n(y + h - PAD_Y - 2)}" '
            f'text-anchor="end" font-size="{_n(STAT_FONT)}" fill="{colors.ink}"'
            f"{' font-weight="700"' if node.kind == 'milestone' else ''}>{_t(node.stat)}</text>"
        )
    if node.status in ("in-progress", "blocked"):
        word = node.status.replace("-", " ")
        out.append(_pill(inner_x - 4, y + h - PILL_H / 2, word, spine or colors.ink, colors))
    if node.badge:
        width = _text_width(node.badge, 10.0) + 12
        out.append(
            _pill(
                x + w - 10 - width,
                y - PILL_H / 2,
                node.badge,
                node.color or colors.milestone,
                colors,
            )
        )
    out.append("</g>")
    return "".join(out)


def _body_tone(node: Node, colors: Colors) -> str | None:
    # Done outranks a kind, and a milestone outranks a feature — the canvas's rule.
    if node.status == "done":
        return colors.good
    if node.kind == "milestone":
        # Its own shade where the plan deals one; the family otherwise, which is what a
        # milestone wore before a project had a colour map.
        return node.color or colors.milestone
    if node.kind == "feature":
        return colors.feature
    return None


def _pill(x: float, y: float, word: str, color: str, colors: Colors) -> str:
    width = _text_width(word, 10.0) + 12
    return (
        f'<g class="pill"><rect x="{_n(x)}" y="{_n(y)}" width="{_n(width)}" height="{_n(PILL_H)}" '
        f'rx="{_n(PILL_H / 2)}" fill="{color}" fill-opacity="0.9" stroke="{colors.surface}" '
        f'stroke-width="1"/><text x="{_n(x + width / 2)}" y="{_n(y + PILL_H / 2)}" '
        f'text-anchor="middle" dominant-baseline="central" font-size="10" font-weight="600" '
        f'fill="{colors.surface}">{_t(word)}</text></g>'
    )


def _wrap(text: str, width: float, font: float, max_lines: int) -> list[str]:
    room = max(4, int(width / (font * GLYPH)))
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= room or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    used = " ".join(lines)
    if len(used) < len(" ".join(words)) or (lines and len(lines[-1]) > room):
        last = lines[-1]
        lines[-1] = (last[: max(1, room - 1)].rstrip() + "…") if len(last) >= room else last + "…"
    return lines or [""]


def _text_width(text: str, font: float) -> float:
    return len(text) * font * GLYPH


# -- the progress chart ------------------------------------------------------------------------

CHART_W = 720.0
AMOUNT_H = 130.0  # A work plot; the shift plot is a row per milestone.
SHIFT_ROW_H = 26.0
TITLE_H = 18.0  # The band over each plot: its name at the left, its keys at the right.
PLOT_GAP = 18.0
CHART_RIGHT = 16.0
CHART_TOP = 4.0  # Air over the first plot's title.
CHART_BOTTOM = 26.0  # The one date gutter, under the last plot.
GUTTER_MIN = 46.0  # Room for "7.5w".
GUTTER_MAX = 150.0  # A long milestone name is clipped rather than pushing the plots over.
GUTTER_PAD = 12.0
TICK_ROOM = 64.0
TODAY_ROOM = 34.0  # A date closer than this to today's word gives way to it.
PAD_DAYS = 1
LINE_W = 2.0
MARKER = 4.0
LANDING_MARK = 3.5
CHECK_MARK = 6.0  # A done milestone's circle, with its check.
CHANGE_MARK = 7.0  # A day's ▲ or ▼ under the scope line.
ARROW_HEAD = 5.0
# The window's alphas (``time_estimates/plotting.py``), as opacities.
FILL_OPACITY = "0.19"
WEEKEND_OPACITY = "0.05"
DONE_OPACITY = "0.1"
SAME = 1e-9  # Two amounts of work closer than this are the same.
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class _Panel:
    """One stacked plot's box, and the band above it its title sits in. ``scale`` is
    what an amount plot's top stands for, in days."""

    kind: PlotKind
    top: float
    height: float
    scale: float = 1.0

    @property
    def bottom(self) -> float:
        return self.top + self.height


def _panels(chart: Chart) -> list[_Panel]:
    """The plots top to bottom. A shift plot is as tall as it has milestones; an amount
    plot is a fixed box, because its scale is the data's."""
    found: list[_Panel] = []
    cursor = CHART_TOP + TITLE_H
    for plot in chart.plots:
        rows = len(chart.milestones)
        if plot.kind == "shift" and not rows:
            continue
        height = rows * SHIFT_ROW_H if plot.kind == "shift" else AMOUNT_H
        found.append(_Panel(plot.kind, cursor, height, plot.ceiling))
        cursor += height + PLOT_GAP + TITLE_H
    return found


def chart_svg(chart: Chart, colors: Colors) -> str:
    """Stacked plots on one locked time axis — the Time tab's Milestones and Work pages.

    Every plot is drawn against the same first and last day — the earliest and latest
    date anything in the chart has to show — so a point placed in one plot is placed in
    all of them; the date marks fall as hairlines through each, and their labels are
    printed once, under the last. The shift plot gives each milestone a row; the scope
    plot and the done plot share one scale in days, with weekends as pale bands.
    """
    panels = _panels(chart)
    if not panels:
        return ""
    days = [chart.today, *(when for when, _ in chart.marks)]
    for plot in chart.plots:
        for series in plot.series:
            days += [when for when, _ in series.points]
    for stretch in chart.stretches:
        days += [when for when in (stretch.finish, stretch.was_finish) if when is not None]
    first, last = min(days) - timedelta(days=PAD_DAYS), max(days) + timedelta(days=PAD_DAYS)
    if last <= first:
        last = first + timedelta(days=1)
    span = (last - first).days
    left = _gutter(chart)
    plot_w = CHART_W - left - CHART_RIGHT
    right = left + plot_w
    height = panels[-1].bottom + CHART_BOTTOM

    def x(when: date) -> float:
        return left + (when - first).days / span * plot_w

    def y(panel: _Panel, value: float) -> float:
        share = value / panel.scale if panel.scale else 0.0
        return panel.top + (1.0 - max(0.0, min(1.0, share))) * panel.height

    ticks = axis_ticks(first, last, int(plot_w // TICK_ROOM))
    out = [
        f'<svg class="chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(CHART_W)} '
        f'{_n(height)}" width="{_n(CHART_W)}" height="{_n(height)}" font-family="{FONT}" '
        f'font-size="11" data-first="{first.isoformat()}" data-last="{last.isoformat()}" '
        f'data-left="{_n(left)}" data-right="{_n(right)}" '
        f'data-top="{_n(panels[0].top)}" data-bottom="{_n(panels[-1].bottom)}">'
    ]
    by_kind = {plot.kind: plot for plot in chart.plots}
    for panel in panels:
        plot = by_kind[panel.kind]
        amount = panel.kind in AMOUNT_PLOTS
        out.append(
            f'<g class="plot plot-{panel.kind}" data-kind="{panel.kind}"'
            f'{' data-unit="days"' if amount else ""} data-top="{_n(panel.top)}" '
            f'data-bottom="{_n(panel.bottom)}">'
        )
        out.append(_plot_title(plot, panel, left, plot_w, colors))
        if amount:
            out.append(_weekends(panel, first, last, x, left, right, colors))
            out.append(_waits(chart, panel, x, left, right, colors))
        out.append(_plot_grid(chart, panel, ticks, x, y, left, plot_w, colors))
        if panel.kind == "scope":
            out.append(_scope_plot(chart, plot, panel, x, y, last, colors))
        elif panel.kind == "done":
            out.append(_done_plot(chart, plot, panel, x, y, colors))
        else:
            out.append(_shift_plot(chart, panel, x, left, right, colors))
        out.append("</g>")
    # A saved snapshot's day: a dashed hairline through every plot, named in its tooltip
    # — a title printed over the plots ran into the first one's dates, and the chart's
    # note names them for paper.
    for when, title in chart.marks:
        if not first <= when <= last:
            continue
        at = x(when)
        out.append(
            f'<g class="mark" data-title="{_t(title)}"><title>{_t(title)}</title>'
            f'<line x1="{_n(at)}" x2="{_n(at)}" y1="{_n(panels[0].top)}" '
            f'y2="{_n(panels[-1].bottom)}" stroke="{colors.ink}" stroke-opacity="0.45" '
            f'stroke-dasharray="4 3"/></g>'
        )
    # Today, and the dates: one line down every plot, one row of labels under the last,
    # with today's own word under its line and any date that would touch it left out.
    base = panels[-1].bottom + 15
    showing = first <= chart.today <= last
    if showing:
        now = x(chart.today)
        out.append(
            f'<line class="today" x1="{_n(now)}" x2="{_n(now)}" y1="{_n(panels[0].top)}" '
            f'y2="{_n(panels[-1].bottom)}" stroke="{colors.ink}" stroke-opacity="0.35" '
            f'stroke-dasharray="3 3"/><text class="today-word" x="{_n(now)}" y="{_n(base)}" '
            f'text-anchor="middle" font-weight="600" fill="{colors.ink}">today</text>'
        )
    for when, label in ticks:
        if showing and abs(x(when) - x(chart.today)) < TODAY_ROOM:
            continue
        out.append(
            f'<text class="axis" x="{_n(x(when))}" y="{_n(base)}" '
            f'text-anchor="middle" fill="{colors.secondary}">{_t(label)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _gutter(chart: Chart) -> float:
    """The left gutter: room for the scale's labels and for the milestone names the shift
    plot puts there, clipped so one long name cannot push every plot to the right."""
    widest = max(
        (_text_width(_clip(stretch.label, 20), 11.0) for stretch in chart.milestones),
        default=0.0,
    )
    return min(GUTTER_MAX, max(GUTTER_MIN, widest + GUTTER_PAD))


def _plot_title(plot: Plot, panel: _Panel, left: float, plot_w: float, colors: Colors) -> str:
    """The plot's name at the left of its band, its keys at the right — dropped when the
    two would meet, since the page's tooltip answers anyway."""
    y = panel.top - TITLE_H / 2
    out = [
        f'<text class="plot-title" x="{_n(left)}" y="{_n(y)}" dominant-baseline="central" '
        f'font-size="12" fill="{colors.ink}">{_t(plot.title)}</text>'
    ]
    keys = _keys(plot, colors)
    room = plot_w - _text_width(plot.title, 12.0) - 24
    width = sum(24 + _text_width(label, 11.0) + 18 for label, _ in keys)
    if keys and width <= room:
        cursor = left + plot_w - width + 18
        for label, mark in keys:
            out.append(
                f'<g class="legend">{mark(cursor, y)}'
                f'<text x="{_n(cursor + 24)}" y="{_n(y)}" dominant-baseline="central" '
                f'fill="{colors.secondary}">{_t(label)}</text></g>'
            )
            cursor += 24 + _text_width(label, 11.0) + 18
    return "".join(out)


def _keys(plot: Plot, colors: Colors) -> list[tuple[str, Callable[[float, float], str]]]:
    """A key per thing the plot draws, each a small sample of it."""

    def line(color: str, css: str, dash: str = "") -> Callable[[float, float], str]:
        def draw(cursor: float, y: float) -> str:
            return (
                f'<line class="{css}" x1="{_n(cursor)}" x2="{_n(cursor + 18)}" y1="{_n(y)}" '
                f'y2="{_n(y)}" stroke="{color}" stroke-width="2"{dash}/>'
            )

        return draw

    def dot(fill: str, ring: str) -> Callable[[float, float], str]:
        def draw(cursor: float, y: float) -> str:
            return (
                f'<circle class="then" cx="{_n(cursor + 9)}" cy="{_n(y)}" r="{_n(MARKER)}" '
                f'fill="{fill}" stroke="{ring}" stroke-width="1.5"/>'
            )

        return draw

    def check(cursor: float, y: float) -> str:
        return _check(cursor + 9, y, colors.secondary, CHECK_MARK - 1)

    def patch(color: str, up: bool) -> Callable[[float, float], str]:
        def draw(cursor: float, y: float) -> str:
            return (
                f'<rect x="{_n(cursor)}" y="{_n(y - 6)}" width="18" height="12" rx="2" '
                f'fill="{color}" fill-opacity="{FILL_OPACITY}"/>'
                + _triangle(cursor + 9, y, CHANGE_MARK, up, color)
            )

        return draw

    dashed = ' stroke-dasharray="6 4"'
    if plot.kind == "shift":
        return [
            ("then", dot(colors.surface, colors.secondary)),
            ("now", dot(colors.secondary, colors.secondary)),
            ("done", check),
        ]
    if plot.kind == "scope":
        found = [("scope", line(colors.plan, "key-plan"))]
        if any(series.role == "baseline" for series in plot.series):
            found.append(("then", line(colors.secondary, "key-secondary", dashed)))
        return [*found, ("added", patch(colors.warm, True)), ("removed", patch(colors.cool, False))]
    return [
        ("done", line(colors.ink, "key-ink")),
        (
            "no status change",
            line(colors.ink, "key-ink", ' stroke-dasharray="0.1 4" stroke-linecap="round"'),
        ),
        ("the plan's schedule", line(colors.secondary, "key-secondary", dashed)),
    ]


def _weekends(
    panel: _Panel,
    first: date,
    last: date,
    x: Callable[[date], float],
    left: float,
    right: float,
    colors: Colors,
) -> str:
    """A pale band over each weekend: a day runs from the point before to its own, the
    window's rule."""
    out = []
    day = first + _ONE_DAY
    while day <= last:
        if day.weekday() < SATURDAY:
            day += _ONE_DAY
            continue
        end = day
        while end + _ONE_DAY <= last and (end + _ONE_DAY).weekday() >= SATURDAY:
            end += _ONE_DAY
        x0, x1 = max(left, x(day - _ONE_DAY)), min(right, x(end))
        out.append(
            f'<rect class="weekend" x="{_n(x0)}" y="{_n(panel.top)}" width="{_n(x1 - x0)}" '
            f'height="{_n(panel.height)}" fill="{colors.ink}" fill-opacity="{WEEKEND_OPACITY}"/>'
        )
        day = end + _ONE_DAY
    return "".join(out)


def _waits(
    chart: Chart,
    panel: _Panel,
    x: Callable[[date], float],
    left: float,
    right: float,
    colors: Colors,
) -> str:
    """A pale band over each wait's days, dashed at its edges, named at the top of the scope
    plot — the window's hatching, which a renderer honouring no pattern cannot draw."""
    out = []
    for start, end, name in chart.waits:
        x0, x1 = max(left, x(start - _ONE_DAY)), min(right, x(end))
        if x1 <= x0:
            continue
        out.append(
            f'<g class="wait"><title>{_t(name)}</title>'
            f'<rect class="wait-band" x="{_n(x0)}" y="{_n(panel.top)}" width="{_n(x1 - x0)}" '
            f'height="{_n(panel.height)}" fill="{colors.ink}" fill-opacity="0.07" '
            f'stroke="{colors.ink}" stroke-opacity="0.3" stroke-dasharray="2 2"/>'
        )
        if panel.kind == "scope":
            out.append(
                f'<text class="wait-name" x="{_n(x0 + 3)}" y="{_n(panel.top + 10)}" '
                f'font-size="10" fill="{colors.secondary}">'
                f"{_t(_clip(name, max(1, int((x1 - x0) / (10 * GLYPH)))))}</text>"
            )
        out.append("</g>")
    return "".join(out)


def _plot_grid(
    chart: Chart,
    panel: _Panel,
    ticks: Sequence[Tick],
    x: Callable[[date], float],
    y: Callable[[_Panel, float], float],
    left: float,
    plot_w: float,
    colors: Colors,
) -> str:
    """Hairlines at every date mark down the plot, and — on an amount plot — at nothing,
    half and the top of its scale, labelled in days; a guide per row on the shift plot."""
    out = []
    if panel.kind == "shift":
        for index in range(len(chart.milestones)):
            row = panel.top + (index + 0.5) * SHIFT_ROW_H
            out.append(
                f'<line class="grid" x1="{_n(left)}" x2="{_n(left + plot_w)}" y1="{_n(row)}" '
                f'y2="{_n(row)}" stroke="{colors.ink}" stroke-opacity="0.1"/>'
            )
    else:
        for share in (0.0, 0.5, 1.0):
            at = y(panel, share * panel.scale)
            opacity = 0.12 if share else 0.25  # The floor is the stronger line.
            out.append(
                f'<line class="grid" x1="{_n(left)}" x2="{_n(left + plot_w)}" y1="{_n(at)}" '
                f'y2="{_n(at)}" stroke="{colors.ink}" stroke-opacity="{opacity}"/>'
                f'<text class="axis" x="{_n(left - 8)}" y="{_n(at)}" text-anchor="end" '
                f'dominant-baseline="central" fill="{colors.secondary}">'
                f"{format_days(share * panel.scale) or '0d'}</text>"
            )
    for when, _ in ticks:
        out.append(
            f'<line class="grid" x1="{_n(x(when))}" x2="{_n(x(when))}" y1="{_n(panel.top)}" '
            f'y2="{_n(panel.bottom)}" stroke="{colors.ink}" stroke-opacity="0.12"/>'
        )
    return "".join(out)


def _scope_plot(
    chart: Chart,
    plot: Plot,
    panel: _Panel,
    x: Callable[[date], float],
    y: Callable[[_Panel, float], float],
    last: date,
    colors: Colors,
) -> str:
    """The work the plan held on each recorded day against the plan compared with, the
    area between them warm where the plan holds more than it did and cool where less, and
    a ▲ or ▼ under the line each day the scope changed, by the day's sum."""
    roles = {series.role: series for series in plot.series}
    scope, base = roles.get("plan"), roles.get("baseline")
    if scope is None or not scope.points:
        return ""
    out = []
    if base is not None and base.points:
        since, level = base.points[0]
        for index, (when, value) in enumerate(scope.points):
            start = max(when, since)
            end = scope.points[index + 1][0] if index + 1 < len(scope.points) else chart.today
            if end <= start or abs(value - level) < SAME:
                continue
            upper, lower = y(panel, max(value, level)), y(panel, min(value, level))
            more = value > level
            out.append(
                f'<rect class="change-{"more" if more else "less"}" x="{_n(x(start))}" '
                f'y="{_n(upper)}" width="{_n(x(end) - x(start))}" height="{_n(lower - upper)}" '
                f'fill="{colors.warm if more else colors.cool}" fill-opacity="{FILL_OPACITY}"/>'
            )
        at = y(panel, level)
        out.append(
            _series_line(
                base,
                [(x(since), at), (x(last), at)],
                colors.secondary,
                1.0,
                ' stroke-dasharray="6 4"',
            )
        )
    corners = _step_corners(scope.points, chart.today, x, lambda value: y(panel, value))
    out.append(_series_line(scope, corners, colors.plan, LINE_W, ""))
    if len(corners) == 1:
        out.append(_marker(*corners[0], colors.plan, colors.surface))
    for change in plot.changes:
        # Under the line, just after the day: the window's place for it.
        cx = x(change.day) + 6
        cy = y(panel, _step_at(scope.points, change.day) or 0.0) + CHANGE_MARK
        mark = _triangle(cx, cy, CHANGE_MARK, change.up, colors.warm if change.up else colors.cool)
        out.append(f'<g class="change"><title>{_t(change.words)}</title>{mark}</g>')
    return "".join(out)


def _done_plot(
    chart: Chart,
    plot: Plot,
    panel: _Panel,
    x: Callable[[date], float],
    y: Callable[[_Panel, float], float],
    colors: Colors,
) -> str:
    """What was done — solid across a day some step changed status, dotted across one none
    did — the plan's schedule from today on, dashed, and each milestone where it ends: a
    check on the done line once its work is done, a dot on the schedule until then."""
    roles = {series.role: series for series in plot.series}
    done, schedule = roles.get("actual"), roles.get("plan")

    def level(value: float) -> float:
        return y(panel, value)

    out = []
    if schedule is not None and len(schedule.points) > 1:
        corners = _step_corners(schedule.points, schedule.points[-1][0], x, level)
        out.append(
            _series_line(
                schedule, corners, colors.secondary, 1.5, ' stroke-dasharray="6 4"', css="schedule"
            )
        )
    if done is not None and done.points:
        corners = _step_corners(done.points, chart.today, x, level)
        floor = level(0.0)
        ring = [*corners, (corners[-1][0], floor), (corners[0][0], floor)]
        out.append(
            f'<polygon class="done-area" points="{_points(ring)}" fill="{colors.ink}" '
            f'fill-opacity="{DONE_OPACITY}"/>'
        )
        out.append(_series_line(done, corners, colors.ink, LINE_W, ""))
        out.append(_idle(done.points, set(plot.active), chart.today, x, level, colors))
        if len(corners) == 1:
            out.append(_marker(*corners[0], colors.ink, colors.surface))
    out.append(_milestone_marks(chart, done, schedule, panel, x, level, colors))
    return "".join(out)


def _idle(
    points: Sequence[tuple[date, float]],
    active: set[date],
    today: date,
    x: Callable[[date], float],
    level: Callable[[float], float],
    colors: Colors,
) -> str:
    """Each run of days no step changed status, dotted: the solid line masked in the
    surface, then dotted over it. The level holds across a run — only a day some step
    changed status moves it."""
    out = []
    day = points[0][0] + _ONE_DAY
    while day <= today:
        if day in active:
            day += _ONE_DAY
            continue
        end = day
        while end + _ONE_DAY <= today and end + _ONE_DAY not in active:
            end += _ONE_DAY
        at = level(_step_at(points, day - _ONE_DAY) or 0.0)
        x0, x1 = x(day - _ONE_DAY), x(end)
        out.append(
            f'<line class="idle-mask" x1="{_n(x0)}" x2="{_n(x1)}" y1="{_n(at)}" y2="{_n(at)}" '
            f'stroke="{colors.surface}" stroke-width="{_n(LINE_W + 1)}"/>'
            f'<line class="idle" x1="{_n(x0)}" x2="{_n(x1)}" y1="{_n(at)}" y2="{_n(at)}" '
            f'stroke="{colors.ink}" stroke-width="{_n(LINE_W)}" stroke-dasharray="0.1 4" '
            f'stroke-linecap="round"/>'
        )
        day = end + _ONE_DAY
    return "".join(out)


def _milestone_marks(
    chart: Chart,
    done: Series | None,
    schedule: Series | None,
    panel: _Panel,
    x: Callable[[date], float],
    level: Callable[[float], float],
    colors: Colors,
) -> str:
    """Each milestone where it ends, named over its mark — beside it where over would
    leave the plot — and a name that would sit on another's left to the tooltip. Milestones
    landing on one day share the mark, a wedge each that picks its own step, and the name."""
    out = []
    labelled: list[tuple[float, float]] = []
    for landing in chart.landings:
        first = landing[0]
        assert first.finish is not None  # A landing is where some milestone ends.
        line = done if first.done else schedule
        value = _step_at(line.points, first.finish) if line is not None else None
        cx, cy = x(first.finish), level(value or 0.0)
        note = "\n\n".join(stretch.note for stretch in landing)
        out.append(f'<g class="landing" data-step="{_t(first.step_id)}"><title>{_t(note)}</title>')
        radius = CHECK_MARK if first.done else LANDING_MARK + 1
        if len(landing) > 1:
            out.append(_wedges(cx, cy, radius, landing))
            out.append(
                _tick(cx, cy, radius)
                if first.done
                else f'<circle class="ring" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(radius)}" '
                f'fill="none" stroke="{colors.surface}" stroke-width="1.5"/>'
            )
        elif first.done:
            out.append(_check(cx, cy, first.color, radius))
        else:
            out.append(
                f'<circle class="ring" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(radius)}" '
                f'fill="{first.color}" stroke="{colors.surface}" stroke-width="1.5"/>'
            )
        name = " · ".join(_clip(stretch.label, 16) for stretch in landing)
        width = _text_width(name, 11.0)
        spot, anchor = (cx, cy - radius - 7), "middle"
        if spot[1] - 6 < panel.top:
            spot, anchor = (cx - radius - 4, cy), "end"
        middle = spot[0] if anchor == "middle" else spot[0] - width / 2
        if not any(abs(middle - px) < 28 and abs(spot[1] - py) < 14 for px, py in labelled):
            labelled.append((middle, spot[1]))
            out.append(
                f'<text class="landing-name" x="{_n(spot[0])}" y="{_n(spot[1])}" '
                f'text-anchor="{anchor}" dominant-baseline="central" font-weight="600" '
                f'fill="{colors.ink}">{_t(name)}</text>'
            )
        out.append("</g>")
    return "".join(out)


def _shift_plot(
    chart: Chart,
    panel: _Panel,
    x: Callable[[date], float],
    left: float,
    right: float,
    colors: Colors,
) -> str:
    """A row per milestone: its name in the gutter, a line dropping from where it ends to
    the axis, a hollow mark where the plan compared with landed it, a filled one where the
    plan now does — a check where its work is done — an arrow between them and the dates
    beside them."""
    out = []
    for index, stretch in enumerate(chart.milestones):
        row = panel.top + (index + 0.5) * SHIFT_ROW_H
        out.append(
            f'<g class="shift" data-step="{_t(stretch.step_id)}" data-words="{_t(stretch.note)}">'
        )
        if stretch.finish is not None:
            # Down to the axis, so the day it ends can be read off the scale. Drawn
            # first: every mark and every date is painted over it.
            drop = x(stretch.finish)
            out.append(
                f'<line class="drop" x1="{_n(drop)}" x2="{_n(drop)}" y1="{_n(row)}" '
                f'y2="{_n(panel.bottom)}" stroke="{stretch.color}" stroke-opacity="0.35" '
                f'stroke-width="1"/>'
            )
        out.append(
            f'<text class="label" x="{_n(left - 8)}" y="{_n(row)}" text-anchor="end" '
            f'dominant-baseline="central" fill="{colors.secondary}">'
            f"{_t(_clip(stretch.label, 20))}</text>"
        )
        then, now = stretch.was_finish, stretch.finish
        if then is not None and now is not None and then != now:
            out.append(_arrow(x(then), x(now), row, stretch.color))
        if then is not None:
            radius = MARKER + (1.5 if then == now else 0.0)
            out.append(
                f'<circle class="then" cx="{_n(x(then))}" cy="{_n(row)}" r="{_n(radius)}" '
                f'fill="{colors.surface}" stroke="{stretch.color}" stroke-width="1.5"/>'
            )
        if now is not None and stretch.done:
            out.append(_check(x(now), row, stretch.color, CHECK_MARK))
        elif now is not None:
            out.append(
                f'<circle class="now" cx="{_n(x(now))}" cy="{_n(row)}" r="{_n(LANDING_MARK)}" '
                f'fill="{stretch.color}"/>'
            )
        for text, spot in _row_dates(stretch, chart.today, x, left, right):
            out.append(
                f'<text class="row-date" x="{_n(spot)}" y="{_n(row)}" '
                f'dominant-baseline="central" fill="{colors.secondary}">{_t(text)}</text>'
            )
        if stretch.note:
            out.append(f"<title>{_t(stretch.note)}</title>")
        out.append("</g>")
    return "".join(out)


def _row_dates(
    stretch: Stretch, today: date, x: Callable[[date], float], left: float, right: float
) -> list[tuple[str, float]]:
    """A milestone row's dates and where they start: where it ends now, and — when it
    moved — where the plan then landed it. The window's rule, said in SVG: a date sits
    beside its own mark, outside the pair when there is room and inside it otherwise, and
    is left out rather than squeezed."""
    found = []
    spots = [(stretch.finish, stretch.was_finish)] if stretch.finish is not None else []
    if stretch.was_finish is not None and stretch.was_finish != stretch.finish:
        spots.append((stretch.was_finish, stretch.finish))
    for when, other in spots:
        assert when is not None
        text = short_date(when, today=today)
        width = _text_width(text, 11.0)
        mark = x(when)
        away = -1.0 if other is not None and x(other) > mark else 1.0
        for way in (away, -away):
            start = mark + LANDING_MARK + 5 if way > 0 else mark - LANDING_MARK - 5 - width
            if start < left or start + width > right:
                continue
            if other is not None:
                keep = x(other)
                if start < keep + LANDING_MARK + 5 and keep - LANDING_MARK - 5 < start + width:
                    continue
            found.append((text, start))
            break
    return found


def _arrow(start: float, end: float, row: float, color: str) -> str:
    """The shaft and head between a milestone's two landings, stopping short of the mark."""
    way = 1.0 if end >= start else -1.0
    tip = end - way * (LANDING_MARK + 1.0)
    head = (
        f"M{_n(tip)},{_n(row)} L{_n(tip - way * ARROW_HEAD)},{_n(row - ARROW_HEAD * 0.55)} "
        f"L{_n(tip - way * ARROW_HEAD)},{_n(row + ARROW_HEAD * 0.55)} Z"
    )
    return (
        f'<line x1="{_n(start)}" x2="{_n(tip)}" y1="{_n(row)}" y2="{_n(row)}" '
        f'stroke="{color}" stroke-width="1.5" stroke-opacity="0.8"/>'
        f'<path d="{head}" fill="{color}" fill-opacity="0.8"/>'
    )


def _check(cx: float, cy: float, color: str, radius: float) -> str:
    """A circle with a check, in the milestone's colour: its work is done. The check is
    white on either theme, as in the window."""
    return (
        f'<circle class="done-mark" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(radius)}" '
        f'fill="{color}"/>{_tick(cx, cy, radius)}'
    )


def _tick(cx: float, cy: float, radius: float) -> str:
    k = radius / 8.0  # The window's check is drawn for a circle of eight.
    tick = (
        f"M{_n(cx - 3.8 * k)},{_n(cy + 0.2 * k)} L{_n(cx - 1.0 * k)},{_n(cy + 3.0 * k)} "
        f"L{_n(cx + 4.0 * k)},{_n(cy - 3.0 * k)}"
    )
    return (
        f'<path d="{tick}" fill="none" stroke="#ffffff" stroke-width="{_n(max(1.5, 2 * k))}" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _wedges(cx: float, cy: float, radius: float, landing: Sequence[Stretch]) -> str:
    """A circle cut into a wedge per milestone, clockwise from twelve — the window's shared
    mark — each wedge its own step's, so a click picks the one under it."""
    out = []
    share = 2 * pi / len(landing)
    for index, stretch in enumerate(landing):
        start, end = -pi / 2 + index * share, -pi / 2 + (index + 1) * share
        edge = f"{_n(cx + radius * cos(start))},{_n(cy + radius * sin(start))}"
        rim = f"{_n(cx + radius * cos(end))},{_n(cy + radius * sin(end))}"
        out.append(
            f'<g data-step="{_t(stretch.step_id)}"><path class="wedge" '
            f'd="M{_n(cx)},{_n(cy)} L{edge} A{_n(radius)},{_n(radius)} 0 0 1 {rim} Z" '
            f'fill="{stretch.color}"/></g>'
        )
    return "".join(out)


def _triangle(cx: float, cy: float, size: float, up: bool, color: str) -> str:
    """A ▲ or ▼ ``size`` across, filled."""
    half = size / 2
    tip = -half if up else half
    corners = [(cx, cy + tip), (cx - half, cy - tip), (cx + half, cy - tip)]
    return f'<polygon points="{_points(corners)}" fill="{color}"/>'


def _step_at(points: Sequence[tuple[date, float]], when: date) -> float | None:
    """A step curve's value on ``when``: what the last point at or before it said."""
    found = None
    for day, value in points:
        if day > when:
            break
        found = value
    return found


def _step_corners(
    points: Sequence[tuple[date, float]],
    end: date,
    x: Callable[[date], float],
    level: Callable[[float], float],
) -> list[tuple[float, float]]:
    """A step curve's corners: each value held level until the next, the last until
    ``end`` — a record holds until the next one."""
    corners: list[tuple[float, float]] = []
    for when, value in points:
        if corners:
            corners.append((x(when), corners[-1][1]))
        corners.append((x(when), level(value)))
    if points and end > points[-1][0]:
        corners.append((x(end), corners[-1][1]))
    return corners


def _series_line(
    series: Series,
    corners: Sequence[tuple[float, float]],
    color: str,
    width: float,
    extra: str,
    *,
    css: str = "",
) -> str:
    """A series drawn through ``corners``, carrying its own points for the page's tooltip."""
    data = ";".join(f"{when.isoformat()}:{value:.4f}" for when, value in series.points)
    classes = f"series series-{series.role}" + (f" {css}" if css else "")
    return (
        f'<polyline class="{classes}" data-label="{_t(series.label)}" data-points="{data}" '
        f'points="{_points(corners)}" fill="none" stroke="{color}" '
        f'stroke-width="{_n(width)}" stroke-linejoin="round" stroke-linecap="round"{extra}/>'
    )


def _marker(cx: float, cy: float, fill: str, ring: str) -> str:
    return (
        f'<circle class="marker" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(MARKER)}" fill="{fill}" '
        f'stroke="{ring}" stroke-width="2"/>'
    )


def _points(corners: Sequence[tuple[float, float]]) -> str:
    return " ".join(f"{_n(px)},{_n(py)}" for px, py in corners)


# -- the timeline ------------------------------------------------------------------------------

TL_W = 720.0
TL_LABEL_W = 176.0
TL_ROW_H = 32.0
TL_TOP = 26.0
TL_BOTTOM = 24.0
TL_BAR_H = 16.0
TL_PAD_DAYS = 3
TL_DATE_ROOM = 96.0  # Room after the last bar for its date.


def timeline_svg(timeline: Timeline, colors: Colors) -> str:
    """One bar per milestone stretch, from its start to where the plan lands it, its shade
    filled as far as the work has landed; the date somebody set marked beside it."""
    if not timeline.spans:
        return ""
    days = [timeline.today]
    for span in timeline.spans:
        days += [span.start, span.finish or span.start, span.asked or span.start]
    first = min(days) - timedelta(days=TL_PAD_DAYS)
    last = max(days) + timedelta(days=TL_PAD_DAYS)
    if last <= first:
        last = first + timedelta(days=1)
    plot_x, plot_w = TL_LABEL_W, TL_W - TL_LABEL_W - TL_DATE_ROOM
    height = TL_TOP + TL_ROW_H * len(timeline.spans) + TL_BOTTOM
    total = (last - first).days

    def x(when: date) -> float:
        return plot_x + (when - first).days / total * plot_w

    out = [
        f'<svg class="timeline" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(TL_W)} '
        f'{_n(height)}" width="{_n(TL_W)}" height="{_n(height)}" font-family="{FONT}" '
        f'font-size="11">'
    ]
    rows_bottom = TL_TOP + TL_ROW_H * len(timeline.spans)
    for when, label in axis_ticks(first, last, int(plot_w // TICK_ROOM)):
        out.append(
            f'<line class="grid" x1="{_n(x(when))}" x2="{_n(x(when))}" y1="{_n(TL_TOP)}" '
            f'y2="{_n(rows_bottom)}" stroke="{colors.ink}" stroke-opacity="0.1"/>'
            f'<text class="axis" x="{_n(x(when))}" y="{_n(TL_TOP - 10)}" text-anchor="middle" '
            f'fill="{colors.secondary}">{_t(label)}</text>'
        )
    for index, span in enumerate(timeline.spans):
        top = TL_TOP + index * TL_ROW_H
        mid = top + TL_ROW_H / 2
        bar_y = mid - TL_BAR_H / 2
        out.append(f'<g class="span" data-step="{_t(span.step_id)}">')
        out.append(
            f'<text class="label" x="8" y="{_n(mid)}" dominant-baseline="central" font-size="12" '
            f'fill="{colors.ink}">{_t(_clip(span.label, 24))}</text>'
        )
        x0 = x(span.start)
        if span.finish is not None:
            x1 = max(x(span.finish), x0 + 3)
            out.append(
                f'<rect class="bar" x="{_n(x0)}" y="{_n(bar_y)}" width="{_n(x1 - x0)}" '
                f'height="{_n(TL_BAR_H)}" rx="4" fill="{span.color}" fill-opacity="0.32" '
                f'stroke="{span.color}" stroke-width="1"/>'
            )
            if span.share:
                out.append(
                    f'<rect class="landed" x="{_n(x0)}" y="{_n(bar_y)}" '
                    f'width="{_n((x1 - x0) * min(1.0, span.share))}" '
                    f'height="{_n(TL_BAR_H)}" rx="4" fill="{span.color}" fill-opacity="0.9"/>'
                )
            out.append(
                f'<text class="date" x="{_n(x1 + 6)}" y="{_n(mid)}" dominant-baseline="central" '
                f'fill="{colors.secondary}">{_t(format_date(span.finish, today=timeline.today))}'
                f"</text>"
            )
        else:
            out.append(
                f'<rect class="bar undated" x="{_n(x0)}" y="{_n(bar_y)}" '
                f'width="{_n(plot_x + plot_w - x0)}" height="{_n(TL_BAR_H)}" rx="4" fill="none" '
                f'stroke="{span.color}" stroke-dasharray="4 3"/>'
                f'<text class="date" x="{_n(x0 + 8)}" y="{_n(mid)}" dominant-baseline="central" '
                f'fill="{colors.secondary}">not estimated</text>'
            )
        if span.asked is not None:
            ax = x(span.asked)
            out.append(
                f'<path class="asked" d="M{_n(ax)},{_n(bar_y - 3)} l5,-6 l-10,0 z" '
                f'fill="{colors.ink}" fill-opacity="0.8"><title>set for '
                f"{_t(format_date(span.asked, today=timeline.today))}</title></path>"
            )
        out.append("</g>")
    tx = x(timeline.today)
    out.append(
        f'<line class="today" x1="{_n(tx)}" x2="{_n(tx)}" y1="{_n(TL_TOP)}" y2="{_n(rows_bottom)}" '
        f'stroke="{colors.ink}" stroke-opacity="0.35" stroke-dasharray="3 3"/>'
        f'<text class="axis" x="{_n(tx)}" y="{_n(rows_bottom + 14)}" text-anchor="middle" '
        f'fill="{colors.secondary}">today</text>'
    )
    out.append("</svg>")
    return "".join(out)


# -- helpers -----------------------------------------------------------------------------------


def _n(value: float) -> str:
    """A number as SVG wants it: no trailing zeros, no ``-0``."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _t(text: str) -> str:
    return escape(text, quote=True)


def _clip(text: str, room: int) -> str:
    return text if len(text) <= room else text[: room - 1].rstrip() + "…"
