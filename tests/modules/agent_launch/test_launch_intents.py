"""A launch's intent on disk: written whole, read back, and never a crash over a stranger's."""

from dplanner.domain.workflow import Daemon
from dplanner.modules.agent_launch.intents import LaunchIntent, LaunchIntents
from dplanner.modules.agent_launch.launcher import SHELL_FILE


def an_intent(tmp_path, run="20261004T120000Z-0000beef"):
    return LaunchIntent("s1", run, tmp_path / run, Daemon(), "2026-10-04T12:00:00")


def test_an_intent_reads_back_as_written_and_is_dropped_by_its_run(tmp_path):
    intents = LaunchIntents(tmp_path / "intents")
    intent = an_intent(tmp_path)
    intents.record(intent)
    assert intents.pending() == [intent]
    intents.drop(intent.run)
    assert intents.pending() == []


def test_started_is_the_wrapper_having_written_its_shell_file(tmp_path):
    intent = an_intent(tmp_path)
    intent.run_dir.mkdir()
    assert not intent.started
    (intent.run_dir / SHELL_FILE).write_text("pid=1\n", encoding="utf-8")
    assert intent.started


def test_a_file_this_build_cannot_read_is_skipped_and_outlives_clear(tmp_path):
    directory = tmp_path / "intents"
    intents = LaunchIntents(directory)
    intents.record(an_intent(tmp_path))
    stranger = directory / "newer.json"
    stranger.write_text('{"format": 9, "actor": "robot"}', encoding="utf-8")
    assert [each.step for each in intents.pending()] == ["s1"]
    intents.clear()
    assert intents.pending() == [] and stranger.exists()


def test_no_directory_is_no_intents(tmp_path):
    assert LaunchIntents(tmp_path / "never").pending() == []
