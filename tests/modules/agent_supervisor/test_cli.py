"""``dplanner agent supervise``: it refuses what it cannot drive before anything starts, and
finds a run's project from the library when it is not told."""

import subprocess
from argparse import Namespace
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from tests.platforms import set_home

from dplanner.cli.command import CliContext
from dplanner.domain import claims, ledger
from dplanner.domain.headless import LimitWindow, TurnEnd
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.model import now_stamp
from dplanner.domain.workflow import Release
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.step_playbook.engine import halt_pass

RUN = "20261007T101500Z-9c1e44ab"


def _headless(project_dir: Path, turns: tuple[Turn, ...] = ()) -> LedgerRecord:
    record = LedgerRecord(
        run=RUN,
        project="p1",
        step="s1",
        harness="claude",
        launched="2026-10-07T10:15:00+00:00",
        mode=ledger.HEADLESS,
        stage="execute",
    ).with_turns(turns)
    ledger.write(project_dir, record)
    return record


def test_a_parked_run_waits_for_its_prompt_and_an_over_one_is_refused(cli, tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path / "home")
    cli("project", "create", "Supervised")
    project_dir = next(path for path in tmp_path.rglob("project.dproj")).parent
    asked = Turn(n=1, prompt="launch", started="…", end="asked", why="prose")
    record = _headless(project_dir, (asked,))

    said = cli("agent", "supervise", RUN, expect=1)
    assert "is parked (turn 1 asked (prose)); resume it with --prompt" in said
    explicit = cli("agent", "supervise", RUN, "--project-dir", str(project_dir), expect=1)
    assert "--prompt" in explicit

    ledger.write(project_dir, replace(record, ended="2026-10-07T11:00:00+00:00"))
    assert "is over" in cli("agent", "supervise", RUN, expect=1)
    assert "no project in the library has a run" in cli("agent", "supervise", "nope", expect=1)


def test_agent_limits_shows_each_accounts_windows_and_its_hold(cli, tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path / "home")
    assert "Claude Code: nothing reported yet" in cli("agent", "limits")
    soon = datetime.now(UTC) + timedelta(hours=2)
    windows = [LimitWindow("five_hour", 0.97, soon)]
    limits.record_turn(
        limits.account_of(claude.HARNESS), RUN, windows, TurnEnd.DONE, None, datetime.now(UTC)
    )
    said = cli("agent", "limits")
    assert "new headless launches wait at 95% of a window" in said
    assert f"Claude Code: five-hour 97% until {limits.clock(soon)}" in said
    assert "held — Claude Code is at 97%" in said


def test_open_session_fences_a_parked_run_releases_its_step_and_resumes_it(
    cli, tmp_path, monkeypatch
):
    """The verb Open Session's terminal runs: refused while a turn runs; parked, the run is
    taken over, the step leaves the squad whose run it was (a person's override, the
    ``release`` handed in) and the harness resumes the session in the directory the run
    worked in."""
    from dplanner.modules.agent_supervisor import cli as supervisor_cli

    set_home(monkeypatch, tmp_path / "home")
    cli("project", "create", "Taken")
    project_dir = next(path for path in tmp_path.rglob("project.dproj")).parent
    squad = claims.claimed("p1", "kettle-two", ["s1"], now_stamp(), worker={"machine": "m"})
    claims.write(project_dir, squad)
    running = Turn(n=1, prompt="launch", started="…", pid=1)
    record = replace(
        _headless(project_dir, (running,)),
        machine=ledger.machine_id(),
        session="S-1",
        directory=str(tmp_path),
        claim=squad.id,
    )
    ledger.write(project_dir, record)
    assert "Follow it, or Stop Playbook first" in cli("agent", "open-session", RUN, expect=1)

    ledger.write(project_dir, record.with_turns([replace(running, pid=0, ended="…", end="asked")]))
    released: list[str] = []
    ran: list[tuple[list[str], Path]] = []

    def resumed(argv: list[str], cwd: Path, check: bool) -> "subprocess.CompletedProcess[str]":
        ran.append((argv, cwd))
        return subprocess.CompletedProcess(argv, 0)

    def release(_project_dir: Path, follow_up: Release) -> bool:
        released.append(follow_up.step)
        return True

    monkeypatch.setattr(subprocess, "run", resumed)
    commands = supervisor_cli.commands(harnesses=(claude.HARNESS,), release=release, halt=halt_pass)
    verb = next(command for command in commands if command.path == ("agent", "open-session"))
    args = Namespace(run=RUN, project_dir=str(project_dir), library=None)
    assert verb.run(cast(CliContext, None), args) == 0  # The verb reads nothing of it.
    fence = (ledger.find(project_dir, RUN) or record).fence
    assert fence is not None and fence["why"] == ledger.TAKEN_OVER
    assert released == ["s1"]
    assert ran == [(["claude", "--resume", "S-1"], tmp_path)]
