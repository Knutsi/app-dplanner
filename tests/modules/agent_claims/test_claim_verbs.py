"""``dplanner claim take|list|release|end``, the launch check ``agent run --callsign`` makes,
and a person's status releasing one step — run in-process against a project in a git
repository with no remote, so a claim is committed and the push is a no-op."""

import json
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
    return workspace / "discovery"


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


def test_one_squad_grows_its_one_claim(cli, project):
    cli("claim", "take", "S1", "--callsign", "kettle")
    cli("claim", "take", "S2", "--callsign", "kettle-two")
    (claim,) = claims.records(project)
    assert len(claim.steps) == 2


def test_the_claim_is_committed_and_nothing_else_is(cli, project, workspace):
    import subprocess

    cli("claim", "take", "S1", "--callsign", "kettle")
    tracked = subprocess.run(
        ["git", "-C", str(workspace), "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    (claim,) = claims.records(project)
    assert claims.path_for(project, claim).relative_to(workspace).as_posix() in tracked
    assert "discovery/project.dproj" not in tracked  # The plan is the window's to Save.


def test_an_abandoned_claim_is_taken_over_and_its_unfinished_runs_fenced(cli, project):
    stale = claims.claimed(
        "p", "osprey", [_id(cli, "Read the spec")], OLD, worker={"machine": "elsewhere"}
    )
    claims.write(project, stale)
    run = _run(project, cli, "Read the spec", stale.id, "20261001T091500Z-0a0b0c0d")
    listed = cli("claim", "list")
    assert "osprey" in listed and "abandoned" in listed
    cli("claim", "take", "S1", "--callsign", "kettle")
    mine = next(c for c in claims.records(project) if c.callsign == "kettle")
    assert mine.supersedes == (stale.id,)
    fence = ledger.find(project, run.run).fence
    assert fence["by"] == "kettle" and mine.short in fence["why"]


def test_release_hands_one_step_back_and_end_closes_the_claim(cli, project):
    cli("claim", "take", "S1", "S2", "--callsign", "kettle")
    said = cli("claim", "release", "S1", "--why", "merged")
    (claim,) = claims.records(project)
    assert "S1 released" in said and claim.steps == (_id(cli, "Cut the graph"),)
    assert claim.released[0]["by"]["kind"] == "person"
    cli("claim", "end", claim.short)
    assert claims.records(project)[0].ended["why"] == "done"
    assert cli("claim", "list") == "no claims\n"
    assert "ended" in cli("claim", "list", "--all")
    assert "already ended" in cli("claim", "end", claim.short, expect=1)


def test_a_persons_stopped_status_releases_the_step_and_stops_its_worker(cli, project):
    cli("claim", "take", "S1", "S2", "--callsign", "kettle")
    (claim,) = claims.records(project)
    run = _run(project, cli, "Read the spec", claim.id, "20261007T101500Z-1a2b3c4d")
    said = cli("status", "set", "S1", "blocked")
    assert "released from its squad's claim" in said
    (claim,) = claims.records(project)
    assert claim.steps == (_id(cli, "Cut the graph"),)
    assert claim.released[0]["why"] == "set blocked by a person"
    assert ledger.find(project, run.run).fence["why"] == "set blocked by a person"


def test_a_worker_reaching_review_releases_nothing(cli, project, monkeypatch):
    cli("claim", "take", "S1", "--callsign", "kettle")
    monkeypatch.setenv("CLAUDECODE", "1")  # An agent's shell: the worker reports.
    said = cli("status", "set", "S1", "ready-for-review")
    assert "released" not in said
    assert claims.records(project)[0].steps == (_id(cli, "Read the spec"),)


def test_an_agent_shells_dplanner_run_renews_its_projects_claims(
    registry, cli, project, cli_library, at_work_board
):
    from dplanner.cli.main import run
    from dplanner.modules import default_module_formats

    heard: list[Path] = []
    argv = ["--library", str(cli_library), "status", "list", "Discovery"]
    for board in (None, at_work_board):  # Only an agent's shell signs: entry.py's rule.
        run(registry, default_module_formats(), argv, StringIO(), StringIO(), board=board,
            renew=heard.append)  # fmt: skip
    assert [path.resolve() for path in heard] == [project.resolve()]


def test_claim_verbs_need_a_squad_word(cli, project):
    assert "--callsign" in cli("claim", "take", "S1", "--callsign", " ", expect=1)


def test_a_claim_take_whose_push_is_refused_lets_go_of_what_it_took(cli, project, monkeypatch):
    from dplanner.core.storage.provider import StorageError
    from dplanner.domain import claim_sync

    def refused(*_args, **_kw):
        raise StorageError("rejected")

    monkeypatch.setattr(claim_sync, "publish", refused)
    said = cli("claim", "take", "S1", "--callsign", "kettle", expect=1)
    assert "could not be pushed" in said
    (claim,) = claims.records(project)
    assert claim.steps == () and claim.ended["why"] == "not pushed"


def test_a_lost_race_stands_down_from_the_step_another_squad_pushed_first(
    cli, project, monkeypatch
):
    from dplanner.domain import claim_sync

    rival = claims.claimed(
        "p", "osprey", [_id(cli, "Read the spec")], now_stamp(), worker={"machine": "elsewhere"}
    )
    order: list[str] = []
    monkeypatch.setattr(claim_sync, "push_order", lambda _dir: list(order))
    real = claim_sync.publish

    def publish(project_dir, message, config=None):
        """The push's rebase brings the rival in: it reached the remote first."""
        claims.write(project, rival)
        order[:] = [rival.id]
        return real(project_dir, message, config)

    monkeypatch.setattr(claim_sync, "publish", publish)
    said = cli("claim", "take", "S1", "S2", "--callsign", "kettle")
    assert "taken first by osprey" in said
    mine = next(c for c in claims.records(project) if c.callsign == "kettle")
    assert mine.steps == (_id(cli, "Cut the graph"),)
    assert mine.released[0]["why"] == f"taken first by osprey ({rival.short})"
