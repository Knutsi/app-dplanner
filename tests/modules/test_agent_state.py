"""The agent-run aspect: its vocabulary on disk and its CLI."""

import json
from datetime import datetime
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.domain.model import Step
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.step_agent_run.aspect import MODULE_ID, launched, read, summary, write

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_no_run():
    step = Step(title="A")
    assert read(step) == ""
    assert launched(step) == ""
    assert summary(step) == ""


def test_write_and_read_round_trip():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write("plan-for-review")
    assert read(step) == "plan-for-review"
    assert summary(step) == "agent: plan for review"


def test_write_stamps_the_launch_time():
    entry = write("launched")
    datetime.fromisoformat(entry["launched"])


def test_write_preserves_a_given_launch_time():
    entry = write("working", launched="2026-01-01T00:00:00+00:00")
    assert entry["launched"] == "2026-01-01T00:00:00+00:00"


def test_clearing_writes_nothing():
    assert write("") == {}


def test_an_unknown_state_reads_as_no_run_not_an_error():
    """A newer build may know states this one does not; reading must not crash over one."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"state": "reviewing", "format": 1}
    assert read(step) == ""


def test_writing_an_unknown_state_is_refused():
    with pytest.raises(ValueError, match="unknown agent-run state"):
        write("reviewing")


# -- the CLI -----------------------------------------------------------------------------------


@pytest.fixture
def cli(workspace):
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        code = run(
            registry, default_module_formats(), ["--workspace", str(workspace), *argv], out, err
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    invoke("project", "create", "Discovery")
    invoke("step", "add", "Discovery", "Read the spec")
    return invoke


def entry_path(workspace):
    steps = workspace / "discovery" / "steps"
    return steps / "read-the-spec" / "modules" / "step_agent_run.json"


def test_set_show_and_clear(cli, workspace):
    cli("agent-state", "set", "Read the spec", "working")
    shown = json.loads(cli("agent-state", "show", "Read the spec", "--json"))
    assert shown["state"] == "working" and shown["launched"]
    assert entry_path(workspace).is_file()
    cli("agent-state", "clear", "Read the spec")
    assert "no agent run" in cli("agent-state", "show", "Read the spec")
    assert not entry_path(workspace).exists()


def test_set_keeps_the_original_launch_stamp(cli, workspace):
    cli("agent-state", "set", "Read the spec", "launched")
    first = json.loads(entry_path(workspace).read_text())["launched"]
    cli("agent-state", "set", "Read the spec", "working")
    assert json.loads(entry_path(workspace).read_text())["launched"] == first


def test_a_word_outside_the_vocabulary_is_refused_by_the_parser(cli):
    """Argparse refuses it before the verb runs — the vocabulary is in the usage line."""
    with pytest.raises(SystemExit):
        cli("agent-state", "set", "Read the spec", "reviewing")
