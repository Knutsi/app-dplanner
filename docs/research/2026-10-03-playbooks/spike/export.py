"""Rebuild `../report.html` from `../report.src.html` and the spike's own output.

Every prototype section of the report is generated here, so what the report shows is what the
code does today: the playbooks and their checks, the stage diagrams, every simulated scenario,
the probe fixtures with the classifier's verdict on each, and the edge-case and question tables
parsed from `failures.md` and `questions.md`.

    uv run python export.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import classify
import playbook as pbk
import simulate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ORDER = ["review-loop.toml", "solo.toml", "careful-change.toml", "careful-change-lead.toml", "broken.toml"]


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def inline(md: str) -> str:
    """The little Markdown a table cell uses: code, bold, italics, links, [scenario] refs."""
    out = esc(md)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+\.md)\)", r"<em>\1</em>", out)
    out = re.sub(
        r"\[`([^`]+)`(?:, `([^`]+)`)?\]",
        lambda m: " ".join(f'<span class="scn">{g}</span>' for g in m.groups() if g),
        out,
    )
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", out)
    return out


def md_tables(path: Path) -> list[tuple[str, list[str], list[list[str]]]]:
    """Every pipe table in a Markdown file, with the nearest heading above it."""
    tables: list[tuple[str, list[str], list[list[str]]]] = []
    heading = ""
    rows: list[list[str]] = []
    for line in [*path.read_text().splitlines(), ""]:
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                rows.append(cells)
        elif rows:
            tables.append((heading, rows[0], rows[1:]))
            rows = []
    return tables


# ── playbooks ─────────────────────────────────────────────────────────────────────────


def star_svg(pb: pbk.Playbook) -> str:
    stages = list(pb.stages)
    w, h, gap, top = 118, 44, 34, 18
    xs = [16 + i * (w + gap) for i in range(len(stages))]
    done_x = xs[-1] + w + gap
    width = done_x + 60
    height = top + h + 28 + 26 * len(pb.gates) + 22
    mid = "ah-" + pb.source.removesuffix(".toml")
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
        f'aria-label="Stage diagram of {esc(pb.name)}" class="star">'
    ]
    parts.append(
        f'<defs><marker id="{mid}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" class="arrowhead"/></marker></defs>'
    )
    cy = top + h / 2
    for i, stage in enumerate(stages):
        x = xs[i]
        nxt = xs[i + 1] if i + 1 < len(stages) else done_x
        parts.append(f'<line x1="{x + w}" y1="{cy}" x2="{nxt - 3}" y2="{cy}" class="fwd" marker-end="url(#{mid})"/>')
        cls = "node work" if stage.kind == "work" else f"node gate {stage.kind}"
        parts.append(f'<rect x="{x}" y="{top}" width="{w}" height="{h}" rx="7" class="{cls}"/>')
        parts.append(
            f'<text x="{x + w / 2}" y="{top + 19}" class="nlabel {"inv" if stage.kind == "work" else ""}">'
            f"{esc(stage.id)}</text>"
        )
        role = pb.roles.get(stage.by)
        who = (
            "DPlanner"
            if stage.kind == "criteria"
            else ("a person" if role and role.person else (role.agent if role and role.agent else stage.by))
        )
        parts.append(
            f'<text x="{x + w / 2}" y="{top + 34}" class="nsub {"inv" if stage.kind == "work" else ""}">'
            f"{esc(stage.kind)} · {esc(who)}</text>"
        )
    parts.append(
        f'<circle cx="{done_x + 22}" cy="{cy}" r="20" class="node done"/>'
        f'<text x="{done_x + 22}" y="{cy + 4}" class="nlabel">done</text>'
    )
    for n, stage in enumerate(pb.gates):
        i = stages.index(stage)
        target = stages.index(pb.stage(stage.on_changes))
        y = top + h + 22 + 26 * n
        x1, x2 = xs[i] + w / 2, xs[target] + w / 2 + 10 + 6 * n
        label = (
            "fail"
            if stage.kind == "criteria"
            else ("send back" if stage.kind == "person" else f"changes ×{stage.rounds}")
        )
        if stage.when:
            label += " · only on " + ", ".join(stage.when)
        parts.append(
            f'<path d="M{x1},{top + h} L{x1},{y} L{x2},{y} L{x2},{top + h + 3}" class="back" marker-end="url(#{mid})"/>'
        )
        parts.append(f'<text x="{x1 + 6}" y="{y - 5}" class="blabel">{esc(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def playbooks_html() -> str:
    tabs, panels = [], []
    for i, name in enumerate(ORDER):
        path = HERE / "playbooks" / name
        pb = pbk.load(path)
        problems = pbk.check(pb)
        pid = "pb-" + name.removesuffix(".toml")
        tabs.append(
            f'<button role="tab" id="tab-{pid}" aria-controls="{pid}" aria-selected="{str(i == 0).lower()}" '
            f'class="tab">{esc(pb.name)}</button>'
        )
        checks = "".join(f'<li class="err">{esc(e)}</li>' for e in problems.errors)
        checks += "".join(f'<li class="warn">{esc(w)}</li>' for w in problems.warnings)
        if not checks:
            checks = '<li class="ok">check() accepts it with no warnings</li>'
        body = [
            f'<div class="pbgrid"><div><div class="cap">playbooks/{esc(name)}</div>'
            f'<pre class="code">{esc(path.read_text())}</pre></div>'
            f'<div><div class="cap">check()</div><ul class="checks">{checks}</ul>'
        ]
        if not problems.errors:
            body.append(
                f'<div class="cap">the stage graph, drawn from the list</div><div class="scroll">{star_svg(pb)}</div>'
            )
        body.append("</div></div>")
        if pb.driver == "lead" and not problems.errors:
            body.append(
                '<details class="brief"><summary>The same playbook as a lead agent\'s briefing '
                "(<code>lead_briefing()</code>)</summary>"
                f'<pre class="code">{esc(pbk.lead_briefing(pb))}</pre></details>'
            )
        cmd = f"uv run python playbook.py playbooks/{name}"
        panels.append(
            f'<div role="tabpanel" id="{pid}" aria-labelledby="tab-{pid}" {"hidden" if i else ""}>'
            f'{"".join(body)}<p class="repro">Reproduce: <code>{esc(cmd)}</code></p></div>'
        )
    return f'<div class="tabs" role="tablist" aria-label="Playbooks">{"".join(tabs)}</div>{"".join(panels)}'


# ── scenarios ─────────────────────────────────────────────────────────────────────────


def outcome_class(outcome: str) -> str:
    if outcome == "done":
        return "good"
    if outcome.startswith("escalated"):
        return "person"
    return "person" if "person" in outcome else "warn"


def scenarios_html() -> str:
    results = [simulate.simulate(n, sc) for n, sc in simulate.SCENARIOS.items()]
    groups: dict[str, list[dict[str, object]]] = {}
    for r in results:
        groups.setdefault(str(r["name"]).split("/")[0], []).append(r)
    titles = {
        "review-loop": "The 99% case",
        "careful": "Careful change",
        "solo": "Solo",
        "fail": "Failures",
        "lead": "Lead agent",
    }
    picker = []
    for group, items in groups.items():
        buttons = "".join(
            f'<button class="scbtn" data-target="sc-{esc(str(r["name"]).replace("/", "-"))}" '
            f'aria-pressed="{str(r is results[0]).lower()}">'
            f'<span class="dot {outcome_class(str(r["outcome"]))}"></span>{esc(str(r["name"]).split("/")[1])}</button>'
            for r in items
        )
        picker.append(f'<div class="scgroup"><div class="cap">{esc(titles.get(group, group))}</div>{buttons}</div>')
    panels = []
    for r in results:
        sid = "sc-" + str(r["name"]).replace("/", "-")
        ring = "".join(_ring_row(line) for line in r["ring"])  # type: ignore[attr-defined]
        talk = esc("\n".join(r["talk"])) or "—"  # type: ignore[arg-type]
        runs = esc("\n".join(r["runs"])) or "—"  # type: ignore[arg-type]
        inbox = (
            "".join(
                f'<li><span class="kind">{esc(i.split("]")[0].strip("["))}</span>{esc(i.split("] ", 1)[1])}</li>'
                for i in r["inbox"]
            )
            or "<li class='none'>nothing</li>"
        )  # type: ignore[attr-defined]
        refused = "".join(f"<li>{esc(x)}</li>" for x in r["refused"]) or "<li class='none'>nothing</li>"  # type: ignore[attr-defined]
        cost = "".join(f"<tr><td>{esc(k)}</td><td class='num'>${v:.2f}</td></tr>" for k, v in r["cost"].items())  # type: ignore[attr-defined]
        inv = "".join(
            f'<li class="{"ok" if x.startswith("ok") else "err"}">{esc(x[3:].strip())}</li>' for x in r["invariants"]
        )  # type: ignore[attr-defined]
        panels.append(f'''<article class="scenario" id="{sid}" {"hidden" if r is not results[0] else ""}>
<header class="schead"><div><h4>{esc(r["name"])}</h4><p>{esc(r["about"])}</p>
<p class="meta"><code>{esc(r["playbook"])}</code> · driver {esc(r["driver"])} · script <code>{esc(r["script"])}</code></p></div>
<div class="verdict {outcome_class(str(r["outcome"]))}"><b>{esc(r["outcome"])}</b><span>after {esc(r["elapsed"])} · ${r["total_usd"]} of ${r["budget_usd"]}</span></div></header>
<div class="layers">
<section class="layer"><div class="cap">1 · the ring, as the canvas mark reads it</div><ol class="ring">{ring}</ol></section>
<section class="layer"><div class="cap">2 · the round conversation</div><pre class="talk">{talk}</pre></section>
<section class="layer"><div class="cap">3 · transcripts — one line per run's stream log</div><pre class="talk dim">{runs}</pre></section>
</div>
<div class="side3">
<section><div class="cap">needs you</div><ul class="inbox">{inbox}</ul></section>
<section><div class="cap">refused or ignored by the engine</div><ul class="refused">{refused}</ul></section>
<section><div class="cap">cost by stage (assumed prices)</div><table class="mini">{cost}</table>
<div class="cap" style="margin-top:.8rem">invariants</div><ul class="checks">{inv}</ul></section>
</div>
<p class="repro">Reproduce: <code>uv run python simulate.py {esc(r["name"])}</code></p>
</article>''')
    return f'<div class="scenarios"><nav class="scpick" aria-label="Scenarios">{"".join(picker)}</nav><div>{"".join(panels)}</div></div>'


def _ring_row(line: str) -> str:
    t, rest = line[:6].strip(), line[8:]
    label, what = rest[:16].strip(), rest[17:]
    tone = (
        "person"
        if label in ("Needs you", "Waits for you", "Escalated")
        else "park"
        if label == "Parked"
        else "retry"
        if label in ("Retrying", "Recovering")
        else "good"
        if label == "Done"
        else ""
    )
    return (
        f'<li><span class="t">{esc(t)}</span><span class="pill {tone}">{esc(label)}</span>'
        f'<span class="what">{esc(what)}</span></li>'
    )


# ── probes ────────────────────────────────────────────────────────────────────────────

MODE_LABEL = {
    "noauth": "not logged in",
    "401": "401 bad key",
    "403": "403 subscription lapsed",
    "credit": "credit too low",
    "429": "429 rate limit",
    "529": "529/503 overloaded",
    "500": "500 server error",
    "404model": "404 model retired",
    "garbage": "malformed 200",
    "hang": "API hangs",
    "sigterm": "SIGTERM after 8 s",
    "sigkill": "SIGKILL after 8 s",
}


def probes_html() -> str:
    cells: dict[tuple[str, str], str] = {}
    for path in sorted((HERE / "probes" / "out").glob("*.json")):
        record, ending = classify.classify_fixture(path)
        secs = float(record["seconds"])  # type: ignore[arg-type]
        timed = record["timed_out_after_s"] is not None
        slow = " slow" if secs > 60 else ""
        took = f"no exit in {secs:.0f} s" if timed else f"exit {record['exit']} · {secs:.1f} s"
        reqs = f" · {record['requests_seen']} req" if record["requests_seen"] else ""
        cells[(str(record["mode"]), str(record["cli"]))] = (
            f'<td class="probe {ending.cls}{slow}"><span class="pill {ending.cls}">{esc(ending.cls)} · '
            f'{esc(ending.kind)}</span><span class="took">{esc(took)}{esc(reqs)}</span>'
            f'<span class="why">{esc(ending.reason[:110])}</span></td>'
        )
    rows = []
    for mode, label in MODE_LABEL.items():
        tds = "".join(cells.get((mode, cli), "<td>—</td>") for cli in ("claude", "codex", "opencode"))
        rows.append(f"<tr><th scope='row'>{esc(label)}</th>{tds}</tr>")
    head = "<tr><th>fake API serves</th><th>claude -p 2.1.280</th><th>codex exec 0.156.1</th><th>opencode run 1.18.34</th></tr>"
    return (
        f'<div class="scroll"><table class="probes"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


# ── tables parsed from the notes ──────────────────────────────────────────────────────


def failures_html() -> str:
    out = []
    for heading, head, rows in md_tables(ROOT / "failures.md"):
        if head[:2] != ["Case", "Detected by"]:
            continue
        trs = []
        for row in rows:
            case, detected, cls, what = (row + [""] * 4)[:4]
            key = cls.split()[0] if cls.strip() not in ("—", "") else "none"
            key = key if key in ("retry", "park", "person", "abandon", "changes", "refused") else "none"
            pill = f'<span class="pill {key}">{esc(cls)}</span>' if key != "none" else '<span class="nopill">—</span>'
            trs.append(
                f'<tr data-class="{key}"><td>{inline(case)}</td><td>{inline(detected)}</td>'
                f"<td>{pill}</td><td>{inline(what)}</td></tr>"
            )
        out.append(
            f'<h4 class="fgroup">{esc(heading)}</h4><div class="scroll"><table class="cases">'
            "<thead><tr><th>Case</th><th>Detected by</th><th>Class</th><th>What happens</th></tr></thead>"
            f"<tbody>{''.join(trs)}</tbody></table></div>"
        )
    return "".join(out)


def questions_html() -> str:
    for _, head, rows in md_tables(ROOT / "questions.md"):
        if head and head[0] == "#":
            items = "".join(
                f'<li><div class="q">{inline(q)}</div><div class="rec"><span class="cap">recommend</span>{inline(rec)}</div>'
                f'<div class="why">{inline(why)}</div></li>'
                for _, q, rec, why in rows
            )
            return f'<ol class="questions">{items}</ol>'
    return ""


def main() -> None:
    src = (ROOT / "report.src.html").read_text()
    parts = {
        "playbooks": playbooks_html(),
        "scenarios": scenarios_html(),
        "probes": probes_html(),
        "failures": failures_html(),
        "questions": questions_html(),
    }
    for key, value in parts.items():
        marker = f"<!--@{key}-->"
        assert marker in src, marker
        src = src.replace(marker, value)
    (ROOT / "report.html").write_text(src)
    print(f"wrote {ROOT / 'report.html'} ({len(src) // 1024} KiB)")


if __name__ == "__main__":
    main()
