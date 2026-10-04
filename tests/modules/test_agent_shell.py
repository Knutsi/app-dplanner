"""Open Terminal in Worktree: a person's own shell where a step's work is — not an agent.

The verb opens the default profile's terminal on a plain shell in the step's worktree (or
its checkout, for a step that works in place), and it is not a run: nothing is briefed,
recorded or claimed.
"""

import shlex
from pathlib import Path

import pytest

from dplanner.cli.discovery import PROJECT_ENV
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.module import NO_WORKTREE
from dplanner.planning.status import Status


@pytest.fixture
def step(services, make_project):
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Step

    project = make_project("Discovery", legacy=True)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def select(services, step):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


def state(services):
    return services.actions.spec("agent.open_shell").state(services.context.current())


@pytest.fixture
def spawned(monkeypatch):
    """Where each terminal opened, and the script it was handed — nothing real starts."""
    calls: list[tuple[Path, Path]] = []
    scripts: list[Path] = []

    def resolve(_template, files, _workdir, **_kw):
        scripts.append(files.script)
        return ["fake-term"]

    def spawn(_command, cwd, **_kw):
        calls.append((cwd, scripts[-1]))
        return ""

    monkeypatch.setattr(launcher, "resolve_command", resolve)
    monkeypatch.setattr(launcher, "spawn", spawn)
    return calls


# -- the script ---------------------------------------------------------------------------------


def test_the_posix_script_moves_into_the_directory_and_becomes_the_person_s_shell(tmp_path):
    directory = tmp_path / "a tree"
    files = launcher.shell_script(directory, "S1 Deploy (shell)", project_id="p1", run_dir=tmp_path)
    text = files.script.read_text()
    assert f"cd {shlex.quote(str(directory))} ||" in text
    assert f"export {PROJECT_ENV}=p1" in text
    assert text.rstrip().endswith('exec "${SHELL:-/bin/sh}"')
    assert not files.shell_file.exists() and not files.exit_file.exists()  # Nothing reports.


def test_the_windows_script_opens_a_shell_of_its_own_in_the_directory(tmp_path):
    directory = tmp_path / "tree"
    files = launcher.shell_script(
        directory, "S1 Deploy (shell)", project_id="p1", run_dir=tmp_path, platform="win32"
    )
    raw = files.script.read_bytes().decode()
    assert f'cd /d "{directory}"\r\n' in raw
    assert f"set {PROJECT_ENV}=p1\r\n" in raw
    assert raw.endswith('"%ComSpec%" /k\r\n')


# -- the verb -----------------------------------------------------------------------------------


def test_a_step_that_works_in_place_opens_its_shell_in_the_checkout(
    services, step, library_repo, spawned
):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_agent_run.aspect import launched
    from dplanner.planning.agent import MODULE_ID, with_worktree
    from dplanner.planning.status import stored as status

    SetModuleDataCommand(step.id, MODULE_ID, with_worktree(step, False)).redo(services.document)
    select(services, step)
    assert state(services).enabled
    assert state(services).label == "&Open Terminal in Checkout"
    services.actions.run("agent.open_shell", services.context.current())
    ((cwd, script),) = spawned
    assert cwd == library_repo
    assert f"cd {shlex.quote(str(library_repo))}" in script.read_text()
    # Not a run: no chip, no claim.
    assert not launched(services.document.step(step.id))
    assert status(services.document.step(step.id)) is Status.PENDING


def test_a_worktree_step_is_greyed_until_its_worktree_is_here_then_opens_in_it(
    services, step, library_repo, spawned
):
    select(services, step)
    refused = state(services)
    assert not refused.enabled
    assert refused.label == f"Open Terminal in Worktree — {NO_WORKTREE}"

    tree = launcher.worktree_path(library_repo, launcher.run_name("S1", "", "Deploy"))
    tree.mkdir(parents=True)
    assert state(services).enabled
    services.actions.run("agent.open_shell", services.context.current())
    assert [cwd for cwd, _script in spawned] == [tree]


def test_a_review_opens_its_shell_in_the_checkout_it_runs_in(services, step, library_repo, spawned):
    """A review's run gets no worktree whatever its aspect says, so a shell of one's own
    opens where that run does."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.planning.review import MODULE_ID, ReviewSettings, write

    SetModuleDataCommand(step.id, MODULE_ID, write(ReviewSettings())).redo(services.document)
    select(services, step)
    assert state(services).label == "&Open Terminal in Checkout"
    services.actions.run("agent.open_shell", services.context.current())
    assert [cwd for cwd, _script in spawned] == [library_repo]
