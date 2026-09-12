"""The agent harnesses: the contract, each provider's reader, the multiplexer rows, and
the launch profiles that pick among them."""

import json
import re
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QComboBox, QLineEdit, QListWidget, QPushButton

from dplanner.domain.agents import AgentHarness, RunFacts, Usage, harness_by_id, harness_for_command
from dplanner.modules import agent_harnesses
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.agent_opencode import harness as opencode
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.launcher import LaunchFiles

HARNESSES = agent_harnesses()

# -- the contract ------------------------------------------------------------------------------


def test_capabilities_are_derived_from_the_record_never_declared():
    bare = AgentHarness("x", "X", "x {prompt}")
    assert bare.capabilities() == ()
    named = AgentHarness("y", "Y", "y --id {session} {prompt}", resume="y --resume {session}")
    assert named.capabilities() == ("names its session", "resumes")
    found = AgentHarness(
        "z", "Z", "z {prompt}", resume="z resume {session}", report=lambda _f: None
    )
    assert found.capabilities() == ("resumes", "counts tokens")
    # A resume template alone is nothing: with no id up front and no way to find one,
    # the run cannot be picked up.
    assert not AgentHarness("w", "W", "w {prompt}", resume="w {session}").resumes


def test_a_stored_command_text_is_read_as_the_harness_that_shipped_it():
    assert harness_for_command(HARNESSES, "claude --permission-mode plan {prompt}") is HARNESSES[0]
    assert harness_for_command(HARNESSES, " codex {prompt} ") is HARNESSES[1]
    assert harness_for_command(HARNESSES, "my-agent {prompt}") is None
    assert harness_by_id(HARNESSES, "opencode") is HARNESSES[2]
    assert harness_by_id(HARNESSES, "nobody") is None


def test_every_harness_marks_its_shells_and_the_claude_rule_covers_new_names():
    assert HARNESSES[0].marks("CLAUDECODE") and HARNESSES[0].marks("CLAUDE_CODE_BRIDGE_SESSION_ID")
    assert not HARNESSES[0].marks("CLAUDE_CONFIG_DIR")
    assert HARNESSES[1].marks("CODEX_THREAD_ID") and not HARNESSES[1].marks("CODEX_HOME")
    assert HARNESSES[2].marks("OPENCODE") and not HARNESSES[2].marks("OPENCODE_DB")
    env = {"CODEX_THREAD_ID": "t", "OPENCODE": "1", "PATH": "/bin", "CODEX_HOME": "/h"}
    assert launcher.scrubbed_environment(env, HARNESSES) == {"PATH": "/bin", "CODEX_HOME": "/h"}


# -- Claude Code: the transcript ---------------------------------------------------------------


def _assistant(message_id: str, **usage: int) -> str:
    return json.dumps({"type": "assistant", "message": {"id": message_id, "usage": usage}})


def test_the_claude_transcript_is_found_by_session_and_cwd_and_summed_per_message(tmp_path):
    """One line per content block, the same id and usage on each: a message counts once.
    Input is everything sent — uncached, cache reads and cache writes."""
    config = tmp_path / "claude"
    session = "3f1c0b8e-0000-4000-8000-000000000001"
    directory = str(tmp_path / "code" / "widget")
    path = claude.transcript_path(session, directory, config)
    assert path.parent.name == re.sub(r"[^A-Za-z0-9]", "-", directory)  # /a/b_c -> -a-b-c
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"content": "hi"}}),
                _assistant(
                    "m1",
                    input_tokens=2,
                    cache_creation_input_tokens=500,
                    cache_read_input_tokens=1000,
                    output_tokens=40,
                ),
                _assistant(
                    "m1",
                    input_tokens=2,
                    cache_creation_input_tokens=500,
                    cache_read_input_tokens=1000,
                    output_tokens=40,
                ),
                "not json at all",
                _assistant("m2", input_tokens=10, cache_read_input_tokens=1500, output_tokens=60),
            ]
        )
    )
    report = claude.report(RunFacts(session, directory, "2026-09-11T10:00:00+00:00"), config)
    assert report is not None and report.session == session
    assert report.usage == Usage(
        input=12 + 500 + 2500,
        output=100,
        details={"uncached": 12, "cache_read": 2500, "cache_creation": 500},
    )
    assert report.usage.total == 3112


def test_a_missing_or_unreadable_claude_transcript_answers_none(tmp_path):
    facts = RunFacts("s", str(tmp_path), "2026-09-11T10:00:00+00:00")
    assert claude.report(facts, tmp_path / "nowhere") is None
    path = claude.transcript_path("s", str(tmp_path), tmp_path / "c")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"type": "assistant", "message": {"id": "m", "usage": "?"}}))
    assert claude.report(facts, tmp_path / "c") is None
    assert claude.report(RunFacts("", str(tmp_path), ""), tmp_path / "c") is None


def test_the_claude_config_dir_follows_the_persons_variable():
    assert claude.config_dir({"CLAUDE_CONFIG_DIR": "/home/me/.cc"}) == Path("/home/me/.cc")
    assert claude.config_dir({}) == Path.home() / ".claude"


# -- Codex: the rollout -----------------------------------------------------------------------


def _rollout(
    home: Path, when: datetime, thread: str, cwd: str, lines: list[dict[str, object]]
) -> Path:
    local = when.astimezone()
    folder = home / "sessions" / f"{local.year:04d}" / f"{local.month:02d}" / f"{local.day:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-{local.strftime('%Y-%m-%dT%H-%M-%S')}-{thread}.jsonl"
    meta = {
        "timestamp": when.isoformat(),
        "type": "session_meta",
        "payload": {"id": thread, "timestamp": when.isoformat(), "cwd": cwd},
    }
    path.write_text("\n".join(json.dumps(record) for record in [meta, *lines]))
    return path


def _token_count(**totals: int) -> dict[str, object]:
    return {
        "timestamp": "x",
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": totals}},
    }


def test_the_codex_run_is_the_earliest_rollout_started_in_its_directory_after_the_launch(
    tmp_path,
):
    """Codex mints its own thread id: the run is found by where it worked and when it
    began, the id is what `codex resume` takes, and the last cumulative count is the total."""
    home = tmp_path / "codex"
    tree = str(tmp_path / "widget" / ".dplanner-worktrees" / "s7-deploy")
    launched = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    earlier = "00000000-0000-4000-8000-00000000000a"
    ours = "00000000-0000-4000-8000-00000000000b"
    later = "00000000-0000-4000-8000-00000000000c"
    _rollout(home, launched - timedelta(hours=1), earlier, tree, [_token_count(input_tokens=1)])
    _rollout(
        home,
        launched + timedelta(seconds=30),
        ours,
        tree,
        [
            _token_count(input_tokens=100, output_tokens=10),
            {"type": "response_item", "payload": {}},
            _token_count(
                input_tokens=900,
                cached_input_tokens=600,
                cache_write_input_tokens=50,
                output_tokens=80,
                reasoning_output_tokens=20,
            ),
        ],
    )
    _rollout(home, launched + timedelta(hours=2), later, tree, [_token_count(input_tokens=5)])
    _rollout(home, launched + timedelta(minutes=1), "0" * 36, str(tmp_path / "elsewhere"), [])
    report = codex.report(RunFacts("", tree, launched.isoformat()), home)
    assert report is not None and report.session == ours
    assert report.usage == Usage(
        input=950, output=80, details={"cached_input": 600, "cache_write": 50, "reasoning": 20}
    )
    assert codex.report(RunFacts("", str(tmp_path / "nowhere"), launched.isoformat()), home) is None
    assert codex.report(RunFacts("", tree, "not a time"), home) is None


def test_a_codex_rollout_without_a_count_reports_the_session_and_no_usage(tmp_path):
    home = tmp_path / "codex"
    launched = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    thread = "00000000-0000-4000-8000-00000000000d"
    _rollout(home, launched, thread, str(tmp_path), [])
    report = codex.report(RunFacts("", str(tmp_path), launched.isoformat()), home)
    assert report is not None and report.session == thread and report.usage is None


def test_the_codex_home_follows_the_persons_variable():
    assert codex.codex_home({"CODEX_HOME": "/srv/codex"}) == Path("/srv/codex")
    assert codex.codex_home({}) == Path.home() / ".codex"


# -- OpenCode: the database -------------------------------------------------------------------


def _opencode_db(path: Path, rows: list[tuple[object, ...]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, time_created INTEGER,"
        " tokens_input INTEGER, tokens_output INTEGER, tokens_reasoning INTEGER,"
        " tokens_cache_read INTEGER, tokens_cache_write INTEGER)"
    )
    connection.executemany("INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def test_the_opencode_run_is_the_earliest_session_in_its_directory_after_the_launch(tmp_path):
    db = tmp_path / "opencode.db"
    launched = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    ms = int(launched.timestamp() * 1000)
    _opencode_db(
        db,
        [
            ("ses_old", "/w", ms - 3_600_000, 1, 1, 0, 0, 0),
            ("ses_ours", "/w", ms + 20_000, 100, 40, 10, 300, 50),
            ("ses_next", "/w", ms + 900_000, 5, 5, 0, 0, 0),
            ("ses_other", "/elsewhere", ms + 20_000, 7, 7, 0, 0, 0),
        ],
    )
    report = opencode.report(RunFacts("", "/w", launched.isoformat()), db)
    assert report is not None and report.session == "ses_ours"
    assert report.usage == Usage(
        input=450, output=50, details={"cache_read": 300, "cache_write": 50, "reasoning": 10}
    )
    by_id = opencode.report(RunFacts("ses_next", "/w", launched.isoformat()), db)
    assert (
        by_id is not None
        and by_id.session == "ses_next"
        and by_id.usage == Usage(5, 5, {"cache_read": 0, "cache_write": 0, "reasoning": 0})
    )
    assert opencode.report(RunFacts("", "/nowhere", launched.isoformat()), db) is None
    assert opencode.report(RunFacts("", "/w", launched.isoformat()), tmp_path / "none.db") is None


def test_an_opencode_database_this_build_cannot_read_answers_none(tmp_path):
    db = tmp_path / "opencode.db"
    sqlite3.connect(db).execute("CREATE TABLE session (id TEXT)").connection.close()
    assert opencode.report(RunFacts("", "/w", "2026-09-11T10:00:00+00:00"), db) is None


def test_the_opencode_database_path_follows_the_variables():
    assert opencode.database_path({"OPENCODE_DB": "/x/o.db"}) == Path("/x/o.db")
    assert opencode.database_path({"XDG_DATA_HOME": "/d"}) == Path("/d/opencode/opencode.db")
    assert opencode.database_path({}) == Path.home() / ".local/share/opencode/opencode.db"


# -- the multiplexer rows and the staged launch ------------------------------------------------


def fake_files(tmp_path: Path) -> LaunchFiles:
    return LaunchFiles(
        directory=tmp_path,
        prompt_file=tmp_path / "prompt.md",
        script=tmp_path / "run.sh",
        shell_file=tmp_path / "shell",
        exit_file=tmp_path / "exit",
        title="dplanner: S7 Deploy",
    )


def test_herdr_is_a_row_whose_template_is_two_calls(tmp_path):
    """herdr creates the workspace with one call and runs the script into its pane with
    another; the row writes both as one template and spawn stages them."""
    row = next(p for p in launcher.terminals_for("linux") if p.id == "herdr")
    assert row.multiplexer and row.probe == "herdr"
    command = launcher.resolve_command(
        row.command, fake_files(tmp_path), Path("/work"), platform="linux"
    )
    assert command is not None
    assert launcher.stages(command) == [
        [
            "herdr",
            "workspace",
            "create",
            "--cwd",
            "/work",
            "--label",
            "dplanner: S7 Deploy",
            "--no-focus",
        ],
        ["herdr", "pane", "run", "{pane}", "--command", str(tmp_path / "run.sh")],
    ]


def test_a_staged_spawn_feeds_the_pane_the_first_call_printed_into_the_second(
    tmp_path, monkeypatch
):
    calls: list[list[str]] = []

    def fake_run(argv, **_kw):
        calls.append(argv)
        out = '{"result": {"workspace": {"workspace_id": "w3"}, "root_pane": {"pane_id": "w3:p1"}}}'
        return subprocess.CompletedProcess(
            argv, 0, stdout=out if len(calls) == 1 else "", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    command = [
        "herdr",
        "workspace",
        "create",
        "&&",
        "herdr",
        "pane",
        "run",
        "{pane}",
        "--command",
        "x",
    ]
    assert launcher.spawn(command, tmp_path) == ""
    assert calls[1] == ["herdr", "pane", "run", "w3:p1", "--command", "x"]
    assert launcher.pane_from("%5\n") == "%5" and launcher.pane_from("") == ""


def test_a_stage_that_fails_is_a_reason_and_never_a_run(tmp_path, monkeypatch):
    def fake_run(argv, **_kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no herdr server running\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    reason = launcher.spawn(
        ["herdr", "workspace", "create", "&&", "herdr", "pane", "run"], tmp_path
    )
    assert reason == "herdr workspace create failed: no herdr server running"


def test_a_profiles_terminal_is_judged_by_its_rows_probe():
    none = lambda _n: None  # noqa: E731 - a stand-in for shutil.which
    herdr = next(p for p in launcher.terminals_for("linux") if p.id == "herdr")
    assert launcher.template_refusal(herdr.command, "linux", which=none, env={}) == (
        "herdr is not installed"
    )
    assert launcher.template_refusal(herdr.command, "linux", which=lambda _n: "/bin/herdr") == ""
    tmux = next(p for p in launcher.terminals_for("linux") if p.id == "tmux")
    assert "TMUX is not set" in launcher.template_refusal(tmux.command, "linux", which=none, env={})
    assert launcher.template_refusal("", "linux", which=none, env={}) == ""  # Automatic falls back.
    assert launcher.template_refusal("myterm -e {script}", "linux", which=none, env={}) == ""


def test_the_wrapper_records_the_multiplexers_own_names_for_the_pane(tmp_path):
    posix = launcher.prepare("p", tmp_path, platform="linux", harnesses=HARNESSES)
    script = posix.script.read_text()
    assert "herdr_workspace=%s" in script and '"$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID"' in script
    assert '"$WEZTERM_PANE"' in script
    windows = launcher.prepare("p", tmp_path, platform="win32", harnesses=HARNESSES)
    assert "'herdr_workspace=' + $env:HERDR_WORKSPACE_ID" in windows.script.read_text()


# -- profiles ---------------------------------------------------------------------------------


def test_the_two_old_settings_read_as_the_default_profile(app):
    from dplanner.framework.user_config import set_global
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
    from dplanner.modules.step_agent_instruction.profiles import (
        AGENT_COMMAND_KEY,
        LAUNCH_COMMAND_KEY,
        Profile,
        default_profile,
        read_profiles,
        write_profiles,
    )

    set_global(MODULE_ID, AGENT_COMMAND_KEY, "codex {prompt}")
    set_global(MODULE_ID, LAUNCH_COMMAND_KEY, "kitty {script}")
    assert read_profiles() == [Profile("Default", "codex {prompt}", "kitty {script}")]
    write_profiles([Profile("Mine", "", ""), Profile("Codex in herdr", "codex {prompt}", "h")])
    assert default_profile() == Profile("Mine", "", "")
    assert [p.name for p in read_profiles()] == ["Mine", "Codex in herdr"]


def test_the_settings_page_adds_removes_and_promotes_profiles(app):
    from dplanner.modules.step_agent_instruction.profiles import read_profiles
    from dplanner.modules.step_agent_instruction.settings_page import build_page

    page = build_page(None, platform="linux", harnesses=HARNESSES)
    listing = page.findChild(QListWidget, "AgentProfileList")
    add = page.findChild(QPushButton, "AgentProfileAdd")
    remove = page.findChild(QPushButton, "AgentProfileRemove")
    promote = page.findChild(QPushButton, "AgentProfileDefault")
    name = page.findChild(QLineEdit, "AgentProfileName")
    agent = page.findChild(QComboBox, "AgentPresetCombo")
    terminal = page.findChild(QLineEdit, "AgentLaunchCommandEdit")
    assert isinstance(listing, QListWidget) and isinstance(agent, QComboBox)
    assert isinstance(add, QPushButton) and isinstance(remove, QPushButton)
    assert isinstance(promote, QPushButton)
    assert isinstance(name, QLineEdit) and isinstance(terminal, QLineEdit)
    assert listing.count() == 1 and not remove.isEnabled() and not promote.isEnabled()

    add.click()  # A copy of the picked profile, named apart.
    assert [p.name for p in read_profiles()] == ["Default", "Default copy"]
    assert listing.currentRow() == 1 and remove.isEnabled() and promote.isEnabled()
    name.setText("Codex in herdr")
    name.editingFinished.emit()
    codex_row = next(i for i in range(agent.count()) if agent.itemText(i).startswith("Codex"))
    agent.setCurrentIndex(codex_row)
    agent.activated.emit(codex_row)
    terminal.setText(launcher.HERDR_COMMAND)
    terminal.editingFinished.emit()
    second = read_profiles()[1]
    assert (second.name, second.agent_command, second.launch_command) == (
        "Codex in herdr",
        "codex {prompt}",
        launcher.HERDR_COMMAND,
    )

    promote.click()
    assert [p.name for p in read_profiles()] == ["Codex in herdr", "Default"]
    assert listing.item(0).text() == "Codex in herdr (default)"
    listing.setCurrentRow(1)
    remove.click()
    assert [p.name for p in read_profiles()] == ["Codex in herdr"]
    page.deleteLater()


@pytest.fixture
def step(services, make_project):
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Step

    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    return step


def select(services, *steps):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, tuple(ContextNode(selection_uri("step", s.id)) for s in steps)
    )


def test_run_agent_with_lists_the_profiles_and_launches_through_the_picked_one(
    services, step, monkeypatch
):
    """The child menu is rebuilt on open with one entry per profile — the default marked,
    a profile whose terminal is missing greyed with that reason — and an entry runs the
    same launch as Run Agent, through that profile's agent and terminal."""
    from dplanner.modules.step_agent_instruction.profiles import Profile, write_profiles

    write_profiles(
        [
            Profile("Claude in Ghostty", "", "ghostty -e {script}"),
            Profile("Codex in herdr", "codex {prompt}", launcher.HERDR_COMMAND),
        ]
    )
    monkeypatch.setattr(
        launcher,
        "template_refusal",
        lambda t, *a, **k: "herdr is not installed" if t == launcher.HERDR_COMMAND else "",
    )
    select(services, step)
    menu = services.window.dynamic_menubar.data_menu("agent.run_with")
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Claude in Ghostty (default)", "Codex in herdr — herdr is not installed"]
    assert menu.actions()[0].isEnabled() and not menu.actions()[1].isEnabled()
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.enabled  # Run Agent… is the default profile, whose terminal is fine.

    monkeypatch.setattr(launcher, "template_refusal", lambda *a, **k: "")
    launched: list[tuple[list[str], str]] = []

    def fake_spawn(command, _cwd, **_kw):
        launched.append((command, ""))
        return ""

    monkeypatch.setattr(launcher, "spawn", fake_spawn)
    menu = services.window.dynamic_menubar.data_menu("agent.run_with")
    assert menu.actions()[1].isEnabled()
    menu.actions()[1].trigger()
    ((command, _),) = launched
    assert command[:3] == ["herdr", "workspace", "create"] and "&&" in command
    from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUN_ID

    runs = next(m for m in services.modules if m.id == RUN_ID).runs()
    assert [(run.harness, run.session) for run in runs] == [("codex", "")]  # Found afterwards.
    script = Path(runs[0].shell_file).parent.joinpath("run.sh").read_text()
    assert "\ncodex 'Read your briefing" in script


def test_run_agent_records_the_harness_and_the_session_it_named(services, step, monkeypatch):
    monkeypatch.setattr(launcher, "spawn", lambda *_a, **_k: "")
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUN_ID

    (run,) = next(m for m in services.modules if m.id == RUN_ID).runs()
    assert run.harness == "claude" and len(run.session) == 36


def test_a_multiplexer_that_refuses_is_no_shell_at_all(services, step, monkeypatch):
    """A workspace herdr could not create stamps nothing: the fallback hands the prompt over."""
    import dplanner.modules.step_agent_instruction.module as agent_module
    from dplanner.modules.step_agent_run.aspect import read as run_state

    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["herdr", "x", "&&", "y"])
    monkeypatch.setattr(launcher, "spawn", lambda *_a, **_k: "herdr workspace create failed: down")
    shown = []

    class SilentDialog:
        def __init__(self, *args, **kwargs):
            shown.append(args)

        def exec(self):
            return 0

    monkeypatch.setattr(agent_module, "PromptFallbackDialog", SilentDialog)
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    assert shown and run_state(services.document.step(step.id)) == ""
