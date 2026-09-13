"""``framework/recording.py``: a recorder command's stdout becomes a clip, whatever the
recorder does when asked to stop."""

import time
from typing import Any

import pytest
from tests.framework.fake_recorder import CHUNK_BYTES, recorder, wait_for

from dplanner.framework import recording
from dplanner.framework.recording import Recording


@pytest.fixture
def clip(app):
    made = Recording()
    heard: dict[str, Any] = {"chunks": 0}
    made.chunk.connect(lambda data: heard.__setitem__("chunks", heard["chunks"] + 1))
    made.finished.connect(lambda pcm: heard.__setitem__("pcm", pcm))
    made.failed.connect(lambda why: heard.__setitem__("why", why))
    yield made, heard
    made.discard()
    made.deleteLater()


@pytest.mark.parametrize("mode", ["term", "q", "ignore-term"])
def test_a_recording_collects_stdout_and_finishes_with_the_samples_on_stop(app, clip, mode):
    made, heard = clip

    assert made.start(recorder(mode)) is None
    assert made.is_recording()
    wait_for(app, lambda: heard["chunks"] >= 3)
    made.stop()
    wait_for(app, lambda: "pcm" in heard)

    assert len(heard["pcm"]) >= 3 * CHUNK_BYTES
    assert not made.is_recording() and "why" not in heard


def test_a_recorder_that_cannot_start_fails_with_its_name(app, clip):
    made, heard = clip

    assert made.start(["no-such-recorder-anywhere", "--raw"]) is None
    wait_for(app, lambda: "why" in heard)

    assert "no-such-recorder-anywhere" in heard["why"]
    assert not made.is_recording() and "pcm" not in heard


def test_a_recorder_that_exits_on_its_own_with_an_error_fails_with_its_stderr(app, clip):
    made, heard = clip

    made.start(recorder("fail"))
    wait_for(app, lambda: "why" in heard)

    assert heard["why"] == "no such device"
    assert "pcm" not in heard


def test_the_safety_cap_stops_a_forgotten_recording(app, clip, monkeypatch):
    monkeypatch.setattr(recording, "MAX_SECONDS", 0)  # Read at start(): stops at once.
    made, heard = clip

    made.start(recorder("term"))
    wait_for(app, lambda: "pcm" in heard)

    assert not made.is_recording()


def test_discard_kills_without_emitting_anything(app, clip):
    made, heard = clip

    made.start(recorder("ignore-term"))
    wait_for(app, lambda: heard["chunks"] >= 1)
    made.discard()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)

    assert not made.is_recording()
    assert "pcm" not in heard and "why" not in heard


def test_start_while_recording_is_refused_and_an_empty_command_too(app, clip):
    made, _heard = clip

    assert made.start([]) == "no recorder command"
    assert made.start(recorder("term")) is None
    assert made.start(recorder("term")) == "already recording"


def test_a_stopped_recording_can_start_again(app, clip):
    made, heard = clip

    made.start(recorder("term"))
    wait_for(app, lambda: heard["chunks"] >= 1)
    made.stop()
    wait_for(app, lambda: "pcm" in heard)
    first = heard.pop("pcm")
    made.start(recorder("q"))
    wait_for(app, lambda: heard["chunks"] >= 2)
    made.stop()
    wait_for(app, lambda: "pcm" in heard)

    assert len(heard["pcm"]) < len(first)
