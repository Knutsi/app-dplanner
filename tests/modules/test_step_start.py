"""The start aspect in the window: one Type toggle, and nothing else of its own.

What a start *means* — the walks that stop at it — is held by ``tests/cli/test_start_verbs.py``
and the Covers tab's tests; this file holds the toggle a person marks it with.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_start.aspect import read


@pytest.fixture
def step(services, make_project):
    project = make_project("Widget")
    step = Step(title="Project start")
    AddNodeCommand(project.id, step).redo(services.document)
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    return step


def test_the_toggle_is_a_kind_after_wait(services):
    spec = services.actions.spec("start.toggle")
    assert (spec.menu, spec.group, spec.submenu, spec.order) == ("Step", "classify", "Type", 67)


def test_toggling_the_start_on_and_off_is_undoable(services, step):
    services.actions.run("start.toggle", services.context.current())
    assert read(step)
    assert services.actions.spec("start.toggle").state(services.context.current()).checked
    services.undo.undo()
    assert not read(step)
    services.undo.redo()
    services.actions.run("start.toggle", services.context.current())
    assert not read(step)
