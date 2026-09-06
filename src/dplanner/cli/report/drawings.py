"""SVG for the report: the graph as the canvas draws it, the progress chart, the timeline.

One drawing code path for screen and paper. The page inlines these; the window's PDF
renders the same strings through ``QSvgRenderer``. QtSvg reads no CSS variables and no
``<style>``, so every shape carries explicit ``fill`` and ``stroke`` from a :class:`Colors`
— and a class beside them, so the page's stylesheet can restyle the same shapes for a dark
theme, which wins over a presentation attribute.

The grammar is the window's (``project_editor/renderers.py``, ``time_estimates/chart.py``):
cards with an 8 px radius, a 26 px spine carrying the key rotated a quarter turn and washed
by status, the body tinted by kind — purple a milestone, teal a feature, green a done step —
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

from dplanner.cli.report.parts import Chart, Graph, Node, Series, Timeline
from dplanner.domain.schedule import axis_ticks, format_date


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


# The hex twins of ``theme/themes.py``'s LIGHT and DARK and ``theme/tones.py``'s tones.
# Copied rather than imported: ``theme/__init__.py`` loads Qt, and this layer may not.
_TONES = {
    "good": "#78c88c",
    "busy": "#6ea0dc",
    "bad": "#dc6e6e",
    "milestone": "#9682dc",
    "feature": "#50b4af",
    "plan": "#5f87d7",
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
        out.append(_pill(x + w - 10 - width, y - PILL_H / 2, node.badge, colors.milestone, colors))
    out.append("</g>")
    return "".join(out)


def _body_tone(node: Node, colors: Colors) -> str | None:
    # Done outranks a kind, and a milestone outranks a feature — the canvas's rule.
    if node.status == "done":
        return colors.good
    if node.kind == "milestone":
        return colors.milestone
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
CHART_H = 240.0
CHART_LEFT = 46.0
CHART_RIGHT = 16.0
CHART_TOP = 30.0
CHART_BOTTOM = 28.0
TICK_ROOM = 64.0
PAD_DAYS = 1
LINE_W = 2.0
MARKER = 4.0


def chart_svg(chart: Chart, colors: Colors) -> str:
    """Shares over dates: baseline dashed and paler, the plan solid, what landed in ink."""
    days = [chart.today]
    for series in chart.series:
        days += [when for when, _ in series.points]
    days += [mark.day for mark in chart.marks]
    first, last = min(days) - timedelta(days=PAD_DAYS), max(days) + timedelta(days=PAD_DAYS)
    if last <= first:
        last = first + timedelta(days=1)
    plot_w = CHART_W - CHART_LEFT - CHART_RIGHT
    plot_h = CHART_H - CHART_TOP - CHART_BOTTOM
    span = (last - first).days

    def x(when: date) -> float:
        return CHART_LEFT + (when - first).days / span * plot_w

    def y(share: float) -> float:
        return CHART_TOP + (1.0 - max(0.0, min(1.0, share))) * plot_h

    out = [
        f'<svg class="chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(CHART_W)} '
        f'{_n(CHART_H)}" width="{_n(CHART_W)}" height="{_n(CHART_H)}" font-family="{FONT}" '
        f'font-size="11" data-first="{first.isoformat()}" data-last="{last.isoformat()}" '
        f'data-left="{_n(CHART_LEFT)}" data-right="{_n(CHART_LEFT + plot_w)}" '
        f'data-top="{_n(CHART_TOP)}" data-bottom="{_n(CHART_TOP + plot_h)}">'
    ]
    for share in (0.0, 0.25, 0.5, 0.75, 1.0):
        out.append(
            f'<line class="grid" x1="{_n(CHART_LEFT)}" x2="{_n(CHART_LEFT + plot_w)}" '
            f'y1="{_n(y(share))}" y2="{_n(y(share))}" stroke="{colors.ink}" stroke-opacity="0.12"/>'
        )
        if share in (0.0, 0.5, 1.0):
            out.append(
                f'<text class="axis" x="{_n(CHART_LEFT - 8)}" y="{_n(y(share))}" text-anchor="end" '
                f'dominant-baseline="central" fill="{colors.secondary}">{share:.0%}</text>'
            )
    for when, label in axis_ticks(first, last, int(plot_w // TICK_ROOM)):
        out.append(
            f'<line class="grid" x1="{_n(x(when))}" x2="{_n(x(when))}" '
            f'y1="{_n(CHART_TOP + plot_h)}" y2="{_n(CHART_TOP + plot_h + 4)}" '
            f'stroke="{colors.ink}" stroke-opacity="0.3"/>'
            f'<text class="axis" x="{_n(x(when))}" y="{_n(CHART_TOP + plot_h + 17)}" '
            f'text-anchor="middle" fill="{colors.secondary}">{_t(label)}</text>'
        )
    out.append(
        f'<line class="today" x1="{_n(x(chart.today))}" x2="{_n(x(chart.today))}" '
        f'y1="{_n(CHART_TOP)}" y2="{_n(CHART_TOP + plot_h)}" stroke="{colors.ink}" '
        f'stroke-opacity="0.35" stroke-dasharray="3 3"/>'
    )
    # Labels take the first of two rows that has room; a label that would leave the plot
    # sits on the other side of its line. A third collision keeps the line and drops the words.
    rows_taken: list[list[tuple[float, float]]] = [[], []]
    for mark in chart.marks:
        mx = x(mark.day)
        out.append(
            f'<g class="mark" data-step="{_t(mark.step_id)}"><line x1="{_n(mx)}" x2="{_n(mx)}" '
            f'y1="{_n(CHART_TOP)}" y2="{_n(CHART_TOP + plot_h)}" stroke="{colors.secondary}" '
            f'stroke-opacity="0.55"/>'
        )
        width = _text_width(mark.label, 10.0)
        flipped = mx + 4 + width > CHART_LEFT + plot_w
        left, right = (mx - 4 - width, mx - 4) if flipped else (mx + 4, mx + 4 + width)
        for row, taken in enumerate(rows_taken):
            if all(right + 6 < a or left - 6 > b for a, b in taken):
                taken.append((left, right))
                anchor = ' text-anchor="end"' if flipped else ""
                out.append(
                    f'<text x="{_n(mx - 4 if flipped else mx + 4)}" '
                    f'y="{_n(CHART_TOP + 11 + row * 12)}" font-size="10"{anchor} '
                    f'fill="{colors.secondary}">{_t(mark.label)}</text>'
                )
                break
        out.append("</g>")
    roles = {series.role: series for series in chart.series}
    plan, base, actual = roles.get("plan"), roles.get("baseline"), roles.get("actual")
    if plan is not None and base is not None and plan.points and base.points:
        ring = [f"{_n(x(w))},{_n(y(s))}" for w, s in plan.points]
        ring += [f"{_n(x(w))},{_n(y(s))}" for w, s in reversed(base.points)]
        out.append(
            f'<polygon class="band" points="{" ".join(ring)}" fill="{colors.plan}" '
            f'fill-opacity="0.1"/>'
        )
    if base is not None and base.points:
        out.append(
            _polyline(base, x, y, colors.plan, "0.55", ' stroke-dasharray="6 4"')
            + _marker(x(base.points[-1][0]), y(base.points[-1][1]), colors.surface, colors.plan)
        )
    if plan is not None and plan.points:
        out.append(_polyline(plan, x, y, colors.plan, "1", ""))
        for since, until in chart.idle:
            level = _share_at(plan.points, since)
            if level is not None:
                out.append(
                    f'<line class="idle" x1="{_n(x(since))}" x2="{_n(x(until))}" '
                    f'y1="{_n(y(level))}" y2="{_n(y(level))}" stroke="{colors.surface}" '
                    f'stroke-width="{_n(LINE_W + 1)}"/>'
                    f'<line class="idle" x1="{_n(x(since))}" x2="{_n(x(until))}" '
                    f'y1="{_n(y(level))}" y2="{_n(y(level))}" stroke="{colors.plan}" '
                    f'stroke-width="{_n(LINE_W)}" stroke-dasharray="0.1 4" stroke-linecap="round"/>'
                )
        out.append(
            _marker(x(plan.points[-1][0]), y(plan.points[-1][1]), colors.plan, colors.surface)
        )
    if actual is not None and actual.points:
        out.append(_polyline(actual, x, y, colors.ink, "1", ""))
        out.append(
            _marker(x(actual.points[-1][0]), y(actual.points[-1][1]), colors.ink, colors.surface)
        )
    out.append(_legend(chart.series, colors))
    out.append("</svg>")
    return "".join(out)


def _polyline(
    series: Series,
    x: Callable[[date], float],
    y: Callable[[float], float],
    color: str,
    opacity: str,
    extra: str,
) -> str:
    points = " ".join(f"{_n(x(when))},{_n(y(share))}" for when, share in series.points)
    data = ";".join(f"{when.isoformat()}:{share:.4f}" for when, share in series.points)
    return (
        f'<polyline class="series series-{series.role}" data-label="{_t(series.label)}" '
        f'data-points="{data}" points="{points}" fill="none" stroke="{color}" '
        f'stroke-opacity="{opacity}" stroke-width="{_n(LINE_W)}" stroke-linejoin="round" '
        f'stroke-linecap="round"{extra}/>'
    )


def _marker(cx: float, cy: float, fill: str, ring: str) -> str:
    return (
        f'<circle class="marker" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(MARKER)}" fill="{fill}" '
        f'stroke="{ring}" stroke-width="2"/>'
    )


def _legend(series: Sequence[Series], colors: Colors) -> str:
    out = []
    cursor = CHART_LEFT
    for entry in series:
        color = colors.ink if entry.role == "actual" else colors.plan
        dash = ' stroke-dasharray="6 4"' if entry.role == "baseline" else ""
        opacity = "0.55" if entry.role == "baseline" else "1"
        out.append(
            f'<g class="legend legend-{entry.role}"><line x1="{_n(cursor)}" x2="{_n(cursor + 18)}" '
            f'y1="12" y2="12" stroke="{color}" stroke-opacity="{opacity}" stroke-width="2"{dash}/>'
            f'<text x="{_n(cursor + 24)}" y="12" dominant-baseline="central" '
            f'fill="{colors.secondary}">{_t(entry.label)}</text></g>'
        )
        cursor += 24 + _text_width(entry.label, 11.0) + 18
    return "".join(out)


def _share_at(points: Sequence[tuple[date, float]], when: date) -> float | None:
    share = None
    for day, value in points:
        if day > when:
            break
        share = value
    return share


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
