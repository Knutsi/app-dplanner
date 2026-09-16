"""The shell behind a launch: how its end is noticed, how its window is found again, and
what the window does about both.

The wrapper script reports through two files beside the prompt; these drive the reader
(``runs.settle``), the per-platform focus provider (``terminal.focus``) with a fake
runner, and the module end to end — a launch tracked, an exit clearing the chip, the
verbs greyed with their reasons.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_agent_run import aspect, terminal
from dplanner.modules.step_agent_run.runs import AgentRun, describe, new_run, read_shell, settle

# -- settling a run, with no application at all -------------------------------------------------


@pytest.fixture
def run(tmp_path) -> AgentRun:
    return new_run("step-1", str(tmp_path / "shell"), str(tmp_path / "exit"))


def test_a_fresh_run_is_live_until_the_script_says_otherwise(run):
    assert run.live
    assert settle(run, alive=lambda _pid: True) is run


def test_exit_zero_is_finished_and_anything_else_failed(run, tmp_path):
    (tmp_path / "exit").write_text("0\n")
    done = settle(run)
    assert done.outcome == "finished" and done.code == 0 and done.ended
    assert describe(done, "") == "finished"

    (tmp_path / "exit").write_text("2\r\n")  # cmd's line ending.
    failed = settle(run)
    assert failed.outcome == "failed" and failed.code == 2
    assert describe(failed, "") == "failed (exit 2)"


def test_the_traps_word_means_the_terminal_was_closed(run, tmp_path):
    (tmp_path / "exit").write_text("closed\n")
    assert settle(run).outcome == "closed"


def test_a_dead_shell_without_an_exit_is_closed_too(run, tmp_path):
    """A window shut hard enough that the trap never ran: the pid the script recorded
    is gone, and that is the answer."""
    (tmp_path / "shell").write_text("tty=/dev/pts/3\npid=4242\npane=\nprogram=ghostty\n")
    assert settle(run, alive=lambda pid: pid != 4242).outcome == "closed"
    assert settle(run, alive=lambda _pid: True).live


def test_a_vanished_run_directory_is_lost(tmp_path):
    gone = tmp_path / "gone"
    run = new_run("s", str(gone / "shell"), str(gone / "exit"))
    lost = settle(run)
    assert lost.outcome == "lost"
    assert "run directory" in describe(lost, "")


def test_the_shell_facts_read_back_as_written(run, tmp_path):
    (tmp_path / "shell").write_text(
        "tty=/dev/ttys003\npid=77\npane=%5\nprogram=Apple_Terminal\ntitle=dplanner: x\n"
    )
    assert read_shell(run) == {
        "tty": "/dev/ttys003",
        "pid": "77",
        "pane": "%5",
        "program": "Apple_Terminal",
        "title": "dplanner: x",
    }
    assert read_shell(new_run("s", str(tmp_path / "none"), "")) == {}


def test_a_run_round_trips_through_the_user_store_shape(run):
    assert AgentRun.from_json(run.to_json()) == run
    assert AgentRun.from_json({"step": "s"}) is None  # A row this build cannot read.
    assert AgentRun.from_json("nonsense") is None
    assert AgentRun.from_json(replace(run, prompt_chars=18_412).to_json()) == replace(
        run, prompt_chars=18_412
    )
    # A row from before the size was measured, or one with nonsense in its place, reads as
    # "nobody measured" rather than refusing the whole run.
    unmeasured = AgentRun.from_json({**run.to_json(), "prompt_chars": "many"})
    assert unmeasured is not None and unmeasured.prompt_chars == 0


def test_the_live_state_is_what_a_row_says(run):
    assert describe(run, "needs-input") == "needs input"
    assert describe(run, "") == "launched"


# -- finding the window again -----------------------------------------------------------------


class Runner:
    """Records every command and answers from a table keyed by the first two words."""

    def __init__(self, answers=None):
        self.calls: list[list[str]] = []
        self.answers = answers or {}

    def __call__(self, argv):
        self.calls.append(argv)
        return self.answers.get(tuple(argv[:2]), (1, ""))


def test_a_tmux_pane_is_selected_wherever_it_is():
    runner = Runner({("tmux", "select-window"): (0, "")})
    reason = terminal.focus(
        {"pane": "%5", "program": "tmux"},
        platform="linux",
        which=lambda n: "/usr/bin/tmux" if n == "tmux" else None,
        run=runner,
    )
    assert reason == ""
    assert runner.calls[:2] == [
        ["tmux", "select-window", "-t", "%5"],
        ["tmux", "select-pane", "-t", "%5"],
    ]


def test_macos_asks_terminal_for_the_tab_on_the_shells_tty():
    runner = Runner({("osascript", "-e"): (0, "ok\n")})
    facts = {"tty": "/dev/ttys003", "program": "Apple_Terminal", "pid": "1"}
    assert terminal.focus(facts, platform="darwin", which=lambda _n: None, run=runner) == ""
    script = runner.calls[0][2]
    assert 'tell application "Terminal"' in script and 'tty of t is "/dev/ttys003"' in script


def test_macos_asks_iterm_through_its_sessions():
    runner = Runner({("osascript", "-e"): (0, "ok\n")})
    facts = {"tty": "/dev/ttys004", "program": "iTerm.app"}
    assert terminal.focus(facts, platform="darwin", which=lambda _n: None, run=runner) == ""
    assert 'tell application "iTerm2"' in runner.calls[0][2]


def test_macos_activates_an_unscriptable_terminal_by_name():
    """Ghostty has no window scripting: the application coming to the front is what can
    honestly be done, and it is done."""
    runner = Runner({("open", "-a"): (0, "")})
    assert terminal.focus({"program": "ghostty"}, platform="darwin", run=runner) == ""
    assert runner.calls == [["open", "-a", "ghostty"]]


def test_a_tab_that_is_gone_is_a_reason_not_an_error():
    runner = Runner({("osascript", "-e"): (0, "none\n")})
    facts = {"tty": "/dev/ttys003", "program": "Apple_Terminal"}
    assert terminal.focus(facts, platform="darwin", run=runner) == terminal.NOT_FOUND


def test_linux_walks_the_shells_ancestors_to_the_window_owner():
    """kitty, Alacritty, xterm and Ghostty own their windows, so the terminal is an
    ancestor of the wrapper shell — the pid the script recorded — and xdotool finds the
    window by that pid, whatever the agent has since retitled it."""
    stats = {500: "500 (sh) S 400 1 1", 400: "400 (kitty) S 1 1 1"}
    runner = Runner({("xdotool", "search"): (0, "")})

    def search(argv):
        runner.calls.append(argv)
        if argv[:2] == ["xdotool", "search"] and argv[-1] == "400":
            return 0, "12345\n"
        return runner.answers.get(tuple(argv[:2]), (1, ""))

    reason = terminal.focus(
        {"pid": "500", "title": "dplanner: x"},
        platform="linux",
        which=lambda n: "/usr/bin/xdotool" if n == "xdotool" else None,
        run=search,
        read_stat=lambda pid: stats.get(pid),
    )
    assert reason == ""
    assert runner.calls[-1] == ["xdotool", "windowactivate", "12345"]
    assert terminal.ancestors(500, stats.get) == [500, 400]


def test_linux_falls_back_to_the_title_with_wmctrl():
    runner = Runner({("wmctrl", "-a"): (0, "")})
    reason = terminal.focus(
        {"pid": "9", "title": "dplanner: Deploy"},
        platform="linux",
        which=lambda n: "/usr/bin/wmctrl" if n == "wmctrl" else None,
        run=runner,
        read_stat=lambda _pid: None,
    )
    assert reason == ""
    assert runner.calls == [["wmctrl", "-a", "dplanner: Deploy"]]


def test_a_desktop_without_a_window_tool_is_named_as_the_reason():
    assert "xdotool or wmctrl" in terminal.support_reason("linux", which=lambda _n: None)
    assert terminal.support_reason("darwin", which=lambda _n: None) == ""
    assert terminal.focus({"pid": "1"}, platform="linux", which=lambda _n: None) != ""


def test_a_tmux_pane_is_reachable_where_a_bare_window_is_not():
    """Availability is the run's, not the machine's: ``focus`` selects a pane before it
    asks the desktop for a window, so ``focus_reason`` answers in the same order."""

    def tmux_only(name):
        return "/usr/bin/tmux" if name == "tmux" else None

    assert terminal.focus_reason({"pane": "%5"}, platform="linux", which=tmux_only) == ""
    assert "xdotool or wmctrl" in terminal.focus_reason({}, platform="linux", which=tmux_only)
    assert "xdotool or wmctrl" in terminal.focus_reason(
        {"pane": "%5"}, platform="linux", which=lambda _n: None
    )


def test_windows_activates_by_the_powershell_pid_then_the_title():
    runner = Runner({("powershell", "-NoProfile"): (0, "True\r\n")})
    facts = {"pid": "321", "title": "dplanner: Deploy"}
    assert terminal.focus(facts, platform="win32", run=runner) == ""
    assert "AppActivate(321)" in runner.calls[0][-1]

    saying_no = Runner({("powershell", "-NoProfile"): (0, "False\r\n")})
    assert terminal.focus(facts, platform="win32", run=saying_no) == terminal.NOT_FOUND
    assert "AppActivate('dplanner: Deploy')" in saying_no.calls[1][-1]


# -- the module ------------------------------------------------------------------------------------


def module(services):
    return next(m for m in services.modules if m.id == aspect.MODULE_ID)


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.autosave.flush_now()
    return step


def select(services, step):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


def test_a_tracked_launch_stamps_the_step_and_shows_in_the_status_bar(services, step, tmp_path):
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    assert aspect.read(services.document.step(step.id)) == "launched"
    assert [run.step_id for run in runs.runs()] == [step.id]
    assert runs._button.isVisibleTo(runs._button.parentWidget()) and "Deploy" in runs._button.text()
    assert runs._timer.isActive()


def test_the_shells_exit_clears_the_chip_and_stops_the_clock(services, step, tmp_path):
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    services.autosave.flush_now()
    (tmp_path / "exit").write_text("0\n")
    runs.check()
    assert aspect.read(services.document.step(step.id)) == ""
    assert runs.runs()[0].outcome == "finished"
    assert not runs._timer.isActive()
    assert "finished" in runs._button.text()


def test_an_agent_that_cleared_its_own_state_is_not_written_again(services, step, tmp_path):
    """The protocol is `agent-state clear` from the shell; the window's clear is only for
    the run that ended without it."""
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    SetModuleDataCommand(step.id, aspect.MODULE_ID, {}).redo(services.document)
    services.autosave.flush_now()
    assert not aspect.record_exit(services.document, step.id)
    (tmp_path / "exit").write_text("1\n")
    runs.check()
    assert runs.runs()[0].outcome == "failed"


def test_an_exit_is_never_written_over_another_writer(services, step, tmp_path, monkeypatch):
    """The agent's last `dplanner` call and its exit land within a tick of each other. The
    store answers "changed underneath", the tick stands down, and the reload that follows
    rebuilds the module — which re-adopts the run from the user's store."""
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    services.autosave.flush_now()
    (tmp_path / "exit").write_text("0\n")
    monkeypatch.setattr(services.repo, "changed_underneath", lambda: True)
    runs.check()
    assert aspect.read(services.document.step(step.id)) == "launched"
    assert runs.runs()[0].live

    from dplanner.framework.user_config import get_global

    stored = get_global(aspect.MODULE_ID, "runs")
    assert [row["step"] for row in stored] == [step.id]


def test_the_verbs_are_greyed_with_their_reasons(services, step, tmp_path):
    select(services, step)
    context = services.context.current()
    show = services.actions.spec("agent.show_terminal").state(context)
    assert show.visible and not show.enabled and "no agent shell" in (show.label or "")
    clear = services.actions.spec("agent.clear_run").state(context)
    assert not clear.enabled and "no agent run" in (clear.label or "")

    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    context = services.context.current()
    assert services.actions.spec("agent.clear_run").state(context).enabled
    show = services.actions.spec("agent.show_terminal").state(context)
    # This container has no desktop; the label says what the desktop would need.
    assert show.enabled == (terminal.support_reason() == "")


def test_clear_agent_run_is_an_undoable_edit(services, step, tmp_path):
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    select(services, step)
    services.actions.run("agent.clear_run", services.context.current())
    assert aspect.read(services.document.step(step.id)) == ""
    services.undo.undo()
    assert aspect.read(services.document.step(step.id)) == "launched"


def test_run_agent_hands_the_shell_to_the_tracker(services, step, monkeypatch):
    """End to end through the real action: the wrapper's two files are what gets tracked."""
    from dplanner.modules.step_agent_instruction import launcher
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, write_state

    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write_state(True)))
    services.document.set_text(step.id, "step_description", "Ship it.")
    spawned: list[list[str]] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["true"])
    monkeypatch.setattr(launcher, "spawn", lambda command, _workdir, **_kw: spawned.append(command))
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    assert spawned == [["true"]]
    (tracked,) = module(services).runs()
    assert tracked.step_id == step.id and tracked.live
    assert Path(tracked.shell_file).name == "shell" and Path(tracked.exit_file).name == "exit"
    assert Path(tracked.exit_file).parent.name.startswith("dplanner-agent-")
    assert aspect.read(services.document.step(step.id)) == "launched"
    # And what it was handed: the briefing as it actually reached prompt.md.
    briefing = Path(tracked.shell_file).parent / "prompt.md"
    assert tracked.prompt_chars == len(briefing.read_text()) > 0


def test_a_launch_is_a_span_saying_what_it_handed_over(services, step, monkeypatch):
    """One gesture can open a shell per chosen step, so the size cannot be a detail on the
    action's own span — each launch opens one of its own under it."""
    from dplanner.modules.step_agent_instruction import launcher
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, write_state

    journal = services.telemetry  # The build's journal is the process's.
    journal.clear()
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write_state(True)))
    services.document.set_text(step.id, "step_description", "Ship it.")
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["true"])
    monkeypatch.setattr(launcher, "spawn", lambda *_a, **_kw: None)
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    (tracked,) = module(services).runs()
    launch = next(span for span in journal.recent() if span.name == "agent.launch")
    assert launch.kind == "action"
    assert launch.detail["prompt_chars"] == tracked.prompt_chars
    assert launch.detail["step"] == "S1"
    # Under the action the gesture ran, so the journal says which verb opened it.
    action = next(span for span in journal.recent() if span.name == "agent.run")
    assert launch.parent == action.span_id


def test_the_browser_lists_runs_with_their_outcome(services, step, tmp_path):
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    runs._open_browser()
    runs._browser.show_ended.setChecked(True)  # So the row is still listed once it ends.
    rows = runs._browser.rows()
    assert len(rows) == 1
    (row,) = rows
    assert row.title.text() == "Deploy"
    assert row.status.words().startswith("launched · since") and row.status.tone() == "busy"
    assert row.terminal_button.isVisibleTo(row)

    (tmp_path / "exit").write_text("3\n")
    runs.check()
    assert row.status.words().startswith("failed (exit 3) · at")
    assert row.status.tone() == "error"
    assert not row.terminal_button.isVisibleTo(row)
    assert runs._browser.clear_button.isEnabled()
    runs._clear_ended()
    assert runs.runs() == [] and runs._browser.empty.isVisibleTo(runs._browser)
    assert not runs._browser.clear_button.isEnabled()


def test_the_browser_lists_the_newest_run_first(services, step, tmp_path):
    """The one just launched is what a person came to look at, so it is the first row —
    and an ended run sorts by the stamp its own line shows, the time it ended."""
    runs = module(services)
    for index in range(3):
        directory = tmp_path / f"run-{index}"
        directory.mkdir()
        runs.track(step.id, str(directory / "shell"), str(directory / "exit"))
    # Stamps a second apart, in launch order, and the middle run ended last of the two.
    runs._runs = [
        replace(run, launched=f"2026-09-16T10:0{index}:00+00:00")
        for index, run in enumerate(runs._runs)
    ]
    runs._open_browser()
    assert [row.run.key for row in runs._browser.rows()] == [
        str(tmp_path / "run-2"),
        str(tmp_path / "run-1"),
        str(tmp_path / "run-0"),
    ]

    runs._runs[0] = replace(runs._runs[0], outcome="finished", ended="2026-09-16T11:00:00+00:00")
    runs._runs[1] = replace(runs._runs[1], outcome="failed", ended="2026-09-16T12:00:00+00:00")
    runs._browser.show_ended.setChecked(True)
    assert [row.run.key for row in runs._browser.rows()] == [
        str(tmp_path / "run-2"),  # The live one, whenever it started.
        str(tmp_path / "run-1"),  # Then the ended ones, the last to end first.
        str(tmp_path / "run-0"),
    ]


def test_the_browser_keeps_the_ended_runs_off_screen_until_they_are_asked_for(
    services, step, tmp_path
):
    """The default list is what is happening now: an ended run leaves it, the footer still
    counts it, and the empty state says where it went. Clear ended waits for the switch —
    a verb that deletes what the list is not showing acts blind."""
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    runs._open_browser()
    browser = runs._browser
    assert not browser.show_ended.isChecked()  # The default: the ended ones are not listed.

    (tmp_path / "exit").write_text("0\n")
    runs.check()
    assert browser.rows() == [] and runs.runs()[0].outcome == "finished"
    assert browser.status.words() == "1 ended"
    assert browser.empty.text() == "No agent is running — tick Show ended for the run that ended."
    assert not browser.clear_button.isEnabled()
    assert "Show ended" in browser.clear_button.toolTip()

    browser.show_ended.setChecked(True)
    assert [row.title.text() for row in browser.rows()] == ["Deploy"]
    assert not browser.empty.isVisibleTo(browser)
    assert browser.clear_button.isEnabled() and browser.clear_button.toolTip() == ""

    browser.clear_button.click()
    assert runs.runs() == []
    assert browser.empty.text() == "No agent has been launched from this window."


def test_the_browser_greys_show_terminal_per_run(services, step, tmp_path, monkeypatch):
    """A run in a tmux pane keeps its button on a desktop that cannot raise windows —
    each row asks about its own shell, never about the machine in general."""
    monkeypatch.setattr(
        terminal, "focus_reason", lambda facts, **_kw: "" if facts.get("pane") else "no way in"
    )
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    (tmp_path / "shell").write_text("pane=%5\n")
    other = tmp_path / "other"
    other.mkdir()
    runs.track(step.id, str(other / "shell"), str(other / "exit"))
    runs._open_browser()
    in_tmux, bare = runs._browser.row(str(tmp_path)), runs._browser.row(str(other))
    assert in_tmux.terminal_button.isEnabled()
    assert not bare.terminal_button.isEnabled()
    assert bare.terminal_button.toolTip() == "no way in"


def test_tools_agent_list_offers_the_live_runs(services, step, tmp_path, monkeypatch):
    """Tools ▸ Agent List: a row per live run raising its terminal, greyed per run with
    the reason, the browser at the bottom — and rebuilt every time the menu opens."""
    menubar = services.window.dynamic_menubar
    listing = menubar.data_menu("agent_run.list")
    labels = [a.text().replace("&", "") for a in listing.actions() if not a.isSeparator()]
    assert labels == ["No agents running from this window", "Agents…"]
    assert not listing.actions()[0].isEnabled()

    monkeypatch.setattr(
        terminal, "focus_reason", lambda facts, **_kw: "" if facts.get("pane") else "no way in"
    )
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    row = menubar.data_menu("agent_run.list").actions()[0]
    assert row.text() == "Agent on “Deploy” — no way in" and not row.isEnabled()

    (tmp_path / "shell").write_text("pane=%5\n")
    row = menubar.data_menu("agent_run.list").actions()[0]
    assert row.text() == "Agent on “Deploy”" and row.isEnabled()
    focused = []

    def focus(facts, **_kw):
        focused.append(facts)
        return ""

    monkeypatch.setattr(terminal, "focus", focus)
    row.trigger()
    assert focused == [{"pane": "%5"}]

    (tmp_path / "exit").write_text("0\n")
    runs.check()
    ended = menubar.data_menu("agent_run.list").actions()[0]
    assert ended.text() == "No agents running from this window"


def test_needs_input_reaches_the_canvas_as_an_attention_chip(services, step):
    tab = services.tabs.open("project", services.document.project_of(step.id).id)
    SetModuleDataCommand(step.id, aspect.MODULE_ID, aspect.write("needs-input")).redo(
        services.document
    )
    accent = tab._scene._nodes[step.id]._accent
    assert (accent.chip_text, accent.chip_tone) == ("needs input", "attention")


def test_the_tick_asks_the_store_only_once_a_run_has_ended(services, step, tmp_path, monkeypatch):
    """`changed_underneath` is a walk over every plan file on the GUI thread; asked every
    two seconds while an agent ran, it stalled a large library's window for as long as
    the walk took. A tick with nothing ended never asks."""
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    services.autosave.flush_now()
    asked: list[int] = []

    def changed_underneath() -> bool:
        asked.append(1)
        return False

    monkeypatch.setattr(services.repo, "changed_underneath", changed_underneath)
    runs.check()
    runs.check()
    assert asked == []
    assert runs.runs()[0].live
    (tmp_path / "exit").write_text("0\n")
    runs.check()
    assert asked == [1]
    assert runs.runs()[0].outcome == "finished"


def test_an_ended_run_shows_the_command_that_picks_it_up_again(services, step, tmp_path):
    """The wrapper records the resume command beside the shell's facts once the agent is
    in place; the browser shows it under an ended row, never under a live one."""
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    (tmp_path / "shell").write_text(
        "pid=1\nsession=7a1e4c2e-0000-4000-8000-000000000003\ndir=/repo/.dplanner-worktrees/s7\n"
        'resume=cd "/repo/.dplanner-worktrees/s7" && claude --resume'
        " 7a1e4c2e-0000-4000-8000-000000000003\n"
    )
    runs._open_browser()
    runs._browser.show_ended.setChecked(True)  # The same row, before and after it ends.
    (row,) = runs._browser.rows()
    assert not row.note.isVisibleTo(row)

    (tmp_path / "exit").write_text("143\n")
    runs.check()
    assert row.status.words().startswith("failed (exit 143)")
    assert row.note.isVisibleTo(row)
    assert row.note.text() == (
        'Pick it up again: cd "/repo/.dplanner-worktrees/s7" && claude --resume'
        " 7a1e4c2e-0000-4000-8000-000000000003"
    )


def test_an_ended_run_without_a_resume_shows_none(services, step, tmp_path):
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    (tmp_path / "shell").write_text("pid=1\nsession=\ndir=/repo\n")
    (tmp_path / "exit").write_text("1\n")
    runs.check()
    runs._open_browser()
    runs._browser.show_ended.setChecked(True)
    (row,) = runs._browser.rows()
    assert not row.note.isVisibleTo(row) and row.note.text() == ""
