"""The window's half of the squad claims: polled from ``claims/``, worn on the card as a
squad chip, named in the Control Centre's Squad column, and ended by *End Squad Claim*."""

from dataclasses import replace

import pytest

from dplanner.domain import claims, ledger
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step, now_stamp
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.status_board.activity import (
    CONTROL_CENTRE_KIND,
    SQUAD_COLUMN,
    ControlCentreActivity,
)

OLD = "2026-10-01T09:00:00+00:00"


def module(services):
    return next(m for m in services.modules if m.id == "agent_claims")


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
    for title in ("Read the spec", "Ship the beta"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    return project


@pytest.fixture
def project_dir(services, project):
    return services.repo.project_dir(project.id)


def _claim(project, step, **fields) -> claims.Claim:
    claim = claims.claimed(
        project.id, "kettle", [step.id], now_stamp(), worker={"machine": ledger.machine_id()}
    )
    return replace(claim, **fields)


def test_a_claimed_step_wears_its_squad_and_an_abandoned_claim_is_amber(
    services, project, project_dir
):
    tab = services.tabs.open("project", project.id)
    step = project.steps[0]
    claims.write(project_dir, _claim(project, step))
    module(services).refresh()
    accent = tab._scene._nodes[step.id]._accent
    assert (accent.squad, accent.chip_text) == (("kettle", ""), "")
    assert tab._scene._nodes[project.steps[1].id]._accent.squad == ("", "")

    (held,) = claims.records(project_dir)
    claims.write(project_dir, replace(held, heartbeat=OLD))
    module(services).refresh()
    accent = tab._scene._nodes[step.id]._accent
    assert accent.squad == ("kettle · abandoned", "attention")


def test_the_control_centre_names_the_squad_only_while_one_holds_a_step(
    services, project, project_dir
):
    tab = services.tabs.open(CONTROL_CENTRE_KIND)
    assert isinstance(tab, ControlCentreActivity)
    assert tab.table.isColumnHidden(SQUAD_COLUMN)
    step = project.steps[0]
    claims.write(project_dir, _claim(project, step))
    module(services).refresh()
    tab._refresh()
    row = tab.table.row_of(step.id)
    item = tab.table.item(row, SQUAD_COLUMN) if row is not None else None
    assert item is not None and item.text() == "kettle"
    assert not tab.table.isColumnHidden(SQUAD_COLUMN)


def test_end_squad_claim_is_a_persons_clear_of_the_whole_claim(services, project, project_dir):
    step = project.steps[0]
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    end = services.actions.spec("agent.end_claim")
    assert not end.state(services.context.current()).enabled
    claims.write(project_dir, _claim(project, step))
    module(services).refresh()
    assert end.state(services.context.current()).enabled
    (held,) = claims.records(project_dir)
    run = ledger.LedgerRecord(
        run="20261007T101500Z-0000dddd",
        project=project.id,
        step=step.id,
        harness="claude",
        launched="2026-10-07T10:15:00+00:00",
        mode=ledger.HEADLESS,
        stage="execute",
        claim=held.id,
    )
    ledger.write(project_dir, run)
    services.actions.run("agent.end_claim", services.context.current())
    (claim,) = claims.records(project_dir)
    assert claim.ended["by"]["kind"] == "person" and claim.ended["why"] == "cleared"
    fenced = ledger.find(project_dir, run.run)
    assert fenced is not None and fenced.fence is not None  # Its worker is stopped too.
    assert module(services).holding(project.id) == {}
