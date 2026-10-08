"""The claims record (``domain/claims.py``): a squad's lease on its steps, a file per claim,
judged by the reader's clock."""

import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from dplanner.domain import claims, questions
from dplanner.domain.claims import Claim
from dplanner.domain.model import now_stamp

AT = "2026-10-07T10:00:00+00:00"
WORKER = {"machine": "m1", "host": "knut-arch"}
PERSON = {"kind": "person", "name": "Knut"}


def _at(minutes: float) -> str:
    """A stamp ``minutes`` after :data:`AT`."""
    return (datetime.fromisoformat(AT) + timedelta(minutes=minutes)).isoformat()


def _claim(*steps: str, callsign: str = "kettle-three", **fields) -> Claim:
    return replace(claims.claimed("p1", callsign, steps or ("s1",), AT, worker=WORKER), **fields)


def test_a_claim_round_trips_through_its_file_and_absence_is_the_default(tmp_path):
    claim = _claim("s1", "s2")
    claims.write(tmp_path, claim)
    path = tmp_path / "claims" / "2026-10" / f"{claim.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["callsign"] == "kettle"  # The squad word, never a member's callsign.
    assert "lease_minutes" not in raw and "ended" not in raw and "supersedes" not in raw
    assert claims.records(tmp_path) == [claim]
    assert claims.find(tmp_path, claim.id) == claim
    assert claims.resolve(tmp_path, claim.short) == claim


def test_a_file_this_build_cannot_read_is_skipped(tmp_path):
    claims.write(tmp_path, _claim())
    month = tmp_path / "claims" / "2026-10"
    (month / "newer.json").write_text(json.dumps({"format": 99, "id": "x"}), encoding="utf-8")
    (month / "torn.json").write_text("{half", encoding="utf-8")
    assert len(claims.records(tmp_path)) == 1


def test_a_heartbeat_is_written_only_once_it_is_ten_minutes_old():
    claim = _claim()
    assert claims.beaten(claim, _at(9)) is claim
    assert claims.beaten(claim, _at(10)).heartbeat == _at(10)
    assert claims.beaten(replace(claim, ended={"at": AT}), _at(30)).heartbeat == AT


def test_a_released_step_leaves_the_rest_with_the_squad_and_the_last_ends_the_claim():
    claim = claims.released(_claim("s1", "s2"), "s1", PERSON, "done", _at(1))
    assert claim.steps == ("s2",) and not claim.ended
    assert claim.released == ({"step": "s1", "at": _at(1), "by": PERSON, "why": "done"},)
    last = claims.released(claim, "s2", PERSON, "blocked", _at(2))
    assert last.steps == () and last.ended["why"] == "blocked"
    with pytest.raises(ValueError):
        claims.released(last, "s2", PERSON, "again", _at(3))
    with pytest.raises(ValueError):
        claims.ended(last, PERSON, "twice", _at(3))


def test_past_its_lease_a_claim_is_abandoned_unless_every_step_is_parked():
    claim = _claim("s1", "s2")
    assert claims.standing(claim, _at(90), {}) == claims.LIVE
    assert claims.standing(claim, _at(91), {}) == claims.ABANDONED
    one = {"s1": _at(30)}
    assert claims.standing(claim, _at(91), one) == claims.ABANDONED
    both = {"s1": _at(30), "s2": _at(60)}
    assert claims.standing(claim, _at(91), both) == claims.PARKED
    # Parked holds until the oldest wait is max_park_hours old.
    assert claims.standing(claim, _at(30 + 24 * 60), both) == claims.ABANDONED
    assert claims.standing(replace(claim, ended={"at": AT}), _at(1), {}) == claims.ENDED


def test_a_step_waits_on_its_oldest_unsettled_question():
    def asked(step: str, at: str, state: str = questions.OPEN):
        return replace(questions.asked("p1", step, at, []), state=state)

    parked = claims.parks(
        [
            asked("s1", _at(20)),
            asked("s1", _at(10), questions.ANSWERED),
            asked("s2", _at(5), questions.CONSUMED),
        ]
    )
    assert parked == {"s1": _at(10)}


def test_the_claim_pushed_first_holds_a_step_and_an_abandoned_one_yields():
    early, late = _claim("s1", callsign="kettle"), _claim("s1", "s2", callsign="osprey")
    held = claims.holdings([early, late], _at(1), {}, order=[late.id, early.id])
    assert held["s1"].claim is late  # Pushed first, whatever the clock said.
    assert held["s2"].claim is late
    stale = _claim("s1", callsign="kettle", heartbeat=_at(-200))
    held = claims.holdings([stale, late], _at(1), {}, order=[stale.id, late.id])
    assert held["s1"].claim is late
    alone = claims.holdings([stale], _at(1), {})
    assert alone["s1"].state == claims.ABANDONED
    assert claims.holder_words(alone["s1"]) == "kettle · abandoned"


def test_release_step_releases_from_the_holder_or_the_claim_named(tmp_path):
    claim = _claim("s1", "s2", heartbeat=now_stamp())
    claims.write(tmp_path, claim)
    config = tmp_path / "config"
    assert claims.release_step(tmp_path, "s9", PERSON, "done", config=config) is None
    released = claims.release_step(tmp_path, "s1", PERSON, "done", config=config)
    assert released is not None and released.steps == ("s2",)
    assert claims.find(tmp_path, claim.id) == released


def test_two_writers_at_once_lose_neither_update(tmp_path):
    claim = _claim("s1", "s2", "s3")
    claims.write(tmp_path, claim)
    config = tmp_path / "config"

    def release(step: str) -> None:
        claims.update(
            tmp_path, claim.id, lambda c: claims.released(c, step, PERSON, "done", AT), config
        )

    workers = [threading.Thread(target=release, args=(step,)) for step in ("s1", "s2")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert claims.find(tmp_path, claim.id).steps == ("s3",)
