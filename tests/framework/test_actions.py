"""Actions: menu validation, ordering across modules, and the state gate."""

import pytest

from dplanner.core.telemetry import current
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
    MenuStructure,
    key_sequences,
)
from dplanner.framework.context import Context

MENUS = MenuStructure({"File": ("open", "save"), "Edit": ("history",)})


def spec(action_id, menu="File", group="open", order=50, **kwargs):
    return ActionSpec(id=action_id, label=action_id, menu=menu, group=group, order=order, **kwargs)


@pytest.fixture
def registry():
    return ActionRegistry(MENUS)


def test_a_duplicate_id_is_refused(registry):
    registry.register(spec("a"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec("a"))


def test_an_unknown_menu_fails_at_registration(registry):
    with pytest.raises(ValueError, match="unknown menu"):
        registry.register(spec("a", menu="Nope"))


def test_an_unknown_group_names_the_valid_ones(registry):
    with pytest.raises(ValueError, match="groups: open, save"):
        registry.register(spec("a", group="nope"))


def test_a_verb_seated_in_a_data_menu_may_carry_no_shortcut(registry):
    """Nothing in the bar would fire it, so the registration says so."""
    registry.register(spec("a", in_menus=False))
    with pytest.raises(ValueError, match="in no menu"):
        registry.register(spec("b", in_menus=False, shortcut="Ctrl+B"))


def test_a_data_menu_is_found_by_id(registry):
    from dplanner.framework.action_registry import DataMenuSpec

    data = DataMenuSpec(id="d", menu="File", group="open", title="D", fill=lambda _m: None)
    registry.register_data_menu(data)
    assert registry.data_menu("d") is data


def test_ordering_is_menu_then_group_then_order(registry):
    registry.register(spec("edit", menu="Edit", group="history"))
    registry.register(spec("save", group="save", order=10))
    registry.register(spec("open_late", group="open", order=90))
    registry.register(spec("open_early", group="open", order=10))
    assert [s.id for s in registry.all_specs()] == ["open_early", "open_late", "save", "edit"]


def test_only_runnable_specs_are_offered(registry):
    registry.register(spec("visible"))
    registry.register(spec("hidden", state=lambda _c: ActionState(visible=False, enabled=False)))
    registry.register(spec("disabled", state=lambda _c: DISABLED))
    offered = [s.id for s, _state in registry.runnable(Context({}))]
    assert offered == ["visible"]


def test_running_by_id_honours_the_state_gate(registry):
    ran = []
    registry.register(spec("blocked", state=lambda _c: DISABLED, run=lambda _c: ran.append(1)))
    registry.run("blocked", Context({}))
    assert ran == []


def test_a_state_callback_can_rename_its_action(registry):
    registry.register(spec("a", state=lambda _c: ActionState(label="Delete 3 Items")))
    _spec, state = registry.runnable(Context({}))[0]
    assert state.label == "Delete 3 Items"


def test_registering_announces_the_spec(registry):
    """Presenters that already exist learn about later registrations through this."""
    seen = []
    registry.registered.connect(lambda s: seen.append(s.id))
    registry.register(spec("a"))
    assert seen == ["a"]


def test_a_standard_key_expands_to_every_platform_binding(app):
    # Needs the QApplication: resolving a StandardKey reads the platform theme.
    from PySide6.QtGui import QKeySequence

    assert key_sequences(QKeySequence.StandardKey.Undo)
    assert len(key_sequences(("Ctrl++", "Ctrl+="))) == 2
    assert key_sequences(None) == []


def test_the_default_state_is_enabled(registry):
    registry.register(spec("a"))
    assert registry.spec("a").state(Context({})) == ENABLED


# -- every run is a span -------------------------------------------------------------------------


def test_running_an_action_is_timed(registry):
    current().clear()
    registry.register(spec("a", run=lambda _c: None))
    registry.run("a", Context({}))
    (span,) = [span for span in current().recent() if span.kind == "action"]
    assert span.name == "a" and span.ok and span.duration_ms is not None


def test_a_raising_action_is_recorded_and_re_raised(registry):
    current().clear()

    def explode(_context):
        raise RuntimeError("no such step")

    registry.register(spec("a", run=explode))
    with pytest.raises(RuntimeError, match="no such step"):
        registry.run("a", Context({}))
    (span,) = [span for span in current().recent() if span.kind == "action"]
    assert span.ok is False and span.error_type == "RuntimeError"
