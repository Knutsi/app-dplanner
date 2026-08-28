"""The background PR refresher: fresh state lands in the model, never on the undo stack."""

import time

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.github import refresh as refresh_mod
from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, read, write
from dplanner.modules.github.gh import PrInfo
from dplanner.modules.github.refresh import PrRefresher

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
    monkeypatch.setattr(refresh_mod, "parse_repo", lambda _url: "acme/widget")
    monkeypatch.setattr(refresh_mod, "gh_refusal", lambda **_kw: None)
    return PrRefresher(
        services.document,
        services.tasks,
        repository_for=lambda _step_id: "https://github.com/acme/widget",
        parent=services.window,
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


def test_a_gh_refusal_stops_the_timer_for_the_session(
    app, services, step, refresher, monkeypatch
):
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
