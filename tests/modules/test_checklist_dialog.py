"""*Tools ▸ Setup Checklist…*: the rows, the remedies, and what opens it at start.

Every probe here is a fake. The registry and the report are tested in
``tests/cli/test_checklist.py`` and each module's own rows in
``tests/modules/test_module_checks.py``; this file is about the surface — that a row says
what its probe found, that the work happens off the GUI thread, that a remedy runs the
owning module's own verb, and that the machine is greeted exactly once.
"""

import time

import pytest

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, MenuStructure
from dplanner.menus import MENU_STRUCTURE
from dplanner.modules.checklist import module as checklist_module
from dplanner.modules.checklist.dialog import AT_START, CHECKING, GREETING, ChecklistDialog
from dplanner.modules.checklist.module import ChecklistDeps, ChecklistModule, at_start, greeted


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the sweep never settled"
        app.processEvents()
        time.sleep(0.01)


def check(check_id, group="Services", *, ok=True, detail="", required=False, remedy=None):
    return MachineCheck(
        id=check_id,
        group=group,
        label=check_id,
        probe=lambda: Reading(ok=ok, detail=detail),
        remedy=remedy,
        required=required,
    )


INSTALL = Remedy(
    words="Install or update DPlanner on this machine.",
    command="dplanner install all",
    action="install.dplanner",
    verb="Install…",
)


@pytest.fixture
def sample():
    return [
        check(
            "install.skill",
            "DPlanner",
            ok=False,
            detail="not installed",
            required=True,
            remedy=INSTALL,
        ),
        check("git.installed", "Git and GitHub", ok=True, detail="git 2.51.0", required=True),
        check(
            "github.gh",
            "Git and GitHub",
            ok=False,
            detail="not on PATH",
            remedy=Remedy(words="Install it from cli.github.com"),
        ),
    ]


@pytest.fixture
def settled(app, services, sample):
    """A dialog whose first sweep has landed, with the remedies it ran recorded."""
    ran: list[str] = []
    dialog = ChecklistDialog(sample, services.tasks, ran.append, services.window)
    wait_for(app, lambda: dialog.status.tone() != "busy")
    return dialog, ran


def words(dialog):
    """What each row says, before the width cuts it — eliding is tested on its own."""
    return {
        row.check.id: " — ".join(p for p in (row.said, row.why_words) if p) for row in dialog.rows
    }


# -- the rows ----------------------------------------------------------------------------


def test_a_row_says_where_its_check_stands_in_the_tone_the_row_earns(settled):
    dialog, _ran = settled

    said = words(dialog)
    assert said["git.installed"] == "git.installed — git 2.51.0"
    assert "not installed" in said["install.skill"]
    tones = {row.check.id: row.line.tone() for row in dialog.rows}
    # A failing required row is the error tone; a failing recommendation is information,
    # because advice shouted in red is not advice.
    assert tones == {"install.skill": "error", "git.installed": "ok", "github.gh": "info"}


def test_a_failing_row_carries_its_remedy_in_its_words(settled):
    dialog, _ran = settled

    assert "Install it from cli.github.com" in words(dialog)["github.gh"]


def test_the_rows_are_grouped_and_the_required_lead_their_group(settled):
    dialog, _ran = settled

    assert [row.check.id for row in dialog.rows] == [
        "install.skill",
        "git.installed",
        "github.gh",
    ]


def test_the_footer_counts_what_needs_attention(settled):
    dialog, _ran = settled

    assert dialog.status.words() == "1 required item needs attention; 1 suggestion."
    assert dialog.status.tone() == "error"


def test_a_machine_with_everything_says_so(app, services):
    dialog = ChecklistDialog(
        [check("git.installed", "Git and GitHub", ok=True)], services.tasks, lambda _id: None, None
    )
    wait_for(app, lambda: dialog.status.tone() != "busy")

    assert dialog.status.words() == "This machine has everything."
    assert dialog.status.tone() == "ok"


def test_a_row_too_narrow_for_its_words_cuts_them_rather_than_widening_the_dialog(settled):
    """A row that wrapped would be a height that depends on a width inside a scroll area,
    which is the shape that took the process down once (CLAUDE.md's *Checks*)."""
    dialog, _ran = settled
    row = dialog.rows[0]
    row.resize(120, row.height())

    assert row.line.words() != row.said
    assert row.line.words().endswith("…")
    assert row.said in row.toolTip()  # Nothing is lost: the full words are the tooltip.


# -- the work -----------------------------------------------------------------------------


def test_every_row_says_it_is_being_checked_before_anything_has_answered(services, sample):
    dialog = ChecklistDialog(sample, services.tasks, lambda _id: None, services.window)

    assert all(CHECKING in line for line in words(dialog).values())
    assert all(not row.why_words for row in dialog.rows)  # No remedy for an unasked question.
    assert all(row.line.tone() == "busy" for row in dialog.rows)
    assert not dialog.recheck.isEnabled()
    assert dialog.spinner.is_spinning()


def test_the_probes_run_off_the_gui_thread(app, services):
    threads: list[str] = []

    def probe():
        import threading

        threads.append(threading.current_thread().name)
        return Reading(ok=True)

    dialog = ChecklistDialog(
        [MachineCheck(id="slow", group="Services", label="slow", probe=probe)],
        services.tasks,
        lambda _id: None,
        services.window,
    )
    wait_for(app, lambda: dialog.status.tone() != "busy")

    assert threads and "MainThread" not in threads
    assert dialog.spinner.is_spinning() is False  # The glyph comes back when the work ends.


def test_re_check_asks_again(app, services):
    answers = iter(
        [Reading(ok=False, detail="not on PATH"), Reading(ok=True, detail="/usr/bin/gh")]
    )
    dialog = ChecklistDialog(
        [
            MachineCheck(
                id="github.gh", group="Git and GitHub", label="gh", probe=lambda: next(answers)
            )
        ],
        services.tasks,
        lambda _id: None,
        services.window,
    )
    wait_for(app, lambda: dialog.status.tone() != "busy")
    assert "not on PATH" in words(dialog)["github.gh"]

    dialog.recheck.click()
    wait_for(app, lambda: "usr" in words(dialog)["github.gh"])

    assert dialog.rows[0].line.tone() == "ok"


# -- remedies ------------------------------------------------------------------------------


def test_a_remedy_that_names_an_action_is_a_button_on_its_row(settled):
    dialog, ran = settled
    by_id = {row.check.id: row for row in dialog.rows}

    assert by_id["install.skill"].button is not None
    assert by_id["install.skill"].button.text() == "Install…"
    # A remedy nobody can run for you is words, not a dead button.
    assert by_id["github.gh"].button is None

    button = by_id["install.skill"].button
    assert button is not None and not button.isHidden()
    button.click()
    assert ran == ["install.dplanner"]


def test_a_row_that_is_well_keeps_its_buttons_room_rather_than_its_button(app, services):
    dialog = ChecklistDialog(
        [check("install.skill", "DPlanner", ok=True, detail="current", remedy=INSTALL)],
        services.tasks,
        lambda _id: None,
        services.window,
    )
    wait_for(app, lambda: dialog.status.tone() != "busy")

    button = dialog.rows[0].button
    assert button is not None
    # Hidden, but its room is kept: a fixed row and a failing one are the same shape.
    assert button.isHidden()
    assert button.sizePolicy().retainSizeWhenHidden()


def test_running_a_remedy_asks_again(app, services):
    answers = iter([Reading(ok=False, detail="not installed"), Reading(ok=True, detail="current")])
    dialog = ChecklistDialog(
        [
            MachineCheck(
                id="install.skill",
                group="DPlanner",
                label="Agent skill",
                probe=lambda: next(answers),
                remedy=INSTALL,
                required=True,
            )
        ],
        services.tasks,
        lambda _id: None,
        services.window,
    )
    wait_for(app, lambda: dialog.status.tone() != "busy")

    button = dialog.rows[0].button
    assert button is not None
    button.click()
    wait_for(app, lambda: dialog.status.tone() == "ok")

    assert "current" in words(dialog)["install.skill"]


# -- the preference and the greeting ---------------------------------------------------------


def test_the_checkbox_writes_the_preference(settled):
    dialog, _ran = settled

    assert dialog.at_start.text() == AT_START
    assert dialog.at_start.isChecked()  # On unless somebody says otherwise.


def test_the_greeting_says_how_to_come_back(services, sample):
    greeting = ChecklistDialog(
        sample, services.tasks, lambda _id: None, services.window, greeting=True
    )
    plain = ChecklistDialog(sample, services.tasks, lambda _id: None, services.window)

    def notes(dialog):
        from PySide6.QtWidgets import QLabel

        return [label.text() for label in dialog.body.findChildren(QLabel)]

    assert GREETING in notes(greeting)
    assert GREETING not in notes(plain)


# -- the module ------------------------------------------------------------------------------


@pytest.fixture
def module(app, services, sample):
    """A checklist module of its own, over a registry of its own — the session already
    registered one, and an id is registered once.

    ``register()`` schedules the start-up sweep, and the conftest's guard is still in place
    while this fixture runs, so nothing probes until a test calls :func:`starts`.
    """
    actions = ActionRegistry(MenuStructure(MENU_STRUCTURE))
    actions.register(
        ActionSpec(
            id="install.dplanner",
            label="&Install DPlanner…",
            menu="Tools",
            group="install",
            order=10,
            run=lambda _c: None,
        )
    )
    built = ChecklistModule(
        ChecklistDeps(
            actions=actions,
            context=services.context,
            tasks=services.tasks,
            parent=services.window,
            checks=lambda: sample,
        )
    )
    built.register()
    return built


def starts(module, monkeypatch):
    """Start the window, as the deferred turn after ``register()`` would."""
    monkeypatch.setattr(checklist_module, "_greeted_this_process", False)
    module._at_start()


def opened(module):
    return module._deps.parent.findChild(ChecklistDialog)


def test_the_menu_entry_counts_what_is_required_and_missing(app, module, services, monkeypatch):
    spec = module._deps.actions.spec("checklist.show")

    assert spec.state(services.context.current()).label == "&Setup Checklist…"

    checklist_module.set_greeted()
    starts(module, monkeypatch)
    wait_for(app, lambda: module.missing() > 0)

    # The menu bar paints no glyph, so the count in the words is the only mark it can wear.
    assert spec.state(services.context.current()).label == "&Setup Checklist (1)…"


def test_a_machine_it_has_never_met_is_greeted_whatever_it_has(app, module, monkeypatch):
    assert not greeted()

    starts(module, monkeypatch)

    assert greeted()
    assert opened(module) is not None


def test_the_greeting_is_one_per_process_however_many_workspaces_open(app, module, monkeypatch):
    starts(module, monkeypatch)
    assert len(module._deps.parent.findChildren(ChecklistDialog)) == 1

    module._at_start()  # A workspace switch re-runs every module's register().

    assert len(module._deps.parent.findChildren(ChecklistDialog)) == 1


def test_a_greeted_machine_is_opened_for_a_required_row(app, module, monkeypatch):
    checklist_module.set_greeted()

    starts(module, monkeypatch)
    wait_for(app, lambda: module.missing() > 0)

    assert opened(module) is not None


def test_a_greeted_machine_with_everything_required_says_nothing(app, services, monkeypatch):
    checklist_module.set_greeted()
    built = ChecklistModule(
        ChecklistDeps(
            actions=ActionRegistry(MenuStructure(MENU_STRUCTURE)),
            context=services.context,
            tasks=services.tasks,
            parent=services.window,
            checks=lambda: [check("git.installed", "Git and GitHub", ok=True, required=True)],
        )
    )
    built.register()

    starts(built, monkeypatch)
    wait_for(app, lambda: built._runner is not None and not built._runner.is_busy())

    assert built.missing() == 0
    assert opened(built) is None


def test_the_person_who_turned_it_off_is_not_asked_again(app, module, monkeypatch):
    checklist_module.set_greeted()
    checklist_module.set_at_start(False)

    starts(module, monkeypatch)

    assert not at_start()
    assert opened(module) is None


def test_the_start_up_sweep_asks_only_the_required_rows(app, services, monkeypatch):
    """What ``required`` costs a machine: a launch probes these and nothing else — no
    network, no ``gh auth status``, no ``az``."""
    asked: list[str] = []

    def watched(check_id, *, required):
        def probe():
            asked.append(check_id)
            return Reading(ok=True)

        return MachineCheck(
            id=check_id, group="Services", label=check_id, probe=probe, required=required
        )

    built = ChecklistModule(
        ChecklistDeps(
            actions=ActionRegistry(MenuStructure(MENU_STRUCTURE)),
            context=services.context,
            tasks=services.tasks,
            parent=services.window,
            checks=lambda: [watched("git.installed", required=True), watched("az", required=False)],
        )
    )
    built.register()
    checklist_module.set_greeted()

    starts(built, monkeypatch)
    wait_for(app, lambda: built._runner is not None and not built._runner.is_busy())

    assert asked == ["git.installed"]
    assert opened(built) is None  # Nothing required is wanting, so nothing is said.
