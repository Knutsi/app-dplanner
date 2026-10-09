"""``agent follow``: each harness says its recorded stream readably, and the follower tails a
run's turns as the supervisor writes them — onto the next turn when an answer resumes it, and
out once the run is over. Read-only, and no real agent CLI anywhere."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dplanner.domain import ledger, questions
from dplanner.domain.headless import CALLED, CAME_BACK, SAID_WIDTH
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.agent_opencode import harness as opencode
from dplanner.modules.agent_supervisor.follow import follow, follow_argv
from dplanner.modules.agent_supervisor.supervisor import RefusedError

TURNS = Path(__file__).parent.parent.parent / "fixtures" / "agent_turns"
HARNESSES = (claude.HARNESS, codex.HARNESS, opencode.HARNESS)
AT = "2026-10-08T10:00:00+00:00"


def stream(name: str) -> list[str]:
    record = json.loads((TURNS / f"{name}.json").read_text(encoding="utf-8"))
    return [*record["stdout_head"], *record.get("stdout_tail", [])]


def said(harness, name: str) -> list[str]:
    return [line for event in stream(name) for line in harness.headless.say(json.loads(event))]


@pytest.mark.parametrize(
    ("harness", "name", "tool", "came_back", "text"),
    [
        (claude.HARNESS, "claude-plan", "→ Bash: find .", "  ← ./calc.py", "Here's the plan."),
        (codex.HARNESS, "codex-done", "→ $ pwd; rg --files", "  ← 12", "Added `multiply"),
        (opencode.HARNESS, "opencode-done", "→ read: ", "  ← Edit applied", "Added `divide"),
    ],
)
def test_each_harness_says_what_the_agent_wrote_called_and_got_back(
    harness, name, tool, came_back, text
):
    lines = said(harness, name)
    assert any(line.startswith(tool) for line in lines)
    assert any(line.startswith(came_back) for line in lines)
    assert any(text in line for line in lines)
    # A call's argument and a result are one line each, cut short (the tool's name aside).
    assert all(
        "\n" not in line and len(line) <= SAID_WIDTH + 30
        for line in lines
        if line.startswith((CALLED, CAME_BACK))
    )


def test_codex_says_a_command_without_the_shell_it_was_wrapped_in():
    lines = said(codex.HARNESS, "codex-ask-door")
    assert not any("bash -lc" in line for line in lines)
    assert any("dplanner-ask" in line for line in lines if line.startswith(CALLED))


class Run:
    """A headless run whose turns are written by hand, as the supervisor would."""

    def __init__(self, tmp_path: Path) -> None:
        self.plan, self.config = tmp_path / "plan", tmp_path / "config"
        self.record = LedgerRecord(
            run=ledger.new_run_id(datetime(2026, 10, 8, 10, tzinfo=UTC)),
            project="p1",
            step="s1",
            harness="codex",
            launched=AT,
            machine=ledger.machine_id(self.config),
            mode=ledger.HEADLESS,
            stage="execute",
            attempt=1,
            callsign="kettle-two",
        )
        ledger.write(self.plan, self.record)
        self.dir = ledger.run_dir(self.record.run, self.config)
        self.dir.mkdir(parents=True)

    def turn(
        self, n: int, prompt: str = "launch", end: str = "", ended: str = "", question: str = ""
    ) -> None:
        turns = [t for t in self.record.turns if t.n != n]
        turn = Turn(n=n, prompt=prompt, started=AT, end=end, ended=ended, question=question)
        self.record = self.record.with_turns([*turns, turn])
        ledger.write(self.plan, self.record)

    def stream(self, n: int, lines: list[str]) -> None:
        with (self.dir / f"turn-{n}.jsonl").open("a", encoding="utf-8") as file:
            file.writelines(line + "\n" for line in lines)

    def end(self) -> None:
        self.record = replace(self.record, ended=AT)
        ledger.write(self.plan, self.record)


def test_follow_reads_a_turn_to_its_end_then_follows_the_next(tmp_path):
    """Turn one parks on a question; the answer resumes the run in turn two, which the follower
    picks up as soon as it is recorded; the run's end lets it go."""
    run = Run(tmp_path)
    asked = replace(
        questions.asked("p1", "s1", AT, [questions.one("Keep both?")]), run=run.record.run
    )
    questions.write(run.plan, asked)
    run.turn(1)
    run.stream(1, stream("codex-ask-door")[:3])

    def resumed() -> None:
        run.turn(2, prompt="answer")
        run.stream(2, stream("codex-done"))

    def over() -> None:
        run.turn(2, prompt="answer", end="done", ended=AT)
        run.end()

    steps = iter(
        [
            lambda: run.stream(1, stream("codex-ask-door")[3:]),
            lambda: run.turn(1, end="asked", ended=AT, question=asked.id),
            lambda: None,  # Parked: the follower waits with it.
            resumed,
            over,
        ]
    )
    out: list[str] = []
    said_end = follow(
        run.plan,
        run.record.run,
        HARNESSES,
        out=out.append,
        sleep=lambda _s: next(steps)(),
        config=run.config,
    )
    text = "\n".join(out)
    assert out[0].startswith(f"Run {run.record.run} on step s1 · execute attempt 1 · kettle-two")
    assert "── turn 1 · launch ──" in out and "── turn 2 · answer ──" in out
    assert text.index("── turn 1 ended asked") < text.index("── turn 2 · answer ──")
    assert f"{asked.short} asks: Keep both?" in text
    assert "Added `multiply(a, b)`" in text
    assert text.count("── turn 1 ended asked") == 1  # Said once, however long the park.
    assert said_end == out[-1] == "The run is over: its last turn ended done."


def test_a_fenced_run_says_why_it_ended(tmp_path):
    run = Run(tmp_path)
    run.turn(1, end="stopped", ended=AT)
    run.record = replace(run.record, fence={"at": AT, "by": "knut", "why": ledger.TAKEN_OVER})
    run.end()
    out: list[str] = []
    follow(run.plan, run.record.run, HARNESSES, out=out.append, config=run.config)
    assert out[-1] == f"The run is over: {ledger.TAKEN_OVER}."


def test_another_machines_run_is_not_followed_here(tmp_path):
    run = Run(tmp_path)
    ledger.write(run.plan, replace(run.record, machine="elsewhere", host="laptop"))
    with pytest.raises(RefusedError, match="ran on laptop"):
        follow(run.plan, run.record.run, HARNESSES, out=print, config=run.config)


def test_the_argv_runs_this_build_on_this_library(tmp_path):
    argv = follow_argv(tmp_path / "lib.json", tmp_path, "R1")
    assert argv[-5:] == ["agent", "follow", "R1", "--project-dir", str(tmp_path)]
