"""Where a test came from: the record, the verbs, the column, and the pane under the table.

A test cites a spec passage or an implementation note, and every surface reads the one
record. What is asserted here is the *contract* between them — that the pointer is all
that is stored, that a name is asked of whoever owns it, and that a pointer nobody can
follow still shows rather than quietly reading as no source at all.
"""

import json

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.testing.aspect import (
    MODULE_ID,
    NOTE_SOURCE,
    SPEC_SOURCE,
    SourceFacts,
    Test,
    TestSource,
    read,
    write,
)


def data(text):
    return json.loads(text)


# -- the record ----------------------------------------------------------------------------


def test_a_source_survives_a_write_and_a_read():
    source = TestSource(kind=SPEC_SOURCE, ref="ui-spec", quote="MUST not flicker", page=4)
    step = Step(title="Work")
    step.module_data[MODULE_ID] = write([Test("T100", "One", sources=(source,))])
    assert read(step)[0].sources == (source,)


def test_a_test_with_no_sources_writes_no_key():
    # Absence encodes the default, as every other aspect here does: a test that says
    # nothing about where it came from carries no `sources` at all.
    entry = write([Test("T100", "One")])
    assert "sources" not in entry["tests"][0]


def test_an_unreadable_source_row_reads_as_absent_rather_than_raising():
    step = Step(title="Work")
    step.module_data[MODULE_ID] = {
        "tests": [
            {
                "id": "T100",
                "title": "One",
                "sources": [
                    {"kind": "spec", "ref": "ui-spec"},
                    {"kind": "telepathy", "ref": "somewhere"},  # Not a kind we know.
                    {"kind": "note"},  # No ref at all.
                    "not even a row",
                ],
            }
        ]
    }
    assert read(step)[0].sources == (TestSource(kind=SPEC_SOURCE, ref="ui-spec"),)


def test_the_entry_carries_the_format_it_was_written_at():
    from dplanner.modules.testing.aspect import DATA_FORMAT

    assert write([Test("T100", "One")])["format"] == DATA_FORMAT.version == 2


def test_changing_a_test_never_drops_what_it_cites():
    """Every verb that edits a test goes through ``dataclasses.replace``.

    Rebuilding the record field by field is what silently lost the sources the first time,
    and it is invisible until somebody looks at the file.
    """
    import dataclasses

    test = Test("T100", "One", "body", sources=(TestSource(SPEC_SOURCE, "ui-spec"),))
    for changed in (
        dataclasses.replace(test, title="Renamed"),
        dataclasses.replace(test, body="rewritten"),
        dataclasses.replace(test, archived=True),
    ):
        assert changed.sources == test.sources


# -- the CLI -------------------------------------------------------------------------------


@pytest.fixture
def cli(cli, tmp_path):
    cli("project", "create", "Widget", "--summary", "The list view")
    cli("step", "add", "widget", "Fix list flicker")
    spec = tmp_path / "ui-spec.md"
    spec.write_text("The list MUST render without visible reflow.\n")
    cli("spec", "import", "widget", str(spec))
    cli("note", "add", "widget", "decision", "Rows arrive late", "--text", "Found in review.")
    return cli


def test_a_test_is_authored_with_its_source_in_one_call(cli):
    found = data(
        cli(
            "test",
            "add",
            "Fix list flicker",
            "No flicker",
            "--text",
            "1. Look",
            "--document",
            "ui-spec",
            "--quote",
            "The list MUST render without visible reflow.",
            "--json",
        )
    )
    assert found["sources"] == [
        {
            "kind": "spec",
            "ref": "ui-spec",
            "quote": "The list MUST render without visible reflow.",
            "page": None,
        }
    ]


def test_adding_a_test_with_no_source_says_so_and_still_adds_it(cli):
    # Never refused: a plan written before sources existed is full of them, and a verb
    # that refused would strand the plan rather than improve it.
    said = cli("test", "add", "Fix list flicker", "No flicker")
    assert "no source" in said
    assert data(cli("test", "show", "T100", "--json"))["sources"] == []


def test_citing_a_note_names_it_by_id(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    found = data(cli("test", "cite", "T100", "--note", "N1", "--json"))
    assert found["sources"] == [{"kind": NOTE_SOURCE, "ref": "N1", "quote": "", "page": None}]


def test_a_document_is_found_by_part_of_its_name(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "cite", "T100", "--document", "ui-sp")
    assert data(cli("test", "show", "T100", "--json"))["sources"][0]["ref"] == "ui-spec"


def test_a_source_pointing_at_nothing_is_refused_rather_than_stored(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    with pytest.raises(AssertionError, match="no spec document matching"):
        cli("test", "cite", "T100", "--document", "nowhere-spec")
    with pytest.raises(AssertionError, match="no note"):
        cli("test", "cite", "T100", "--note", "N99")
    assert data(cli("test", "show", "T100", "--json"))["sources"] == []


def test_citing_the_same_passage_twice_is_one_source(cli):
    # An agent re-runs a command after a stale-workspace refusal; the second run must not
    # leave the test citing one thing twice.
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "cite", "T100", "--document", "ui-spec", "--quote", "MUST render")
    found = data(
        cli("test", "cite", "T100", "--document", "ui-spec", "--quote", "MUST render", "--json")
    )
    assert len(found["sources"]) == 1


def test_a_test_may_prove_more_than_one_thing(cli):
    cli("test", "add", "Fix list flicker", "No flicker")
    cli("test", "cite", "T100", "--document", "ui-spec", "--quote", "MUST render")
    found = data(cli("test", "cite", "T100", "--note", "N1", "--json"))
    assert [one["kind"] for one in found["sources"]] == [SPEC_SOURCE, NOTE_SOURCE]


def test_unciting_takes_one_source_or_all_of_them(cli):
    cli("test", "add", "Fix list flicker", "No flicker", "--note", "N1")
    cli("test", "cite", "T100", "--document", "ui-spec")
    assert data(cli("test", "uncite", "T100", "--note", "N1", "--json"))["removed"] == 1
    assert data(cli("test", "uncite", "T100", "--all", "--json"))["removed"] == 1
    assert "nothing to remove" in cli("test", "uncite", "T100", "--all")


def test_lint_names_every_test_that_says_nowhere_it_came_from(cli):
    cli("test", "add", "Fix list flicker", "Sourced", "--note", "N1", "--text", "1. Look")
    cli("test", "add", "Fix list flicker", "Bare", "--text", "1. Look")
    found = data(cli("project", "lint", "widget", "--json", expect=1))
    by_check = {row["check"]: row["message"] for row in found["findings"]}
    assert "test.unsourced" in by_check
    assert "T101" in by_check["test.unsourced"] and "T100" not in by_check["test.unsourced"]


def test_test_show_prints_where_it_came_from(cli):
    cli("test", "add", "Fix list flicker", "No flicker", "--note", "N1")
    assert "from note: N1" in cli("test", "show", "T100")
    cli("test", "uncite", "T100", "--all")
    assert "no source" in cli("test", "show", "T100")


# -- the window ----------------------------------------------------------------------------


@pytest.fixture
def project(services, make_project):
    return make_project("Widget")


@pytest.fixture
def step(services, project):
    step = Step(title="Fix list flicker")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def select_test(table, test_id):
    """Pick a row through the selection model, never ``selectRow``.

    ``QTableView::selectRow`` asks its header which column sits at x=0, and a table that
    has never been laid out answers -1 — so the call is a silent no-op, and whether a
    table has been laid out depends on what else the worker did first. The table's own
    ``_reselect`` takes this path for the same reason.
    """
    from PySide6.QtCore import QItemSelectionModel

    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in range(table.rowCount()):
        if table.test_at(row) == test_id:
            table.selectionModel().select(table.model().index(row, 0), flags)
            return
    raise AssertionError(f"{test_id} is not in the table")


def sourced_tab(services, project, step, sources):
    from dplanner.modules.testing.activity import TESTS_KIND

    step.module_data[MODULE_ID] = write([Test("T100", "One", "1. Look", sources=sources)])
    services.document.module_data_changed.emit(step.id, MODULE_ID, None)
    return services.tabs.open(TESTS_KIND, project.id)


def test_the_sources_column_names_what_the_owner_calls_it(services, project, step):
    from dplanner.modules.testing.table import SOURCES_COLUMN

    tab = sourced_tab(services, project, step, (TestSource(SPEC_SOURCE, "ui-spec", "MUST"),))
    assert tab.page.table.item(0, SOURCES_COLUMN).text() == "ui-spec"


def test_a_test_with_no_source_wears_a_dash_and_says_why(services, project, step):
    from dplanner.modules.testing.table import SOURCES_COLUMN, UNSOURCED, UNSOURCED_TIP

    tab = sourced_tab(services, project, step, ())
    cell = tab.page.table.item(0, SOURCES_COLUMN)
    assert cell.text() == UNSOURCED and cell.toolTip() == UNSOURCED_TIP


def test_picking_a_test_reveals_every_source_under_the_table(services, project, step):
    sources = (TestSource(SPEC_SOURCE, "ui-spec", "MUST render"), TestSource(NOTE_SOURCE, "N1"))
    tab = sourced_tab(services, project, step, sources)
    select_test(tab.page.table, "T100")
    # Both of them: the column says how many, this pane is where all of them are read.
    assert tab.page.sources.table.rowCount() == 2
    assert tab.page.sources.sources() == sources


def test_the_pane_prints_what_the_owner_answered_about_each_source(app):
    from dplanner.modules.testing.sources import SourcesPane

    facts = {
        "ui-spec": SourceFacts(label="ui-spec", detail="The list MUST render."),
        "N1": SourceFacts(label="N1 Rows arrive late", detail="Found in review."),
    }
    pane = SourcesPane(lambda _source: None)
    try:
        pane.show_sources(
            Test(
                "T100",
                "One",
                sources=(TestSource(SPEC_SOURCE, "ui-spec"), TestSource(NOTE_SOURCE, "N1")),
            ),
            lambda source: facts[source.ref],
        )

        def cell(row, column):
            found = pane.table.item(row, column)
            assert found is not None
            return found.text()

        rows = [(cell(row, 0), cell(row, 1)) for row in range(pane.table.rowCount())]
        assert rows == [
            ("ui-spec", "The list MUST render."),
            ("N1 Rows arrive late", "Found in review."),
        ]
    finally:
        pane.deleteLater()


def test_the_pane_says_so_when_nothing_is_picked_and_when_there_is_no_source(
    services, project, step
):
    from dplanner.modules.testing.sources import NOTHING_PICKED, UNSOURCED

    tab = sourced_tab(services, project, step, ())
    assert tab.page.sources.empty.text() == NOTHING_PICKED
    select_test(tab.page.table, "T100")
    assert tab.page.sources.empty.text() == UNSOURCED


def test_a_source_tooltip_wraps_and_carries_the_whole_passage(services, project, step):
    passage = "The list MUST render without visible reflow, " * 6
    tab = sourced_tab(services, project, step, (TestSource(SPEC_SOURCE, "ui-spec", passage),))
    select_test(tab.page.table, "T100")
    tip = tab.page.sources.table.item(0, 1).toolTip()
    assert tip.startswith("<div")  # Qt wraps a tooltip only when it is rich text.
    assert "visible reflow" in tip


def test_a_source_that_is_no_longer_there_still_shows_and_says_so(services, project, step):
    from dplanner.modules.testing.sources import GONE

    tab = sourced_tab(services, project, step, (TestSource(SPEC_SOURCE, "renamed-away"),))
    select_test(tab.page.table, "T100")
    # Hiding it would leave the test looking sourced; the reader has to be able to mend it.
    assert GONE.strip(" —") in tab.page.sources.table.item(0, 0).text()


def test_double_clicking_a_source_opens_where_it_lives(services, project, step):
    opened: list[TestSource] = []
    tab = sourced_tab(services, project, step, (TestSource(NOTE_SOURCE, "N1"),))
    select_test(tab.page.table, "T100")
    tab.page.sources._open = opened.append
    tab.page.sources.table.cellActivated.emit(0, 0)
    assert opened == [TestSource(NOTE_SOURCE, "N1")]


def test_bare_facts_print_the_pointer_when_no_owner_can_be_asked():
    from dplanner.modules.testing.module import _bare_facts

    found = _bare_facts("p1", TestSource(SPEC_SOURCE, "ui-spec", page=4))
    assert found == SourceFacts(label="ui-spec p. 4")
