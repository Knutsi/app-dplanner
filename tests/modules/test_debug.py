"""Debug ▸ Telemetry: the journal as a tab — newest first, narrowed by two switches, one
span in full below.

The tab polls the process's journal, the same one every other test in this worker writes
into, so each test clears it first and records exactly what it then asserts on.
"""

import pytest

from dplanner.framework.context import Context
from dplanner.modules.debug.telemetry_view import TELEMETRY_KIND, render_detail


@pytest.fixture
def journal(services):
    services.telemetry.clear()
    return services.telemetry


def rows(activity):
    tree = activity.tree
    return [
        tuple(tree.topLevelItem(row).text(column) for column in range(1, 5))
        for row in range(tree.topLevelItemCount())
    ]


def test_the_menu_opens_the_tab(services):
    services.actions.run("debug.telemetry", Context({}))
    activity = services.tabs.current_activity()
    assert activity is not None and activity.title == "Telemetry"


def test_rows_are_newest_first_with_kind_duration_and_outcome(services, journal):
    activity = services.tabs.open(TELEMETRY_KIND)
    journal.clear()  # Opening the tab may itself journal a slow slot; the rows are ours.
    journal.record("action", "steps.new", duration_ms=3.0)
    journal.record("command", "Add Step", duration_ms=45.0)
    journal.record("cli", "step add", exit_code=1, refused="no such project")
    activity.refresh()
    assert rows(activity) == [
        ("cli", "step add", "0.0 ms", "exit 1"),
        ("command", "Add Step", "45.0 ms", "ok"),
        ("action", "steps.new", "3.0 ms", "ok"),
    ]


def test_the_switches_narrow_to_slow_and_to_failures(services, journal):
    activity = services.tabs.open(TELEMETRY_KIND)
    journal.clear()
    journal.record("action", "quick", duration_ms=1.0)
    journal.record("action", "slow", duration_ms=80.0)
    journal.failure("broken", RuntimeError("boom"))
    journal.record("stall", "MainThread", duration_ms=400.0, samples=["File x.py, in sleep"])
    activity.slow_only.setChecked(True)
    assert [row[1] for row in rows(activity)] == ["MainThread", "slow"]
    activity.slow_only.setChecked(False)
    activity.failures_only.setChecked(True)
    assert [(row[1], row[3]) for row in rows(activity)] == [
        ("MainThread", "stalled"),
        ("broken", "failed"),
    ]


def test_selecting_a_row_shows_the_span_in_full(services, journal):
    activity = services.tabs.open(TELEMETRY_KIND)
    journal.clear()
    with journal.span("action", "steps.link", steps=2):
        journal.record("slot", "OrderActivity._refresh", duration_ms=30.0)
    try:
        raise ValueError("bad link")
    except ValueError as error:
        journal.failure("uncaught: ValueError", error)
    activity.refresh()
    activity.tree.topLevelItem(1).setSelected(True)  # The action: its child ran inside it.
    text = activity.detail.toPlainText()
    assert text.startswith("action steps.link —") and "steps: 2" in text
    assert "--- ran inside it ---" in text and "OrderActivity._refresh" in text
    activity.tree.clearSelection()
    activity.tree.topLevelItem(0).setSelected(True)  # The failure: its traceback.
    text = activity.detail.toPlainText()
    assert "ValueError: bad link" in text and "Traceback" in text


def test_a_stall_renders_its_samples_and_what_it_interrupted(journal):
    span = journal.record(
        "stall",
        "MainThread",
        duration_ms=1200.0,
        during=["action steps.delete"],
        samples=['  File "x.py", line 3, in sleep'],
    )
    text = render_detail(span, journal.recent())
    assert "1.20 s — stalled" in text
    assert "during: ['action steps.delete']" in text
    assert "--- stack sample 1 ---" in text and "in sleep" in text


def test_the_selection_survives_a_refresh(services, journal):
    activity = services.tabs.open(TELEMETRY_KIND)
    journal.clear()
    journal.record("action", "first", duration_ms=1.0)
    activity.refresh()
    activity.tree.topLevelItem(0).setSelected(True)
    journal.record("action", "second", duration_ms=1.0)
    activity.refresh()
    assert [item.text(2) for item in activity.tree.selectedItems()] == ["first"]


# -- Debug ▸ Design Example: the design system's living reference ------------------------


@pytest.fixture
def example(services, monkeypatch):
    """The modal, captured instead of run: exec() is patched, so the action returns at once
    and the test holds the dialog it built."""
    from dplanner.modules.debug.design_example import DesignExampleDialog

    opened = []

    def capture(self):
        opened.append(self)
        return 0

    monkeypatch.setattr(DesignExampleDialog, "exec", capture)
    services.actions.run("debug.design_example", Context({}))
    (dialog,) = opened
    return dialog


def test_the_menu_opens_the_design_example_modal_on_the_frame(example):
    from PySide6.QtWidgets import QPushButton

    assert example.windowTitle() == "Design Example"
    assert not example.footer.isHidden()
    primary = example.findChild(QPushButton, "PrimaryButton")
    assert primary is not None and primary.text() == "Apply" and primary.isDefault()
    assert [b.text() for b in example.footer_buttons()] == ["Apply", "Cancel", "Delete Sample"]
    assert example.table.rowCount() > 0 and example.table.columnSpan(0, 0) == 3


def test_every_signalling_state_is_on_the_modal(example):
    assert [line.tone() for line in example.lines] == ["info", "busy", "ok", "error"]
    assert example.problem.tone() == "error" and not example.problem.isHidden()
    assert example.progress.maximum() == 5 and not example.progress.isTextVisible()
    primary = example.primary()
    assert primary is not None and primary.isEnabled()
    example.refuse_switch.setChecked(True)
    assert not primary.isEnabled() and example.status.words() == "Pick a repository first"
    example.refuse_switch.setChecked(False)
    assert primary.isEnabled() and example.status.isHidden()


def test_the_demo_debouncer_drives_the_updating_indicator(services, example):
    services.debounce.set_immediate(False)
    try:
        assert example.updating.isHidden()
        example.change_button.click()
        assert not example.updating.isHidden()
        services.debounce.flush_all()
        assert example.updating.isHidden()
    finally:
        services.debounce.set_immediate(True)


def test_the_design_table_tab_opens_and_empty_trades_the_table_for_the_state(services):
    services.actions.run("debug.design_table", Context({}))
    activity = services.tabs.current_activity()
    assert activity is not None and activity.title == "Design Example"
    assert activity.table.rowCount() > 0 and activity.empty.isHidden()
    activity.empty_action.trigger()
    assert activity.table.rowCount() == 0 and activity.table.isHidden()
    assert not activity.empty.isHidden() and activity.empty.button is not None
    activity.empty.button.click()  # Add Rows: the toggle comes off and the rows come back.
    assert not activity.empty_action.isChecked() and activity.table.rowCount() > 0
    assert not activity.table.isHidden() and activity.empty.isHidden()


def test_the_filter_narrows_the_table_and_a_theme_change_repaints_it(services):
    from dplanner.modules.debug.design_example import DESIGN_TABLE_KIND

    activity = services.tabs.open(DESIGN_TABLE_KIND)
    everything = activity.table.rowCount()
    activity.filter.set_active({"milestone"})
    milestones = activity.table.rowCount()
    assert 0 < milestones < everything
    assert activity.filter.face.property("active") is True
    activity.filter.clear_button.click()
    assert activity.table.rowCount() == everything and not activity.filter.active()
    activity.group.setCurrentIndex(1)  # Flat: the headings go, the rows stay.
    assert activity.table.rowCount() == everything - 2
    services.theme.set_theme("light")  # A repaint, not a change: the count holds.
    assert activity.table.rowCount() == everything - 2


def test_the_strip_words_delete_with_the_count_and_add_appends(services):
    from PySide6.QtCore import QItemSelectionModel

    from dplanner.modules.debug.design_example import DESIGN_TABLE_KIND

    activity = services.tabs.open(DESIGN_TABLE_KIND)
    table = activity.table
    before = table.rowCount()
    delete = activity.delete_action
    assert not delete.isEnabled() and delete.text() == "Delete"
    # Through the selection model, never ``selectRow``: that asks the header which column
    # sits at x=0, and a table the suite has never laid out answers -1, so the call is a
    # silent no-op. Whether it has been laid out depends on what else the worker ran
    # first, which is what made this one fail under ``--dist load`` and pass alone.
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    table.selectionModel().select(table.model().index(1, 0), flags)
    assert delete.isEnabled() and delete.text() == "Delete Step" == delete.toolTip()
    table.selectionModel().select(table.model().index(2, 0), flags)
    assert delete.text() == "Delete 2 Steps"
    delete.trigger()
    assert table.rowCount() == before - 2 and not delete.isEnabled()
    activity.add_action.trigger()
    assert table.rowCount() == before - 1


def test_the_toolbars_example_shows_every_shape_a_strip_comes_in(services):
    """DESIGN.md's *Toolbars*, built rather than described: a developer bringing a surface
    up opens this beside their own."""
    from dplanner.framework.toolbar import _Group
    from dplanner.modules.debug.design_example import NO_ROOM, DesignExampleToolbars

    services.actions.run("debug.design_toolbars", services.context.current())
    (tab,) = [a for a in services.tabs.activities() if isinstance(a, DesignExampleToolbars)]

    # The flat strip has no bands; the palette has four, each named.
    assert tab.verbs.findChildren(_Group) == []
    named = [g.caption.text() for g in tab.palette.findChildren(_Group) if g.caption]
    assert named == ["Go", "Step", "Link", "Options"]

    # And the third strip is the same palette with no room, so a band can be seen folding.
    tab.folded._reflow()
    assert tab.folded.width() == NO_ROOM
    assert tab.folded.hidden_items() != []
    tab.folded._fill_more()
    listed = [a.text() for a in tab.folded._menu.actions() if not a.isSeparator()]
    assert "Isolate" in listed and all(
        not a.icon().isNull() for a in tab.folded._menu.actions() if not a.isSeparator()
    )

    # The dense strip answers a question rather than offering verbs: two of six are on.
    assert [v.text() for v in tab.dense.verbs() if v.isChecked()] == ["Milestone", "Agent"]


# -- Debug ▸ Windows Check -----------------------------------------------------------------
# The Windows half of this application cannot be run from here, so what is tested here is the
# menu entry's *refusal*: the machine's answer is computed once, at registration, and the
# state reads it. `scripts/windows_check.py` itself is driven by hand, not by the suite.


def test_the_windows_check_is_greyed_with_its_reason_off_omarchy(tmp_path):
    """Disabled with the reason in its own label, never hidden. Both preconditions say what
    is missing, because the entry is what tells a machine the capability exists at all."""
    from dplanner.modules.debug.windows_check import probe

    everywhere = lambda name: f"/usr/bin/{name}"  # noqa: E731
    nowhere = lambda _name: None  # noqa: E731

    absent = tmp_path / "windows_check.py"
    assert "source checkout" in probe(script=absent, which=everywhere).run_refusal

    harness = tmp_path / "present.py"
    harness.write_text("", encoding="utf-8")
    assert "omarchy-windows-vm" in probe(script=harness, which=nowhere).run_refusal

    here = probe(script=harness, which=everywhere)
    assert here.run_refusal == "" and here.script == harness


def test_watching_the_desktop_needs_only_the_vm(tmp_path):
    """A build with no scripts/ can still open the viewer of a VM that is running, so the two
    verbs derive different refusals from the same two facts — refusing the cheaper one would
    be refusing something that works."""
    from dplanner.modules.debug.windows_check import probe

    no_harness = probe(script=tmp_path / "gone.py", which=lambda name: f"/usr/bin/{name}")
    assert no_harness.run_refusal and no_harness.watch_refusal == ""
    assert probe(script=tmp_path / "gone.py", which=lambda _n: None).watch_refusal


def test_the_windows_check_builds_no_command_for_a_refused_machine(tmp_path):
    """A refused check has no script, so asking for its command is the error — rather than a
    command naming None that fails somewhere further away."""
    import pytest as _pytest

    from dplanner.modules.debug.windows_check import command, probe

    refused = probe(script=tmp_path / "missing.py", which=lambda name: f"/usr/bin/{name}")
    with _pytest.raises(ValueError, match="source checkout"):
        command(refused, "python")

    harness = tmp_path / "present.py"
    harness.write_text("", encoding="utf-8")
    ready = probe(script=harness, which=lambda name: f"/usr/bin/{name}")
    assert command(ready, "python") == ["python", str(harness), "all"]


def test_both_windows_entries_are_registered_in_the_debug_menu(services):
    for action_id in ("debug.windows_check", "debug.windows_desktop"):
        spec = services.actions.spec(action_id)
        assert spec.menu == "Debug" and spec.group == "windows"
        state = spec.state(Context({}))
        # On this machine each is either runnable or greyed *with a reason in the label* —
        # never hidden, and never greyed silently.
        assert state.visible
        assert state.enabled or (state.label and "—" in state.label)


def test_watching_the_desktop_runs_omarchys_launcher_and_keeps_the_vm_alive(services, monkeypatch):
    """Delegated to omarchy-windows-vm, which knows the credentials, the scale and the client.
    `--keep-alive` is the one flag that matters: without it the launcher stops the VM when
    the RDP window closes, and it is the developer's own VM."""
    from dplanner.modules.debug import module as debug_module

    launched: list[tuple[str, ...]] = []
    monkeypatch.setattr(debug_module, "launch_desktop", launched.append)
    # The spec's body directly rather than through `run`, which honours the state gate: what
    # is under test is what the verb does, on every machine, not whether this one has a VM.
    services.actions.spec("debug.windows_desktop").run(Context({}))
    assert launched == [("omarchy-windows-vm", "launch", "--keep-alive")]
