"""``dplanner report``: the page, the site, the tables — and the rules under them.

Pinned here: every module's contribution is plain data (no ``Step`` ever crosses to the
renderer); the page carries every step, escapes what people typed, and re-renders to the
same bytes; the site's index depends on the set of projects and nothing else; the tables
export as what they show. No ``qapp`` fixture anywhere in this file.
"""

import io
import json
import re
import zipfile
from dataclasses import fields, is_dataclass
from datetime import date
from pathlib import Path

import pytest

from dplanner.cli.discovery import open_library
from dplanner.cli.report import website
from dplanner.cli.report.assemble import build
from dplanner.cli.report.parts import Chart, Contribution, Graph, Table
from dplanner.core.png import encode_rgb
from dplanner.domain.assets import attach
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.seed import seed_project
from dplanner.modules import _report_sources, _step_key, _step_kind, default_module_formats
from dplanner.modules.estimation.aspect import write as estimate
from dplanner.modules.notes.log import Note, write_log
from dplanner.modules.step_milestone.aspect import write as milestone
from dplanner.modules.step_status.aspect import read as status_for
from dplanner.modules.step_status.aspect import write as status

SCRIPTY = "<script>alert('x')</script> & friends"


@pytest.fixture
def plan(cli_library, workspace):
    """A project in the CLI tests' repository with enough on it for every source to speak."""
    project_dir = seed_project(workspace / "plan", "Discovery")
    with open_library(cli_library, default_module_formats(), io.StringIO()) as context:
        library = context.library
        project = context.store.attach(project_dir)
        library.add_child(library.id, project)
        steps = [Step(title=title) for title in ("Interview", SCRIPTY, "Ship it")]
        for step in steps:
            AddNodeCommand(project.id, step).redo(library)
        SetEdgesCommand(steps[1].id, "requires", [steps[0].id]).redo(library)
        SetEdgesCommand(steps[2].id, "requires", [steps[1].id]).redo(library)
        SetModuleDataCommand(steps[0].id, "estimation", estimate(2.0)).redo(library)
        SetModuleDataCommand(steps[1].id, "estimation", estimate(3.0)).redo(library)
        SetModuleDataCommand(
            steps[0].id, "step_status", status("done", today=date(2026, 9, 21))
        ).redo(library)
        SetModuleDataCommand(steps[2].id, "step_milestone", milestone("v1")).redo(library)
        area = context.store.files(steps[0].id, "step_description")
        picture = attach(area, encode_rgb(2, 2, 6, bytes(12)), "dot.png")
        library.set_text(steps[0].id, "step_description", f"Ask **everyone**.\n\n![dot]({picture})")
        log = write_log(
            [Note("N1", "decision", "Talk first", "Because.", "2026-09-01", steps[0].id)]
        )
        SetModuleDataCommand(project.id, "notes", log).redo(library)
        project_id = project.id
    return project_id


def _plain(value: object) -> bool:
    """True when nothing in ``value`` is a model object or a path — a renderer's whole diet."""
    if isinstance(value, Step | Project | Library | Path):
        return False
    if is_dataclass(value) and not isinstance(value, type):
        return all(_plain(getattr(value, field.name)) for field in fields(value))
    if isinstance(value, dict):
        return all(_plain(k) and _plain(v) for k, v in value.items())
    if isinstance(value, list | tuple | set | frozenset):
        return all(_plain(item) for item in value)
    return True


def test_every_source_speaks_plain_data(cli_library, plan):
    with open_library(cli_library, default_module_formats(), io.StringIO()) as context:
        project = context.library.project(plan)
        for source in _report_sources():
            contribution = source(context.library, project, context.store.files, date(2026, 9, 6))
            assert isinstance(contribution, Contribution)
            assert _plain(contribution), source
        report = build(
            context.library,
            project,
            context.store.files,
            _report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=status_for,
            today=date(2026, 9, 6),
        )
    assert _plain(report)
    assert [card.key for card in report.steps] == ["S1", "S2", "M3"]
    assert set(report.sections) >= {"overview", "plan", "order", "steps", "notes"}
    graph = next(p for p in report.sections["plan"] if isinstance(p, Graph))
    assert len(graph.nodes) == 3 and len(graph.edges) == 2
    steps = next(t for t in report.tables() if t.id == "steps")
    assert [c.label for c in steps.columns][:5] == ["Key", "Step", "Kind", "Status", "Estimate"]


def test_the_progress_chart_is_the_windows_plots_on_one_axis(cli_library, plan):
    """Each plot answers one question, and the renderer takes the axis from all of them at
    once: the same first and last day, the labels drawn once under the last plot. The
    volume plots share one scale, in days."""
    from dplanner.cli.report.drawings import LIGHT, chart_svg

    with open_library(cli_library, default_module_formats(), io.StringIO()) as context:
        report = build(
            context.library,
            context.library.project(plan),
            context.store.files,
            _report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=status_for,
            today=date(2026, 9, 6),
        )
    chart = next(p for p in report.sections["overview"] if isinstance(p, Chart))
    # No earlier plan is recorded, so there is nothing to compare scope against and that
    # plot is left out rather than drawn empty.
    assert [plot.kind for plot in chart.plots] == ["status", "shift", "volume", "remaining"]
    status = chart.plots[0]
    volume, remaining = chart.plots[2:]
    assert volume.ceiling == remaining.ceiling >= 1.0
    assert [series.role for series in remaining.series] == ["baseline", "plan"]
    assert [series.role for series in status.series] == ["plan", "actual"]
    assert status.standing in ("on plan", "") or status.standing.startswith(("ahead", "behind"))
    # One stretch per milestone plus the work after the last one; only the milestone gets
    # a row, and its sentence is the one the window's tooltip says.
    assert [stretch.label for stretch in chart.stretches] == ["v1"]
    (v1,) = chart.milestones
    assert v1.step_id and v1.note.startswith("v1 lands ")
    assert "by estimated days" in chart.note  # the measure the whole report reads
    svg = chart_svg(chart, LIGHT)
    assert svg.count('class="plot ') == 4
    assert svg.count('data-unit="days"') == 2  # the page's tooltip reads those in days
    assert 'data-kind="status"' in svg and 'data-kind="shift"' in svg
    # The window's decorations, drawn the same way here: the milestone's landing named on
    # the progress line, and on its own row a date beside the mark with a line dropping
    # from it to the axis.
    assert 'class="landing-name"' in svg and ">v1</text>" in svg
    assert svg.count('class="drop"') == 1
    assert svg.count('class="row-date"') == 1
    # One axis under every plot: the dates are labelled once, under the last plot's box —
    # a plot in the middle of the stack prints none of its own.
    last_plot = max(float(value) for value in re.findall(r'data-bottom="([\d.]+)"', svg))
    dates = [
        float(y)
        for y in re.findall(r'class="axis" x="[\d.]+" y="([\d.]+)" text-anchor="middle"', svg)
    ]
    assert dates and all(y > last_plot for y in dates)


def test_report_html_carries_every_step_and_escapes_what_people_typed(cli, plan, tmp_path):
    target = tmp_path / "plan.html"
    cli("report", "html", "Discovery", "--out", str(target))
    text = target.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    for key in ("S1", "S2", "M3"):
        assert f'data-key="{key}"' in text
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; friends" in text
    assert "<script>alert" not in text
    assert "data:image/png;base64," in text  # The description's picture travels inline.
    assert "<strong>everyone</strong>" in text
    assert 'id="about"' in text and "git clone" not in text  # No remote: no clone line.
    for section in ("overview", "plan", "timeline", "order", "steps", "notes"):
        assert f'<section id="{section}">' in text


def test_report_html_is_the_same_bytes_twice_and_prints_without_out(cli, plan, tmp_path):
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    cli("report", "html", "Discovery", "--out", str(first))
    cli("report", "html", "Discovery", "--out", str(second))
    assert first.read_bytes() == second.read_bytes()
    printed = cli("report", "html", "Discovery")
    assert printed.startswith("<!doctype html>")


def test_report_site_lays_the_repository_out_and_its_index_reads_the_set(cli, plan, workspace):
    out = cli("report", "site", "Discovery", "--json")
    written = json.loads(out)["sites"]
    site = workspace / website.REPORTS_DIR
    assert written == [{"root": str(workspace), "site": str(site), "projects": ["plan"]}]
    assert (site / "plan" / "index.html").is_file()
    summary = website.summary_record((site / "plan" / "summary.js").read_text())
    assert summary["title"] == "Discovery" and summary["slug"] == "plan"
    figures = summary["figures"]
    assert isinstance(figures, list) and any(f["label"] == "Done" for f in figures)
    index = (site / "index.html").read_text()
    assert '<script src="plan/summary.js"></script>' in index
    assert 'href="plan/index.html"' in index
    # The index is a function of the set: a second run leaves it byte-identical…
    before = (site / "index.html").read_bytes()
    cli("report", "site", "Discovery")
    assert (site / "index.html").read_bytes() == before
    # …and a project that appears is picked up from disk, whoever wrote it.
    (site / "other").mkdir()
    (site / "other" / website.SUMMARY_NAME).write_text("window.dplannerProjects = [];")
    cli("report", "site", "Discovery")
    assert '<script src="other/summary.js"></script>' in (site / "index.html").read_text()


def test_slugs_are_the_directory_relative_to_the_repository(tmp_path):
    root = tmp_path / "plans"
    assert website.slug_for(root / "search", root) == "search"
    assert website.slug_for(root / "team a" / "Søk", root) == "team-a-sok"
    assert website.slug_for(root, root) == "plans"


def test_report_tables_csv_and_xlsx_export_what_the_page_shows(cli, plan, tmp_path):
    listed = json.loads(cli("report", "tables", "Discovery", "--json"))["tables"]
    ids = [row["id"] for row in listed]
    assert "steps" in ids and "order" in ids and "milestones" in ids
    printed = cli("report", "csv", "Discovery", "--table", "order")
    lines = printed.splitlines()
    assert lines[0].startswith("#,Step,Wave,Estimate (days)")
    assert len(lines) == 4
    assert "no table 'nope'" in cli("report", "csv", "Discovery", "--table", "nope", expect=1)
    workbook = tmp_path / "plan.xlsx"
    cli("report", "xlsx", "Discovery", "--out", str(workbook))
    with zipfile.ZipFile(workbook) as archive:
        sheets = [name for name in archive.namelist() if name.startswith("xl/worksheets/")]
        assert len(sheets) == len(listed)
        names = archive.read("xl/workbook.xml").decode()
    assert 'name="Steps"' in names and 'name="Order"' in names


def test_the_steps_table_marks_milestones_and_carries_facet_columns(cli_library, plan):
    with open_library(cli_library, default_module_formats(), io.StringIO()) as context:
        project = context.library.project(plan)
        report = build(
            context.library,
            project,
            context.store.files,
            _report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=status_for,
            today=date(2026, 9, 6),
        )
    table = next(t for t in report.tables() if isinstance(t, Table) and t.id == "steps")
    by_key = {row.cells[0]: row for row in table.rows}
    assert by_key["M3"].strong and not by_key["S1"].strong
    assert by_key["S1"].cells[3] == "done" and by_key["S1"].cells[4] == "2d"
    card = report.step(by_key["S1"].step_id)
    assert card is not None
    assert [facet.label for facet in card.facets] == ["Estimate", "Description", "Decision"]


def test_the_tests_table_names_the_audience_and_offers_it_as_a_pick(cli, plan, tmp_path):
    cli("test", "add", "Interview", "Mechanism", "--audience", "technical", "--text", "1. Look")
    cli("test", "add", "Interview", "By hand", "--audience", "qa", "--audience", "technical")
    cli("test", "add", "Ship it", "Nobody said")
    target = tmp_path / "plan.html"
    cli("report", "html", "Discovery", "--out", str(target))
    text = target.read_text(encoding="utf-8")

    assert '<th class="kind-text">Audience</th>' in text
    # A cell naming two carries them apart from its words, because `_cell` prettifies what
    # it prints and a pick has to match what the data says.
    assert 'data-values="QA|Technical"' in text
    # The picks offer what the rows actually hold — including Other, which is what a test
    # nobody has classified reads as.
    for value in ("QA", "Technical", "Other"):
        assert f'<option value="{value}">' in text
    # And the per-step block says it too, for a reader who is looking at one step.
    assert "— QA, Technical —" in text


def test_a_column_pick_offers_only_the_values_its_rows_hold(cli, plan, tmp_path):
    """The steps table's status pick used to be four hard-coded options, blocked included."""
    target = tmp_path / "plan.html"
    cli("report", "html", "Discovery", "--out", str(target))
    text = target.read_text(encoding="utf-8")
    assert '<select data-column="3"><option value="">Any status</option>' in text
    assert '<option value="done">done</option>' in text
    assert 'value="blocked"' not in text  # Nothing here is blocked, so it is not offered.
    assert 'id="status-filter"' not in text  # The bespoke one is gone, not doubled up.


def test_the_audience_reaches_the_sheets_the_page_exports(cli, plan, tmp_path):
    cli("test", "add", "Interview", "By hand", "--audience", "qa")
    target = tmp_path / "tests.csv"
    cli("report", "csv", "Discovery", "--table", "tests", "--out", str(target))
    rows = target.read_text(encoding="utf-8").splitlines()
    assert "Audience" in rows[0]
    assert "QA" in rows[1]


def test_report_site_writes_to_the_reporting_location_this_machine_has(
    cli, plan, workspace, tmp_path
):
    """A project that names where it reports publishes there — the row's repository at the
    row's position — when this machine has that repository; `--out` names any directory."""
    from dplanner.core.storage.locations import init_repo

    reports = init_repo(tmp_path / "reports-repo")
    url = "https://github.com/acme/reports"
    cli(
        "location",
        "add",
        "Discovery",
        "--role",
        "reporting",
        "--repository",
        url,
        "--path",
        "team/search",
    )
    # Not checked out here: beside the plan, as always.
    written = json.loads(cli("report", "site", "Discovery", "--json"))["sites"]
    assert written[0]["site"] == str(workspace / website.REPORTS_DIR)
    cli("location", "checkout", "Discovery", "reporting", str(reports))
    written = json.loads(cli("report", "site", "Discovery", "--json"))["sites"]
    site = reports / "team" / "search"
    assert written == [{"root": str(reports), "site": str(site), "projects": ["plan"]}]
    assert (site / "plan" / "index.html").is_file() and (site / "index.html").is_file()
    elsewhere = tmp_path / "elsewhere"
    written = json.loads(cli("report", "site", "Discovery", "--out", str(elsewhere), "--json"))
    assert written["sites"][0]["site"] == str(elsewhere)
    assert (elsewhere / "plan" / "index.html").is_file()
