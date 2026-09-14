"""The Tests tab's three panes, its right-click, and writing the tests out.

The roster's *reader* is a tester, and everything here follows from that: which feature
is being tested is a standing list rather than a dropdown, the step a test hangs off is
not a column, the right-click offers verbs about tests rather than about steps, and the
whole thing can leave as files for somebody with no DPlanner at all.
"""

import zipfile

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Step
from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as milestone_write
from dplanner.modules.testing import runs
from dplanner.modules.testing.activity import TESTS_KIND
from dplanner.modules.testing.aspect import MODULE_ID, SPEC_SOURCE, Test, TestSource, write
from dplanner.modules.testing.collectors import ALL_TESTS, COLLECTOR_ROLE


@pytest.fixture
def shot(app):
    """A real 64 x 64 PNG. Built rather than pasted as hex, because half of what these
    assertions are about is that an actual picture comes out the other side."""
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QImage

    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, format="PNG")  # type: ignore[call-overload]
    return bytes(buffer.data().data())


@pytest.fixture
def project(services, make_project):
    return make_project("Widget")


def step(services, project, title, *, after=None, tests=(), marker=None):
    made = Step(title=title)
    AddNodeCommand(project.id, made).redo(services.document)
    if after is not None:
        SetEdgesCommand(made.id, "requires", [after.id]).redo(services.document)
    if tests:
        services.document.set_module_data(made.id, MODULE_ID, write(list(tests)))
    if marker is not None:
        module_id, entry = marker
        services.document.set_module_data(made.id, module_id, entry)
    return made


@pytest.fixture
def plan(services, project):
    """One milestone over two features, each with a work step carrying a test.

    Small, but it is the shape every question on this tab is about: which feature, which
    milestone, and what is behind each.
    """
    work_a = step(services, project, "Parse the query", tests=[Test("T100", "Parses bare words")])
    feature_a = step(
        services, project, "Search", after=work_a, marker=(FEATURE_ID, feature_write())
    )
    work_b = step(
        services, project, "Render results", after=feature_a, tests=[Test("T101", "Renders rows")]
    )
    feature_b = step(
        services, project, "Results list", after=work_b, marker=(FEATURE_ID, feature_write())
    )
    release = step(
        services,
        project,
        "Version 1",
        after=feature_b,
        marker=(MILESTONE_ID, milestone_write("Version")),
    )
    return {
        "work_a": work_a,
        "feature_a": feature_a,
        "work_b": work_b,
        "feature_b": feature_b,
        "release": release,
    }


def listed(tab):
    """The left list as (title, detail, trailing) — what a reader chooses from."""
    listing = tab.collectors.list
    return [
        (
            listing.item(index).text(),
            str(listing.item(index).data(DETAIL_ROLE) or ""),
            str(listing.item(index).data(TRAILING_ROLE) or ""),
        )
        for index in range(listing.count())
    ]


def pick(tab, step_id):
    listing = tab.collectors.list
    for index in range(listing.count()):
        if str(listing.item(index).data(COLLECTOR_ROLE)) == step_id:
            listing.setCurrentRow(index)
            return
    raise AssertionError(f"{step_id} is not listed: {listed(tab)}")


def shown(tab):
    """The test ids the table is showing, headings skipped."""
    table = tab.page.table
    return [found for row in range(table.rowCount()) if (found := table.test_at(row))]


# -- the feature list ----------------------------------------------------------------------


def test_the_left_list_leads_with_all_tests_then_every_collector(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    assert listed(tab)[0] == (ALL_TESTS, "", "")
    assert [title for title, _detail, _count in listed(tab)[1:]] == [
        "Search",
        "Results list",
        "Version 1",
    ]


def test_a_row_says_what_it_is_and_which_milestone_gathers_it(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    by_title = {title: detail for title, detail, _count in listed(tab)}
    assert by_title["Search"] == "Feature · Version 1"
    assert by_title["Version 1"] == "Milestone"  # A milestone is gathered by nothing above it.


def test_a_row_carries_how_many_tests_it_stands_for(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    by_title = {title: count for title, _detail, count in listed(tab)}
    assert by_title["Search"] == "1"  # Its own work only: the feature stops at the last one.
    assert by_title["Version 1"] == "2"  # Everything since the previous milestone.


def test_picking_a_feature_narrows_the_table_to_what_it_gathers(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    assert shown(tab) == ["T100", "T101"]
    pick(tab, plan["feature_b"].id)
    assert shown(tab) == ["T101"]
    pick(tab, "")
    assert shown(tab) == ["T100", "T101"]


def test_the_milestone_filter_limits_the_list_and_not_the_table(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    second = step(
        services,
        project,
        "Version 2",
        after=plan["release"],
        marker=(MILESTONE_ID, milestone_write("Version")),
    )
    tab._refresh_soon.flush()
    tab.collectors.filter.set_active([second.id])
    # The features of Version 1 are gone from the *list*; the table still shows everything,
    # because nothing has been picked.
    assert [title for title, _d, _c in listed(tab)[1:]] == ["Version 2"]
    assert shown(tab) == ["T100", "T101"]


def test_a_pick_the_filter_hides_falls_back_to_all_tests(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    pick(tab, plan["feature_a"].id)
    assert shown(tab) == ["T100"]
    other = step(services, project, "Version 2", marker=(MILESTONE_ID, milestone_write("Version")))
    tab._refresh_soon.flush()
    tab.collectors.filter.set_active([other.id])
    # Landing on some other feature's tests would be a wrong answer; "all of them" is
    # merely a wider one.
    assert tab.scope == "" and shown(tab) == ["T100", "T101"]


def test_revealing_a_scope_clears_the_filter_that_would_hide_it(services, project, plan):
    tab = services.tabs.open(TESTS_KIND, project.id)
    other = step(services, project, "Version 2", marker=(MILESTONE_ID, milestone_write("Version")))
    tab._refresh_soon.flush()
    tab.collectors.filter.set_active([other.id])
    tab.show_scope(plan["feature_a"].id)
    assert tab.collectors.filter.active() == [] and shown(tab) == ["T100"]


# -- the columns ---------------------------------------------------------------------------


def test_the_project_tab_hides_the_step_column_and_the_roll_call_keeps_it(services, project, plan):
    from dplanner.modules.testing.activity import ALL_TESTS_KIND
    from dplanner.modules.testing.table import STEP_COLUMN

    tab = services.tabs.open(TESTS_KIND, project.id)
    # The panel a double-click opens says which step; a roster's reader is after what is
    # being proved. Across projects a row has no other placing, so the roll call keeps it.
    assert tab.page.table.isColumnHidden(STEP_COLUMN)
    roll = services.tabs.open(ALL_TESTS_KIND)
    assert not roll.page.table.isColumnHidden(STEP_COLUMN)


# -- the right-click -----------------------------------------------------------------------


def test_the_right_click_offers_the_test_verbs_and_nothing_about_steps(services, project, plan):
    from PySide6.QtCore import QItemSelectionModel

    from dplanner.framework.action_menu import build_menu

    tab = services.tabs.open(TESTS_KIND, project.id)
    # Through the selection model, never selectRow: a table that has never been laid out
    # answers -1 to "which column is at x=0" and the call silently does nothing.
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    tab.page.table.selectionModel().select(tab.page.table.model().index(0, 0), flags)
    menu = build_menu(services.actions, services.context, "Step", tab.page.table, submenu="Test")
    # A greyed entry carries its reason in its label, so the verb is the part before the
    # dash — *disabled, never hidden* is exactly what this menu is meant to keep doing.
    verbs = {
        action.text().replace("&", "").split(" — ")[0] for action in menu.actions() if action.text()
    }
    assert {"Open Origin Step", "Open Origin Feature", "Mark Ok", "Add Test"} <= verbs
    # The whole Step menu here offered Delete, Link and Run Agent over a row that is not a
    # step at all.
    assert not {"Delete", "Link", "Run Agent", "New"} & verbs
    menu.deleteLater()


def test_open_origin_feature_names_the_feature_the_step_flows_into(services, project, plan):
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

    context = Context(
        {
            SCOPE_SELECTION: (
                ContextNode(selection_uri("step", plan["work_a"].id)),
                ContextNode(selection_uri("test", "T100")),
            )
        }
    )
    state = services.actions.spec("test.open_feature").state(context)
    assert state.enabled


def test_open_origin_feature_is_greyed_with_its_reason_off_a_feature(services, project):
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

    lonely = step(services, project, "Lonely", tests=[Test("T100", "One")])
    context = Context(
        {
            SCOPE_SELECTION: (
                ContextNode(selection_uri("step", lonely.id)),
                ContextNode(selection_uri("test", "T100")),
            )
        }
    )
    state = services.actions.spec("test.open_feature").state(context)
    assert state.enabled is False and "no feature gathers" in state.label


# -- the export ----------------------------------------------------------------------------


def test_a_pack_groups_the_tests_by_feature_and_says_where_each_came_from(services, project, plan):
    from dplanner.modules.testing.export import gather
    from dplanner.modules.testing.pack import render_markdown

    services.document.set_module_data(
        plan["work_a"].id,
        MODULE_ID,
        write(
            [
                Test(
                    "T100",
                    "Parses bare words",
                    "1. Type a word.",
                    sources=(TestSource(SPEC_SOURCE, "ui-spec", "MUST parse bare words"),),
                )
            ]
        ),
    )
    pack = gather(
        services.document,
        services.document.project(project.id),
        wanted=[],
        scope="",
        scopes=_scopes(services),
        feature_kind=FEATURE_ID,
        facts_for=lambda source: _facts(source),
        files=services.repo.files,
    )
    body = _body(render_markdown(pack))
    assert "## Search" in body and "## Results list" in body
    assert "### T100 — Parses bare words" in body
    assert "MUST parse bare words" in body
    assert "1. Type a word." in body


def test_a_pack_says_which_tests_it_holds(services, project, plan):
    from dplanner.modules.testing.export import gather

    every = gather(
        services.document,
        services.document.project(project.id),
        wanted=[],
        scope="",
        scopes=_scopes(services),
        feature_kind=FEATURE_ID,
        facts_for=_facts,
        files=services.repo.files,
    )
    some = gather(
        services.document,
        services.document.project(project.id),
        wanted=["T100"],
        scope="",
        scopes=_scopes(services),
        feature_kind=FEATURE_ID,
        facts_for=_facts,
        files=services.repo.files,
    )
    assert every.note == "Every test in the plan — 2 tests."
    assert some.note == "1 test, picked from the 2 in the plan."


def test_a_screenshot_travels_with_the_pack_under_a_readable_name(services, project, plan, shot):
    from dplanner.domain.assets import attach
    from dplanner.modules.testing.export import gather
    from dplanner.modules.testing.pack import render_markdown

    work = plan["work_a"]
    name = attach(services.repo.files(work.id, MODULE_ID), shot, "login.png")
    services.document.set_module_data(
        work.id,
        MODULE_ID,
        write([Test("T100", "Parses", f"1. Look.\n\n![shot]({name}#click=8,8,20,12)")]),
    )
    pack = gather(
        services.document,
        services.document.project(project.id),
        wanted=["T100"],
        scope="",
        scopes=_scopes(services),
        feature_kind=FEATURE_ID,
        facts_for=_facts,
        files=services.repo.files,
    )
    files = render_markdown(pack)
    paths = [one.path for one in files]
    # Never the content-addressed name: a hash tells the person who opens the pack nothing.
    assert "assets/T100-1.png" in paths
    body = _body(files)
    assert "assets/T100-1.png" in body and name not in body
    # And the fragment does not survive onto the new link — the ring is already painted in.
    assert "#click=" not in body


def test_a_marked_screenshot_is_rung_in_the_copy_that_leaves(services, project, plan, shot):
    from PySide6.QtGui import QColor, QImage

    from dplanner.domain.assets import attach
    from dplanner.modules.testing.export import gather

    work = plan["work_a"]
    name = attach(services.repo.files(work.id, MODULE_ID), shot, "login.png")
    services.document.set_module_data(
        work.id,
        MODULE_ID,
        write([Test("T100", "Parses", f"![shot]({name}#click=8,8,20,12)")]),
    )
    pack = gather(
        services.document,
        services.document.project(project.id),
        wanted=["T100"],
        scope="",
        scopes=_scopes(services),
        feature_kind=FEATURE_ID,
        facts_for=_facts,
        files=services.repo.files,
    )
    picture = pack.tests[0].pictures[0]
    # Whoever receives the pack has no reader that would draw the ring from the link.
    before = QImage.fromData(shot)
    after = QImage.fromData(picture.data)
    assert QColor(after.pixel(8, 8)) != QColor(before.pixel(8, 8))


def test_a_pack_is_written_as_a_folder_or_as_one_zip(tmp_path, shot):
    from dplanner.modules.testing.export import write_pack
    from dplanner.modules.testing.pack import ExportFile

    files = [ExportFile("tests.md", b"# hi"), ExportFile("assets/T100-1.png", shot)]
    folder = write_pack(files, tmp_path / "pack", zipped=False)
    assert (folder / "tests.md").read_bytes() == b"# hi"
    assert (folder / "assets" / "T100-1.png").read_bytes() == shot

    archive = write_pack(files, tmp_path / "pack.zip", zipped=True)
    with zipfile.ZipFile(archive) as opened:
        assert sorted(opened.namelist()) == ["assets/T100-1.png", "tests.md"]
        assert opened.read("tests.md") == b"# hi"


def test_the_default_name_carries_the_day_and_the_minute():
    from datetime import datetime

    from dplanner.modules.testing.pack import default_name

    when = datetime(2026, 9, 14, 14, 32)
    # An export is a moment: the second pack made on a Tuesday must not replace the first.
    assert default_name("Widget", when) == "Widget tests 2026-09-14 1432"
    assert default_name("A/B: testing?", when).startswith("AB testing tests ")


def test_the_export_verb_sits_in_file_export_and_on_the_tests_strip(services, project, plan):
    from dplanner.modules.testing.activity import RUN_VERBS

    spec = services.actions.spec("tests.export")
    assert (spec.menu, spec.group, spec.submenu) == ("File", "export", "Export")
    assert "tests.export" in RUN_VERBS


def test_the_export_verb_says_how_many_it_is_about_to_write(services, project, plan):
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

    nodes = (
        ContextNode(selection_uri("step", plan["work_a"].id)),
        *(ContextNode(selection_uri("test", one)) for one in ("T100", "T101")),
    )
    state = services.actions.spec("tests.export").state(Context({SCOPE_SELECTION: nodes}))
    assert state.label == "Export 2 Tests…"


def test_the_export_verb_is_greyed_on_a_project_with_no_tests(services, make_project):
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

    empty = make_project("Empty")
    context = Context({SCOPE_SELECTION: (ContextNode(selection_uri("project", empty.id)),)})
    state = services.actions.spec("tests.export").state(context)
    assert state.enabled is False and "no tests" in state.label


# -- helpers -------------------------------------------------------------------------------


def _scopes(services):
    from dplanner.modules import _scope_kinds
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    return _scope_kinds(check_read, is_feature, milestone_read)


def _facts(source):
    from dplanner.modules.testing.aspect import SourceFacts

    return SourceFacts(label=source.ref, detail=source.quote)


def _body(files):
    return next(one.data.decode("utf-8") for one in files if one.path == "tests.md")


def test_the_run_still_covers_what_the_tab_is_narrowed_to(services, project, plan, monkeypatch):
    from dplanner.framework.dialog import LinePrompt

    monkeypatch.setattr(LinePrompt, "ask", staticmethod(lambda *_a, **_k: "Smoke"))
    tab = services.tabs.open(TESTS_KIND, project.id)
    pick(tab, plan["feature_b"].id)
    services.actions.run("tests.new_run", services.context.current())
    opened = runs.open_run(runs.read(services.document.project(project.id)))
    # The left list replaced the scope dropdown, and what a run opened from the strip
    # covers still follows it.
    assert opened is not None and list(opened.tests) == ["T101"]
