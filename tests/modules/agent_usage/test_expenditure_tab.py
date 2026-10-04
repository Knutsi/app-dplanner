"""The Expenditure tab: the order, with what each step's agents consumed from the project's
usage ledger, what its estimate predicted, and the running offset between them."""

from pathlib import Path

import pytest

from dplanner.domain import ledger
from dplanner.domain.agents import AgentUsage, Tokens
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, activity_uri, selection_uri
from dplanner.framework.list_rows import TINT_ROLE
from dplanner.framework.signalling import tone_colour
from dplanner.modules.agent_usage import expenditure_activity as tab_words

COLUMN = {
    title: index
    for index, title in enumerate(["#", "Step", *(column.title for column in tab_words.columns())])
}


@pytest.fixture
def project(services, make_project):
    """A → B → C, each estimated a day; A and B done."""
    library = services.document
    project = make_project("Discovery")
    for title in ("A", "B", "C"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [b.id]).redo(library)
    for step in (a, b, c):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": 1.0}))
    for step in (a, b):
        services.undo.push(
            SetModuleDataCommand(step.id, "step_status", {"status": "done", "format": 1})
        )
    services.autosave.flush_now()
    return project


def _plan(services, project) -> Path:
    return Path(services.repo.project_dir(project.id))


def _record(services, project, step, run: str, **models: Tokens) -> None:
    ledger.write(
        _plan(services, project),
        ledger.LedgerRecord(
            run=run,
            project=project.id,
            step=step.id,
            harness="claude",
            launched="2026-10-01T10:00:00+00:00",
            agents=(AgentUsage("main", dict(models)),),
        ),
    )


def cell(tab, row: int, title: str) -> str:
    return str(tab.table.item(row, COLUMN[title]).text())


def test_each_step_says_what_its_runs_consumed_down_the_order(services, project):
    a, b, _c = project.steps
    _record(services, project, a, "r1", opus=Tokens(1000, 40_000, 500))
    _record(services, project, b, "r2", opus=Tokens(2000, 0, 1000))
    _record(services, project, b, "r3", haiku=Tokens(300, 0, 200))
    tab = services.tabs.open("expenditure", project.id)
    assert services.tabs.tab_title(tab) == "Discovery — Expenditure"
    assert [cell(tab, row, "Step") for row in range(3)] == ["A", "B", "C"]
    assert [cell(tab, row, "Runs") for row in range(3)] == ["1", "2", ""]
    assert (cell(tab, 0, "In"), cell(tab, 0, "Cached"), cell(tab, 0, "Out")) == (
        "1.0k",
        "40.0k",
        "500",
    )
    assert cell(tab, 1, "Models") == "haiku, opus"
    assert [cell(tab, row, "Running") for row in range(3)] == ["1.5k", "5.0k", "5.0k"]
    # One project, so what is expected is learned from it alone: (1.5k + 3.5k) per 2 days.
    assert [cell(tab, row, "Expected") for row in range(3)] == ["2.5k", "2.5k", "2.5k"]
    assert cell(tab, 0, "Offset") == "-40%" and cell(tab, 1, "Offset") == "+0%"
    assert cell(tab, 2, "Offset") == ""  # Not finished: nothing to compare yet.
    assert (
        tab.volume.text()
        == "2 of 3 finished · 3.3k in · 40.0k cached · 1.7k out · 0% under expected"
    )
    assert "learned from 2 finished steps in this project" in tab.volume.toolTip()


def test_the_offset_is_said_in_the_tone_a_status_takes():
    from dplanner.domain.expenditure import Row, Spent
    from dplanner.domain.ordering import Placed

    def offset_ink(offset: float):
        row = Row(Placed(1, 1, Step(title="X")), Spent(), 0, None, 1.0, offset)
        return tab_words.row_cells(row, False)[-1].ink

    assert offset_ink(-0.1) == tone_colour("ok") and offset_ink(0.004) == tone_colour("ok")
    assert offset_ink(0.2) == tone_colour("warn") and offset_ink(0.5) == tone_colour("error")


def test_by_model_adds_an_in_out_pair_per_model_most_work_first(services, project):
    a, b, _c = project.steps
    _record(services, project, a, "r1", opus=Tokens(1000, 0, 500))
    _record(services, project, b, "r2", haiku=Tokens(100, 0, 100))
    tab = services.tabs.open("expenditure", project.id)
    tab.by_model.setChecked(True)
    titles = [column.title for column in tab.table.columns()]
    assert titles[COLUMN["Out"] + 1 : COLUMN["Out"] + 5] == [
        "opus in",
        "opus out",
        "haiku in",
        "haiku out",
    ]
    assert tab.table.item(1, COLUMN["Out"] + 3).text() == "100"
    tab.by_model.setChecked(False)
    assert "opus in" not in [column.title for column in tab.table.columns()]


def test_a_record_another_process_writes_reaches_the_open_tab(services, project):
    """The harvest writes the ledger from an agent's shell; nothing in the model says so,
    so the tab looks at the ledger on its own timer."""
    tab = services.tabs.open("expenditure", project.id)
    assert cell(tab, 0, "Runs") == ""
    _record(services, project, project.steps[0], "late", opus=Tokens(10, 0, 10))
    tab._check_ledger()
    assert cell(tab, 0, "Runs") == "1"


def test_a_milestone_row_keeps_its_tint_and_a_double_click_opens_details(
    services, project, monkeypatch
):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog
    from dplanner.planning import milestone

    c = project.steps[2]
    services.undo.push(SetModuleDataCommand(c.id, milestone.MODULE_ID, milestone.write("MVP")))
    tab = services.tabs.open("expenditure", project.id)
    assert tab.table.item(2, 0).data(TINT_ROLE) is not None
    shown = []
    monkeypatch.setattr(
        StepDetailsDialog, "exec", lambda self: shown.append(self.panel.current_step_id())
    )
    tab.table.cellActivated.emit(0, 1)
    assert shown == [project.steps[0].id]


def test_the_index_and_go_open_it_and_the_export_is_a_row_per_step_and_model(
    services, project, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    a, _b, _c = project.steps
    _record(services, project, a, "r1", opus=Tokens(1, 2, 3), haiku=Tokens(4, 5, 6))
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.actions.run("expenditure.open", services.context.current())
    opened = [activity.uri for activity in services.tabs.activities()]
    assert activity_uri(tab_words.EXPENDITURE_KIND, project.id) in opened
    target = tmp_path / "spent.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(target), "CSV files (*.csv)")),
    )
    services.actions.run("expenditure.export", services.context.current())
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "#,Key,Step,Finished,Runs,Model,In,Cached,Out"
    assert [line.split(",")[2:] for line in lines[1:]] == [
        ["A", "yes", "1", "haiku", "4", "5", "6"],
        ["A", "yes", "1", "opus", "1", "2", "3"],
    ]
    spec = services.actions.spec("expenditure.export")
    assert (spec.menu, spec.group, spec.submenu) == ("File", "export", "Export")
