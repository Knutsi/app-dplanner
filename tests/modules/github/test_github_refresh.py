"""The background PR refresher: fresh state lands in the model, never on the undo stack."""

import time

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.github import refresh as refresh_mod
from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, read, write
from dplanner.modules.github.gh import PrInfo
from dplanner.modules.github.refresh import PrRefresher
from dplanner.planning.status import MERGED_ORIGIN, Status, record_merged
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import stored as status_read
from dplanner.planning.status import write as status_write

MERGED = PrInfo(number=12, title="Add login flow", state="merged", url="u12", head_ref="feat/login")


@pytest.fixture
def step(services, make_project):
    library = services.document
    project = make_project("Discovery")
    step = Step(title="Read the spec")
    AddNodeCommand(project.id, step).redo(library)
    SetModuleDataCommand(step.id, MODULE_ID, write(GithubRefs(pr_number=12))).redo(library)
    return step


@pytest.fixture
def refresher(services, monkeypatch):
    """A refresher of this test's own — and the application's silenced first.

    ``services`` is a whole running application, and the github module builds and *starts* a
    ``PrRefresher`` in it. The patches below are module globals, which that one reads too: with
    ``parse_repo`` answering for any URL and ``gh_refusal`` answering None, its pending first
    tick becomes a second call to this test's fake ``view_pr``, landing whenever ``wait_for``
    next pumps the event loop. That is what made ``test_a_terminal_state_is_not_rechecked``
    fail with ``[12, 12] == [12]``, on timing rather than on anything it was testing.
    """
    for running in services.window.findChildren(PrRefresher):
        running.stop()
    monkeypatch.setattr(refresh_mod, "parse_repo", lambda _url: "acme/widget")
    monkeypatch.setattr(refresh_mod, "gh_refusal", lambda **_kw: None)
    return PrRefresher(
        services.document,
        services.tasks,
        repository_for=lambda _step_id: "https://github.com/acme/widget",
        parent=services.window,
        # As the composition root wires it.
        finish_merged=lambda step_id: record_merged(
            services.document, step_id, services.clock.today()
        ),
    )


def set_status(services, step, status):
    today = services.clock.today()
    SetModuleDataCommand(step.id, STATUS_ID, status_write(Status(status), today=today)).redo(
        services.document
    )


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "refresh never delivered"
        app.processEvents()
        time.sleep(0.01)


def test_a_ticks_answer_updates_the_model_but_not_the_undo_stack(
    app, services, step, refresher, monkeypatch
):
    monkeypatch.setattr(refresh_mod, "view_pr", lambda _repo, _number: MERGED)
    assert not services.undo.can_undo()

    refresher._tick()
    wait_for(app, lambda: (read(services.document.step(step.id)) or GithubRefs()).pr_state)

    refs = read(services.document.step(step.id))
    assert refs is not None and refs.pr_state == "merged" and refs.pr_title == "Add login flow"
    # A cache of an external fact is not a user decision: Ctrl+Z must not restore staleness.
    assert not services.undo.can_undo()


def test_a_terminal_state_is_not_rechecked(app, services, step, refresher, monkeypatch):
    calls = []

    def view_pr(_repo, number):
        calls.append(number)
        return MERGED

    monkeypatch.setattr(refresh_mod, "view_pr", view_pr)

    refresher._tick()
    wait_for(app, lambda: not refresher._runner.is_busy())
    assert calls == [12]

    refresher._tick()  # Now merged: nothing left to check, so no run starts.
    wait_for(app, lambda: not refresher._runner.is_busy())
    assert calls == [12]


def test_a_stale_answer_is_dropped(services, step, refresher):
    """The user re-pointed the step at another PR while the worker was out."""
    SetModuleDataCommand(step.id, MODULE_ID, write(GithubRefs(pr_number=99))).redo(
        services.document
    )
    refresher._apply([(step.id, MERGED)])
    refs = read(services.document.step(step.id))
    assert refs is not None and refs.pr_number == 99 and refs.pr_state == ""


def test_a_gh_refusal_stops_the_timer_for_the_session(app, services, step, refresher, monkeypatch):
    monkeypatch.setattr(refresh_mod, "gh_refusal", lambda **_kw: "gh not found on PATH")
    refresher._timer.start()
    refresher._tick()
    wait_for(app, lambda: not refresher._timer.isActive())


def test_the_refresh_write_carries_the_refreshers_origin(services, step, refresher):
    origins = []
    services.document.module_data_changed.connect(
        lambda _node, _module, origin: origins.append(origin)
    )
    refresher._apply([(step.id, MERGED)])
    assert origins == [refresh_mod.REFRESH_ORIGIN]


def test_a_merged_pr_finishes_a_step_waiting_on_its_merge(services, step, refresher):
    set_status(services, step, "ready-to-merge")
    written = []
    services.document.module_data_changed.connect(
        lambda _node, module, origin: written.append((module, origin))
    )
    refresher._apply([(step.id, MERGED)])
    assert status_read(services.document.step(step.id)) is Status.DONE
    assert (STATUS_ID, MERGED_ORIGIN) in written
    # Undo is for decisions: GitHub merged it, and Ctrl+Z cannot take that back.
    assert not services.undo.can_undo()


def test_a_merged_pr_leaves_work_nobody_accepted_alone(services, step, refresher):
    set_status(services, step, "in-progress")
    refresher._apply([(step.id, MERGED)])
    assert status_read(services.document.step(step.id)) is Status.IN_PROGRESS


def test_a_tick_finishes_a_step_whose_pr_read_merged_before_it_was_accepted(
    services, step, refresher, monkeypatch
):
    """A review approved after the developer merged by hand carries a merged state that
    is never fetched again: the tick finishes it from what is stored."""
    SetModuleDataCommand(
        step.id, MODULE_ID, write(GithubRefs(pr_number=12, pr_state="merged"))
    ).redo(services.document)
    set_status(services, step, "ready-to-merge")
    monkeypatch.setattr(refresh_mod, "view_pr", lambda _repo, _number: pytest.fail("fetched"))
    refresher._tick()
    assert status_read(services.document.step(step.id)) is Status.DONE
