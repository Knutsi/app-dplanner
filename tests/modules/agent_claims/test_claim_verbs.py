"""``dplanner claim take|list|release|end``, the launch check ``agent run --callsign`` makes,
and a person's status releasing one step — run in-process against a project in a git
repository with no remote, so a claim is committed and the push is a no-op."""

import json
from collections.abc import Mapping
from io import StringIO
from pathlib import Path

import pytest

from dplanner.domain import claims, ledger
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import now_stamp

OLD = "2026-10-01T09:00:00+00:00"


@pytest.fixture
def project(cli, workspace, monkeypatch) -> Path:
    """A project with three steps, its verbs scoped to it."""
    cli("project", "create", "Discovery")
    monkeypatch.setenv("DPLANNER_PROJECT", "Discovery")
    for title in ("Read the spec", "Cut the graph", "Estimate it"):
        cli("step", "add", "Discovery", title)
    return Path(workspace) / "discovery"


@pytest.fixture
def stopped(monkeypatch) -> list[str]:
    """Every run ``supervisor.stop`` was asked to stop — fenced as it really is."""
    from dplanner.modules.agent_supervisor import supervisor

    runs: list[str] = []
    real = supervisor.stop

    def stop(project_dir, run, by, why, config=None):
        runs.append(run)
        real(project_dir, run, by, why, config)

    monkeypatch.setattr(supervisor, "stop", stop)
    return runs


def _fence(project: Path, run: str) -> Mapping[str, str]:
    record = ledger.find(project, run)
    assert record is not None and record.fence is not None
    return record.fence


def _id(cli, title: str) -> str:
    return str(json.loads(cli("step", "show", title, "--json"))["id"])


def _run(project: Path, cli, title: str, claim: str, run: str) -> LedgerRecord:
    meta = json.loads((project / "project.dproj").read_text(encoding="utf-8"))
    record = LedgerRecord(
        run=run,
        project=meta["id"],
        step=_id(cli, title),
        harness="claude",
        launched="2026-10-07T10:15:00+00:00",
        mode=ledger.HEADLESS,
        stage="execute",
        callsign="kettle-two",
        claim=claim,
    )
    ledger.write(project, record)
    return record


def test_a_squad_takes_steps_and_another_squad_is_refused_naming_the_holder(cli, project):
    said = json.loads(cli("claim", "take", "S1", "S2", "--callsign", "kettle-actual", "--json"))
    (claim,) = claims.records(project)
    assert said["id"] == claim.id and claim.callsign == "kettle"
    assert claim.steps == (_id(cli, "Read the spec"), _id(cli, "Cut the graph"))
    assert claim.worker["machine"] == ledger.machine_id()
    refused = cli("claim", "take", "S2", "S3", "--callsign", "osprey", expect=1)
    assert "Cut the graph" not in refused and "S2 is held by kettle" in refused
    assert claim.short in refused
    assert len(claims.records(project)) == 1  # Refused whole: S3 was not taken either.


def test_one_squad_grows_its_one_claim(cli, project, monkeypatch):
    cli("claim", "take", "S1", "--callsign", "kettle")
    monkeypatch.setenv("DPLANNER_CALLSIGN", "kettle-actual")
    cli("claim", "take", "S2", "--callsign", "kettle-two")
    (claim,) = claims.records(project)
    assert len(claim.steps) == 2


def test_a_second_coordinator_that_chose_a_running_word_is_refused(cli, project, monkeypatch):
    cli("claim", "take", "S1", "--callsign", "kettle")
    (claim,) = claims.records(project)
    said = cli("claim", "take", "S2", "--callsign", "kettle", expect=1)
    assert f"squad kettle is running already ({claim.short}) — choose another word" in said
    monkeypatch.setenv("DPLANNER_CALLSIGN", "anvil-actual")
    cli("claim", "take", "S2", "--callsign", "kettle", expect=1)
    assert claims.records(project)[0].steps == claim.steps  # Nothing grew.
    cli("claim", "take", "S2", "--callsign", "anvil")
    assert len(claims.records(project)) == 2


def test_the_claim_is_committed_and_nothing_else_is(cli, project, workspace):
    import subprocess

    cli("claim", "take", "S1", "--callsign", "kettle")
    tracked = subprocess.run(
        ["git", "-C", str(workspace), "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    (claim,) = claims.records(project)
    assert claims.path_for(project, claim).relative_to(workspace).as_posix() in tracked
    assert "discovery/project.dproj" not in tracked  # The plan is the window's to Save.


def test_an_abandoned_claim_is_taken_over_and_its_workers_stopped(cli, project, stopped):
    # Another machine's squad, gone quiet: every agent-shell call here renews this machine's.
    stale = claims.claimed(
        "p", "osprey", [_id(cli, "Read the spec")], OLD, worker={"machine": "elsewhere"}
    )
    claims.write(project, stale)
    run = _run(project, cli, "Read the spec", stale.id, "20261001T091500Z-0a0b0c0d")
    listed = cli("claim", "list")
    assert "osprey" in listed and "abandoned" in listed
    cli("claim", "take", "S1", "--callsign", "kettle")
    mine = next(c for c in claims.records(project) if c.callsign == "kettle")
    assert mine.supersedes == ({"claim": stale.id, "step": _id(cli, "Read the spec")},)
    assert stopped == [run.run]
    fence = _fence(project, run.run)
    assert fence["by"] == "kettle" and mine.short in fence["why"]


def test_the_squad_that_lost_a_step_stands_down_when_it_comes_back(cli, project):
    """The returning loser: osprey's coordinator wakes after kettle took its step over, and
    its next ``dplanner`` call renews — which hands the step back rather than reclaiming it."""
    from dplanner.domain import claim_sync

    stale = claims.claimed(
        "p", "osprey", [_id(cli, "Read the spec")], OLD, worker={"machine": "elsewhere"}
    )
    claims.write(project, stale)
    cli("claim", "take", "S1", "--callsign", "kettle")
    claim_sync.renew(project, stale.id)  # Its coordinator's first call on waking.
    back = next(c for c in claims.records(project) if c.callsign == "osprey")
    assert back.ended and back.heartbeat == OLD
    assert "kettle" in cli("claim", "list") and "osprey" not in cli("claim", "list")


def test_release_hands_one_step_back_and_end_closes_the_claim(cli, project, stopped):
    cli("claim", "take", "S1", "S2", "--callsign", "kettle")
    (taken,) = claims.records(project)
    first = _run(project, cli, "Read the spec", taken.id, "20261007T101500Z-0000aaaa")
    second = _run(project, cli, "Cut the graph", taken.id, "20261007T101500Z-0000bbbb")
    said = cli("claim", "release", "S1", "--why", "merged")
    assert stopped == [first.run]
    (claim,) = claims.records(project)
    assert "S1 released" in said and claim.steps == (_id(cli, "Cut the graph"),)
    assert claim.released[0]["by"]["kind"] == "person"
    cli("claim", "end", claim.short)
    assert claims.records(project)[0].ended["why"] == "done"
    assert stopped == [first.run, second.run]
    assert cli("claim", "list") == "no claims\n"
    assert "ended" in cli("claim", "list", "--all")
    assert "already ended" in cli("claim", "end", claim.short, expect=1)


def test_a_persons_stopped_status_releases_the_step_and_stops_its_worker(cli, project, stopped):
    cli("claim", "take", "S1", "S2", "--callsign", "kettle")
    (claim,) = claims.records(project)
    run = _run(project, cli, "Read the spec", claim.id, "20261007T101500Z-1a2b3c4d")
    said = cli("status", "set", "S1", "blocked")
    assert "released from its squad's claim" in said
    (claim,) = claims.records(project)
    assert claim.steps == (_id(cli, "Cut the graph"),)
    assert claim.released[0]["why"] == "set blocked by a person"
    assert _fence(project, run.run)["why"] == "set blocked by a person"
    assert stopped == [run.run]


def test_a_worker_reaching_review_releases_nothing(cli, project, monkeypatch):
    cli("claim", "take", "S1", "--callsign", "kettle")
    monkeypatch.setenv("CLAUDECODE", "1")  # An agent's shell: the worker reports.
    said = cli("status", "set", "S1", "ready-for-review")
    assert "released" not in said
    assert claims.records(project)[0].steps == (_id(cli, "Read the spec"),)


def test_an_agent_shells_dplanner_run_renews_its_projects_claims(
    registry, cli, project, cli_library, at_work_board, monkeypatch
):
    from dplanner.cli.main import run
    from dplanner.domain import claim_sync
    from dplanner.modules import default_module_formats

    heard: list[tuple[Path, str]] = []
    monkeypatch.setattr(claim_sync, "renew", lambda path, squad: heard.append((path, squad)))
    argv = ["--library", str(cli_library), "status", "list", "Discovery"]
    for board in (None, at_work_board):  # Only an agent's shell signs: entry.py's rule.
        run(registry, default_module_formats(), argv, StringIO(), StringIO(), board=board)
    # A shell that names its member renews that member's squad alone.
    monkeypatch.setenv("DPLANNER_CALLSIGN", "kettle-actual")
    run(registry, default_module_formats(), argv, StringIO(), StringIO(), board=at_work_board)
    assert [(path.resolve(), squad) for path, squad in heard] == [
        (project.resolve(), ""),
        (project.resolve(), "kettle"),
    ]


def test_claim_verbs_need_a_squad_word(cli, project):
    assert "--callsign" in cli("claim", "take", "S1", "--callsign", " ", expect=1)


def test_a_claim_whose_push_is_refused_still_holds_and_says_it_waits_for_a_sync(
    cli, project, monkeypatch
):
    from dplanner.domain import claim_sync

    monkeypatch.setattr(claim_sync, "publish", lambda *_args, **_kw: claim_sync.UNPUBLISHED)
    said = cli("claim", "take", "S1", "--callsign", "kettle")
    assert "not published yet" in said
    (claim,) = claims.records(project)
    assert claim.steps == (_id(cli, "Read the spec"),) and not claim.ended


def test_ending_a_claim_stops_a_step_grown_onto_it_a_moment_before(
    cli, project, stopped, monkeypatch
):
    """Another take adds S2 and launches it between End's read and its locked write: the end
    stops S2's worker too, because it fences the steps it read under the claim's lock."""
    # Another machine's claim, so no renewal of this machine's touches it mid-test.
    claim = claims.claimed(
        "p", "kettle", [_id(cli, "Read the spec")], now_stamp(), worker={"machine": "elsewhere"}
    )
    claims.write(project, claim)
    first = _run(project, cli, "Read the spec", claim.id, "20261007T101500Z-0000f001")
    s2 = _id(cli, "Cut the graph")
    real = claims.update
    raced: list[str] = []

    def growth_lands_first(project_dir, id_, change, config=None):
        if not raced:
            raced.append(id_)
            real(project_dir, id_, lambda c: claims.grown(c, [s2], c.heartbeat), config)
            _run(project, cli, "Cut the graph", id_, "20261007T101500Z-0000f002")
        return real(project_dir, id_, change, config)

    monkeypatch.setattr(claims, "update", growth_lands_first)
    cli("claim", "end", claim.short)
    assert sorted(stopped) == sorted([first.run, "20261007T101500Z-0000f002"])
    assert claims.records(project)[0].ended


def test_a_take_racing_an_end_starts_its_own_claim_and_never_grows_the_ended_one(
    cli, project, monkeypatch
):
    from dplanner.modules.agent_claims import ownership
    from dplanner.modules.step_playbook.engine import halt_claimed

    cli("claim", "take", "S1", "--callsign", "kettle")
    (claim,) = claims.records(project)
    real = claims.update
    raced: list[str] = []

    def end_lands_first(project_dir, id_, change, config=None):
        if not raced:
            raced.append(id_)
            monkeypatch.setattr(claims, "update", real)
            ownership.end(
                project_dir, id_, {"kind": "person", "name": "Knut"}, "cleared", halt_claimed
            )
        return real(project_dir, id_, change, config)

    monkeypatch.setattr(claims, "update", end_lands_first)
    cli("claim", "take", "S2", "--callsign", "kettle")
    old, new = sorted(claims.records(project), key=lambda c: c.id != claim.id)
    assert old.id == claim.id and old.ended and old.steps == (_id(cli, "Read the spec"),)
    assert new.steps == (_id(cli, "Cut the graph"),) and not new.ended
