"""Open Pull Request: a step's PR on the web, from wherever the step is picked — greyed with
the reason while nothing says where it is."""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.github import module as github_module
from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, write


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    return step


@pytest.fixture
def opened(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(github_module, "open_url", calls.append)
    return calls


def record(services, step, refs):
    SetModuleDataCommand(step.id, MODULE_ID, write(refs)).redo(services.document)


def state(services):
    return services.actions.spec("github.open_pr").state(services.context.current())


def test_a_step_with_no_pull_request_is_greyed_and_says_so(services, step):
    assert not state(services).enabled
    assert state(services).label == "Open Pull Request — no pull request recorded"
    record(services, step, GithubRefs(branch="agent/s1-deploy"))
    assert state(services).label == "Open Pull Request — no pull request recorded"


def test_a_recorded_address_is_opened_as_it_was_recorded(services, step, opened):
    record(services, step, GithubRefs(pr_number=12, pr_url="https://github.com/o/r/pull/12"))
    assert state(services).enabled
    services.actions.run("github.open_pr", services.context.current())
    assert opened == ["https://github.com/o/r/pull/12"]


def test_a_number_needs_a_github_repository_to_be_found_in(services, step, opened, monkeypatch):
    record(services, step, GithubRefs(pr_number=12))
    assert state(services).label == "Open Pull Request — no GitHub repository to find PR #12 in"
    monkeypatch.setattr(github_module, "parse_repo", lambda _url: "owner/repo")
    assert state(services).enabled
    services.actions.run("github.open_pr", services.context.current())
    assert opened == ["https://github.com/owner/repo/pull/12"]
