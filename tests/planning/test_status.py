"""The status vocabulary: what a reader is handed, and what readiness makes of it.

The stored format and its CLI are ``tests/modules/step_status/test_step_status.py``'s; this
file holds the claims the planning tier makes about the *types* — that an unreadable word and
a wait not over are readings of their own, and that a literal compared with a status is
refused before the code ever runs.
"""

import textwrap

import pytest
from mypy import api as mypy_api

from dplanner.domain.model import Step
from dplanner.planning.status import (
    MODULE_ID,
    Status,
    Unknown,
    Waiting,
    held,
    phrase,
    readiness_of,
    stored,
    word,
)


def test_a_word_this_build_cannot_read_holds_its_step():
    assert held(Unknown("paused")) is Status.BLOCKED


def test_a_wait_not_over_is_still_pending_to_readiness():
    assert held(Waiting()) is Status.PENDING


def test_a_known_status_reads_as_itself():
    assert [held(status) for status in Status] == list(Status)


def test_readiness_reads_what_a_step_stores():
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"status": "paused", "format": 2}
    assert stored(step) == Unknown("paused")
    assert readiness_of(stored)(step) is Status.BLOCKED


def test_every_reading_has_a_word_on_its_way_out():
    assert word(Status.READY_FOR_REVIEW) == "ready-for-review"
    assert phrase(Status.READY_FOR_REVIEW) == "ready for review"
    assert (word(Unknown("paused")), word(Waiting())) == ("unknown", "waiting")


@pytest.mark.parametrize(
    "line",
    [
        'stored(step) == "done"',
        'held(stored(step)) != "blocked"',
    ],
)
def test_comparing_a_status_with_a_word_is_a_type_error(tmp_path, line):
    """The rule the Enum exists for: ``--strict-equality`` refuses a copied word, so a
    literal compared with a status never reaches a review, let alone a run."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            f"""\
            from dplanner.domain.model import Step
            from dplanner.planning.status import held, stored

            def check(step: Step) -> bool:
                return {line}
            """
        )
    )
    out, _err, code = mypy_api.run(
        [
            str(probe),
            "--strict",
            "--no-error-summary",
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    assert code == 1
    assert "Non-overlapping equality check" in out
