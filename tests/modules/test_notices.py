"""View ▸ Notices: an inbox of standing conditions, opt-in per source, a bell in the menu
bar's corner that counts what stands, and a row that opens where the condition is fixed.

Built over the real application with ``_notice_sources`` — the composition root's one
assembly — handed a fake, so the tab, the bell and the preferences are proven without
the skill source; the skill source has tests of its own below.
"""

import time

import pytest
from PySide6.QtCore import Qt

from dplanner.cli.skill import install
from dplanner.core.signals import Signal
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.domain.notice import Notice
from dplanner.framework.context import Context
from dplanner.framework.user_config import get_global
from dplanner.modules.install.notices import MISSING, STALE, SkillNoticeSource
from dplanner.modules.notices.activity import NOTHING_STANDING, NOTHING_WATCHED, NOTICES_KIND
from dplanner.modules.notices.module import MODULE_ID, MUTED_KEY, SOURCES_KEY
from dplanner.modules.notices.sources import bell_text


class FakeSource:
    id = "fake.source"
    label = "Fake"

    def __init__(self) -> None:
        self.changed: Signal[()] = Signal()
        self.notices: list[Notice] = []
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def scan(self) -> list[Notice]:
        return list(self.notices)


def notice(key: str, target: tuple[str, ...] = ("tab", "telemetry", "")) -> Notice:
    return Notice(key, f"Condition {key}", "What resolves it.", target, where="Somewhere")


@pytest.fixture
def fake(monkeypatch):
    """Requested before ``services``: the root assembles the sources while it builds."""
    source = FakeSource()
    monkeypatch.setattr("dplanner.modules._notice_sources", lambda _install: (source,))
    return source


def module_of(services):
    return next(module for module in services.modules if module.id == MODULE_ID)


# -- the switches ------------------------------------------------------------------------------


def test_every_source_is_off_at_first_and_the_bell_is_hidden(fake, services):
    fake.notices = [notice("a")]
    module = module_of(services)
    module.rescan()
    assert fake.started == 0 and module.bell.isHidden()
    activity = services.tabs.open(NOTICES_KIND)
    assert activity.rows() == []
    assert activity.empty.text() == NOTHING_WATCHED
    assert not activity.switches[fake.id].isChecked()


def test_switching_a_source_on_persists_starts_it_and_scans(fake, services):
    fake.notices = [notice("a")]
    module = module_of(services)
    module.set_on(fake.id, True)
    assert get_global(MODULE_ID, SOURCES_KEY) == {fake.id: True}
    assert fake.started == 1
    assert not module.bell.isHidden() and module.bell.text() == "Condition a"
    fake.notices = [notice("a"), notice("b")]
    module.rescan()
    assert module.bell.text() == "2 notices"
    module.set_on(fake.id, False)
    assert fake.stopped == 1 and module.bell.isHidden()


def test_the_tabs_switch_drives_the_module_and_the_empty_line_says_why(fake, services):
    module = module_of(services)
    activity = services.tabs.open(NOTICES_KIND)
    activity.switches[fake.id].setChecked(True)
    assert module.is_on(fake.id)
    assert activity.empty.text() == NOTHING_STANDING and activity.empty.isVisibleTo(activity.widget)
    fake.notices = [notice("a")]
    module.rescan()
    assert activity.rows() == [("Condition a", False)]
    assert not activity.empty.isVisibleTo(activity.widget)


def test_the_timer_runs_only_while_a_source_is_on(fake, services):
    module = module_of(services)
    assert not module._timer.isActive()
    module.set_on(fake.id, True)
    assert module._timer.isActive()
    module.set_on(fake.id, False)
    assert not module._timer.isActive()


def test_a_source_saying_changed_is_heard(fake, services):
    module = module_of(services)
    module.set_on(fake.id, True)
    fake.notices = [notice("a")]
    fake.changed.emit()
    assert module.bell.text() == "Condition a"


# -- going there -------------------------------------------------------------------------------


def test_open_goes_to_a_tab_an_action_or_a_step(fake, services, make_project):
    project = make_project("Discovery")
    library = services.document
    AddNodeCommand(project.id, Step(title="A step")).redo(library)
    (step,) = project.steps
    module = module_of(services)
    module.set_on(fake.id, True)
    fake.notices = [
        notice("tab", ("tab", "telemetry", "")),
        notice("verb", ("action", "debug.llm_calls")),
        notice("step", ("step", step.id)),
    ]
    module.rescan()
    activity = services.tabs.open(NOTICES_KIND)

    activity.list.setCurrentRow(0)
    activity.open_current()
    assert services.tabs.current_activity().title == "Telemetry"

    services.tabs.open(NOTICES_KIND)
    activity.list.setCurrentRow(1)
    activity.open_current()
    assert services.tabs.current_activity().title == "LLM Calls"

    services.tabs.open(NOTICES_KIND)
    activity.list.setCurrentRow(2)
    activity.open_current()
    assert services.context.current().selected_entity("step") == step.id


# -- muting ------------------------------------------------------------------------------------


def test_a_mute_hides_from_the_bell_greys_the_row_and_lasts_until_the_notice_clears(fake, services):
    module = module_of(services)
    module.set_on(fake.id, True)
    fake.notices = [notice("a"), notice("b")]
    module.rescan()
    activity = services.tabs.open(NOTICES_KIND)
    activity.list.setCurrentRow(0)
    activity.toggle_mute_current()
    assert module.bell.text() == "Condition b"
    assert activity.rows() == [("Condition b", False), ("Condition a", True)]
    assert get_global(MODULE_ID, MUTED_KEY) == [f"{fake.id}:a"]
    assert activity.mute_action.text() == "Unmute"  # The muted row stays picked.

    fake.notices = [notice("b")]  # The condition cleared: the mute goes with it.
    module.rescan()
    assert get_global(MODULE_ID, MUTED_KEY) == []
    fake.notices = [notice("a"), notice("b")]  # …and it is heard again when it returns.
    module.rescan()
    assert module.bell.text() == "2 notices"


# -- the chrome --------------------------------------------------------------------------------


def test_the_bell_sits_in_the_menu_bars_corner_and_the_menu_opens_the_tab(fake, services):
    module = module_of(services)
    corner = services.window.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
    assert corner is module.bell
    services.actions.run("notices.show", Context({}))
    assert services.tabs.current_activity().title == "Notices"


@pytest.mark.parametrize(
    ("titles", "text"),
    [
        ([], ""),
        (["Agent skill is out of date"], "Agent skill is out of date"),
        (["A" * 60], "A" * 39 + "…"),
        (["one", "two"], "2 notices"),
    ],
)
def test_the_bell_words_one_title_or_a_count(titles, text):
    assert bell_text(titles) == text


# -- the skill source --------------------------------------------------------------------------

FILES = {"SKILL.md": "# skill\n", "reference.md": "# reference\n"}


@pytest.fixture
def skill_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "skills" / "dplanner"


def test_the_skill_source_stands_for_missing_stale_or_nothing(skill_home):
    prepared = []
    source = SkillNoticeSource(lambda: FILES, lambda: prepared.append(True))
    source.start()
    assert prepared == [True]
    assert source.scan() == [MISSING]
    install(FILES, skill_home)
    assert source.scan() == []
    (skill_home / "SKILL.md").write_text("# older\n")
    assert source.scan() == [STALE]


def test_the_skill_source_stands_for_nothing_until_the_render_has_landed(skill_home):
    source = SkillNoticeSource(lambda: None, lambda: None)
    assert source.scan() == []


def test_switching_the_skill_source_on_renders_once_off_the_gui_thread(app, skill_home, services):
    module = module_of(services)
    module.set_on("install.skill", True)
    deadline = time.time() + 10
    while module.bell.isHidden():
        assert time.time() < deadline, "the render never landed"
        app.processEvents()
        time.sleep(0.01)
    assert module.bell.text() == "Agent skill is not installed"
    activity = services.tabs.open(NOTICES_KIND)
    assert activity.rows() == [("Agent skill is not installed", False)]
    activity.list.setCurrentRow(0)
    activity.toggle_mute_current()
    assert module.bell.isHidden()
