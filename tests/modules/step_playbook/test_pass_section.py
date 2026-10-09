"""The Playbook tab of Step Details: a pass's outcome, what it changed, and the verbs — read
from records written to a plan directory, its verbs handed to fakes."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from tests.modules.step_playbook.test_changes import git, repo  # noqa: F401 - a fixture
from tests.modules.step_playbook.test_history import write
from tests.modules.step_playbook.test_passes import CHANGED, PASSED, gate, run

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.step_playbook.pass_section import NO_PASS, PassSection
from dplanner.modules.step_playbook.workflows import ACCEPTED
from dplanner.planning import status
from dplanner.planning.agent import MODULE_ID as AGENT_ID
from dplanner.planning.agent import write_state as agent_state


@dataclass
class Fakes:
    """Every verb the tab hands on, recorded."""

    sent: list[tuple[str, str]] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    accepted: list[tuple[str, str, str]] = field(default_factory=list)
    followed: list[str] = field(default_factory=list)
    terminals: list[tuple[Path, Sequence[str]]] = field(default_factory=list)

    def run_refusals(self, _project_dir: Path, _run: str) -> tuple[str, str]:
        return "", "its session is another machine's"

    def follow_by_id(self, _project_dir: Path, run: str) -> None:
        self.followed.append(run)

    def open_session_by_id(self, _project_dir: Path, run: str) -> None:
        raise AssertionError("greyed")

    def accept_playbook(self, step: Step) -> None:
        self.passed.append(step.id)

    def send_back(self, step: Step, note: str) -> None:
        self.sent.append((step.id, note))

    def accept(self, step: Step, reason: str, titled: str) -> str:
        self.accepted.append((step.id, reason, titled))
        return ""

    def open_terminal(
        self,
        directory: Path,
        _title: str,
        argv: Sequence[str],
        _project: str,
        opened: Callable[[str], None],
    ) -> None:
        self.terminals.append((directory, argv))
        opened("")


@pytest.fixture
def step(services, make_project) -> Step:
    project = make_project("Widget")
    made = Step(title="Build it")
    AddNodeCommand(project.id, made).redo(services.document)
    services.document.set_module_data(made.id, AGENT_ID, agent_state(True))
    services.document.set_module_data(made.id, status.MODULE_ID, {"status": "ready-for-review"})
    return services.document.step(made.id)


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def tab(services, step, tmp_path, fakes, qapp):
    made = PassSection(
        services.document,
        project_dir=lambda _step: tmp_path,
        harnesses=(),
        runs=fakes,
        verbs=fakes,
        open_terminal=fakes.open_terminal,
        accept=fakes.accept,
        tasks=None,
        changed=lambda _slot: lambda: None,
    )
    yield made
    made.dispose()
    made.deleteLater()


def texts(tab: PassSection) -> list[str]:
    table = tab.table
    return [table.item(row, 0).text() for row in range(table.rowCount())]


def test_a_step_with_no_pass_says_so_in_one_line(tab, step):
    tab.show_target(step.id)
    assert tab.empty.text() == NO_PASS and not tab.empty.isHidden()
    assert tab.content.isHidden()


def test_a_two_round_pass_reads_as_its_work_its_findings_and_its_verbs(tab, step, tmp_path, fakes):
    planned, executed = run("plan"), replace(run("execute"), summary="Built it")
    review = run("review", verdict=CHANGED)
    fix = replace(
        run("execute"),
        attempt=2,
        summary="Fixed the race",
        declined=({"finding": {"run": review.run, "index": 0}, "reason": "cannot race"},),
    )
    write(tmp_path, step, planned, executed, review, fix, run("review", verdict=PASSED))
    tab.show_target(step.id)
    assert tab.content.isVisibleTo(tab) and tab.empty.isHidden()
    assert tab.head.words().startswith("Waits for you · ready for review")
    rows = texts(tab)
    assert rows[0].startswith("Pass P ·") and "↳ A race" in rows
    finding = rows.index("↳ A race")
    assert tab.table.item(finding, 2).text() == "declined"
    assert "Fixed the race" in tab.detail.toPlainText()  # The latest work's own account.
    assert "No commits" not in tab.commits.text()
    assert "no run of the pass recorded where it worked" in tab.where.text()

    assert tab.accept_button.isEnabled() and tab.accept_button.text() == "Accept"
    assert not tab.send_back_button.isEnabled()  # Nothing to send it back with yet.
    tab.note_edit.setPlainText("the empty state says nothing")
    assert tab.send_back_button.isEnabled()
    tab.send_back_button.click()
    assert fakes.sent == [(step.id, "the empty state says nothing")]
    tab.accept_button.click()
    ((accepted, reason, titled),) = fakes.accepted
    assert (accepted, titled) == (step.id, ACCEPTED) and reason.startswith("Accepted after pass P")

    tab.table.setCurrentCell(finding, 0)
    assert "cannot race" in tab.detail.toPlainText()
    assert tab.follow_button.isEnabled() and not tab.open_session_button.isEnabled()
    tab.follow_button.click()
    assert fakes.followed == [review.run]


def test_an_open_gate_is_answered_from_the_tab(tab, step, tmp_path, fakes):
    write(tmp_path, step, run("execute"), gate("person"), preset="plan-execute-person")
    tab.show_target(step.id)
    assert tab.accept_button.text() == "Pass"
    tab.accept_button.click()
    assert fakes.passed == [step.id] and not fakes.accepted


def test_earlier_passes_are_folded_under_the_latest(tab, step, tmp_path):
    write(tmp_path, step, run("execute"), pass_id="old", preset="execute")
    write(tmp_path, step, run("execute"), pass_id="new", preset="execute")
    tab.show_target(step.id)
    assert tab.table.collapsed() == {"old"}
    assert texts(tab)[0].startswith("Pass new")


def test_work_that_left_no_commits_says_so_and_still_opens_its_worktree(
    tab,
    step,
    tmp_path,
    fakes,
    repo,  # noqa: F811 - the fixture
):
    write(tmp_path, step, replace(run("execute"), directory=str(repo)), preset="execute")
    tab.show_target(step.id)
    assert tab.commits.text().startswith("No commits on agent/s1 since main")
    assert tab.open_diff_button.isEnabled()
    tab.open_worktree_button.click()
    tab.open_diff_button.click()
    assert fakes.terminals == [(repo, ()), (repo, ["git", "diff", "main...agent/s1"])]
    assert tab.said.words().endswith("opened")
