"""``dplanner agent supervise``: it refuses what it cannot drive before anything starts, and
finds a run's project from the library when it is not told."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.platforms import set_home

from dplanner.domain import ledger
from dplanner.domain.headless import LimitWindow, TurnEnd
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.modules.agent_supervisor import limits

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
    limits.record_turn("claude", RUN, windows, TurnEnd.DONE, None, True)
    said = cli("agent", "limits")
    assert "new headless launches wait at 95% of a window" in said
    assert f"Claude Code: five-hour 97% until {limits.clock(soon)}" in said
    assert "held — Claude Code is at 97%" in said
