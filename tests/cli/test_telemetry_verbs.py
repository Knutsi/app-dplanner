"""``dplanner telemetry``: reading the journal back, and the CLI's own rows in it.

The verbs are built over a journal under ``tmp_path`` — the composition root hands the
real paths in, and a test hands its own — so nothing here reads or clears the machine's.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliCommand, CliContext, CliRegistry
from dplanner.cli.main import run
from dplanner.cli.telemetry import commands
from dplanner.core.telemetry import Telemetry, current


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "telemetry" / "journal.jsonl", tmp_path / "telemetry" / "crash.log"


@pytest.fixture
def journal(paths):
    """A journal with a quick action (ring only), a slow one, a CLI run and a failure."""
    made = Telemetry(paths[0], surface="window")
    made.record("action", "steps.new", duration_ms=2.0)
    made.record("action", "steps.link", duration_ms=45.0)
    made.record("cli", "project list", exit_code=0)
    try:
        raise RuntimeError("boom")  # Raised, so the failure carries a real traceback.
    except RuntimeError as error:
        made.failure("dplanner.core.signals: slot failed", error)
    made.close()

    return made


@pytest.fixture
def telemetry_cli(paths):
    registry = CliRegistry()
    registry.register_all(commands(journal=paths[0], crash_log=paths[1]))

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        code = run(registry, [], list(argv), out, err)
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue()

    return invoke


def test_show_lists_what_reached_the_file_newest_last(telemetry_cli, journal):
    text = telemetry_cli("telemetry", "show")
    assert "steps.new" not in text  # Quick, so the ring's alone.
    assert text.index("steps.link") < text.index("project list") < text.index("slot failed")
    assert "45.0 ms" in text and "FAILED" in text and "[window" in text


def test_show_filters_by_kind_slowness_and_failure(telemetry_cli, journal):
    assert "project list" in telemetry_cli("telemetry", "show", "--kind", "cli")
    assert "steps.link" not in telemetry_cli("telemetry", "show", "--kind", "cli")
    slow = telemetry_cli("telemetry", "show", "--slow", "40")
    assert "steps.link" in slow and "project list" not in slow
    failures = telemetry_cli("telemetry", "show", "--failures")
    assert "RuntimeError: boom" in failures and "Traceback" in failures
    assert "steps.link" not in failures


def test_show_json_is_the_records(telemetry_cli, journal):
    data = json.loads(telemetry_cli("telemetry", "show", "--json", "--last", "1"))
    (record,) = data["spans"]
    assert record["kind"] == "failure" and record["error"]["type"] == "RuntimeError"
    assert data["journal"].endswith("journal.jsonl")


def test_failures_include_the_crash_logs_tail(telemetry_cli, journal, paths):
    paths[1].write_text('Fatal Python error: Segmentation fault\n  File "x.py", line 1\n')
    text = telemetry_cli("telemetry", "show", "--failures")
    assert "crash.log (tail):" in text and "Segmentation fault" in text


def test_an_empty_journal_says_so(telemetry_cli, paths):
    assert "No spans" in telemetry_cli("telemetry", "show")


def test_path_names_both_files(telemetry_cli, paths):
    text = telemetry_cli("telemetry", "path")
    assert str(paths[0]) in text and str(paths[1]) in text


def test_clear_removes_the_journal_its_rotated_half_and_the_crash_log(
    telemetry_cli, journal, paths
):
    paths[0].with_name("journal.1.jsonl").write_text("{}\n")
    paths[1].write_text("crash\n")
    removed = telemetry_cli("telemetry", "clear").splitlines()
    assert len(removed) == 3 and not any(path.exists() for path in paths)
    assert telemetry_cli("telemetry", "clear") == "Nothing to clear.\n"


# -- the CLI's own rows ----------------------------------------------------------------------------


def test_a_run_is_a_cli_span_with_its_words_and_exit_code(cli):
    current().clear()
    cli("project", "list")
    (span,) = [span for span in current().recent() if span.kind == "cli"]
    assert span.name == "project list" and span.ok
    assert span.detail["exit_code"] == 0 and span.detail["argv"][-2:] == ["project", "list"]


def test_a_refusal_is_a_run_that_ended_with_a_reason(cli):
    current().clear()
    cli("project", "show", "no-such-project", expect=1)
    (span,) = [span for span in current().recent() if span.kind == "cli"]
    assert span.ok and span.detail["exit_code"] == 1 and "no-such-project" in span.detail["refused"]


def test_a_bug_is_journaled_with_its_traceback_and_still_raised():
    def explode(_context: CliContext, _args) -> int:
        raise RuntimeError("a bug, not a refusal")

    registry = CliRegistry()
    registry.register(
        CliCommand(path=("boom", "now"), summary="", run=explode, needs_library=False)
    )
    current().clear()
    with pytest.raises(RuntimeError, match="a bug"):
        run(registry, [], ["boom", "now"], StringIO(), StringIO())
    (span,) = [span for span in current().recent() if span.kind == "cli"]
    assert span.ok is False and span.error_type == "RuntimeError"
    assert "a bug, not a refusal" in (span.traceback or "")
