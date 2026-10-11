"""Run Agent's worktrees, prepared inline from a repository with a commit — see
``tests/launching.py`` — and the step the module's tests launch on."""

import pytest
from tests.launching import library_repo, services

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step

__all__ = ["library_repo", "services"]


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery", legacy=True)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.autosave.flush_now()
    return step
