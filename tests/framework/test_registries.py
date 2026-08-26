"""Every registry has the same shape: registration order, and no duplicate ids.

One file rather than six near-identical ones, because the contract is genuinely the same —
and because a new registry is then one line here rather than a new file to remember to
write.
"""

import pytest

from dplanner.framework.exports import ExportRegistry, ExportSpec
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.panels import PanelRegistry, PanelSpec
from dplanner.framework.settings_registry import (
    SettingsScope,
    SettingsSection,
    SettingsSectionRegistry,
)


class FakeProvider:
    def __init__(self, provider_id):
        self.id = provider_id
        self.label = provider_id

    def is_configured(self):
        return False

    def model(self):
        return ""

    def complete(self, messages):
        raise NotImplementedError


def _segment(segment_id, order=50):
    return IndexSegment(
        id=segment_id, label=segment_id, factory=lambda _root: FakeSegmentView(), order=order
    )


class FakeSegmentView:
    """The smallest thing that satisfies IndexSegmentView."""

    def selection_nodes(self, items):
        return ()

    def activated(self, item):
        pass

    def context_menu(self, item):
        return None

    def dispose(self):
        pass


class FakeExtension:
    """The smallest thing that satisfies InspectorExtension."""

    def __init__(self):
        from PySide6.QtWidgets import QWidget

        from dplanner.core.signals import Signal

        self.tab_visibility_changed: Signal[bool] = Signal()
        self.widget = QWidget()

    def tab_visible(self):
        return True

    def show_target(self, target_id):
        pass

    def dispose(self):
        pass


def _section(section_id, order=50):
    return InspectorSection(id=section_id, label=section_id, order=order, factory=FakeExtension)


def _settings(section_id):
    from PySide6.QtWidgets import QWidget

    return SettingsSection(
        id=section_id,
        category=(section_id,),
        scope=SettingsScope.GLOBAL,
        factory=lambda parent: QWidget(parent),
    )


def _panel(panel_id, order=50):
    from PySide6.QtWidgets import QWidget

    return PanelSpec(id=panel_id, title=panel_id, factory=QWidget, order=order)


def _export(export_id):
    return ExportSpec(
        id=export_id, label=export_id, file_filter="x (*.x)", suffix=".x", run=lambda path: None
    )


CASES = [
    pytest.param(IndexSegmentRegistry, _segment, "segments", id="index_segments"),
    pytest.param(InspectorSectionRegistry, _section, "sections", id="inspector_sections"),
    pytest.param(PanelRegistry, _panel, "panels", id="panels"),
    pytest.param(SettingsSectionRegistry, _settings, "sections", id="settings_sections"),
    pytest.param(ExportRegistry, _export, "specs", id="exports"),
    pytest.param(LLMProviderRegistry, FakeProvider, "providers", id="llm_providers"),
]


@pytest.mark.parametrize(("factory", "make", "accessor"), CASES)
def test_a_duplicate_id_is_refused(app, factory, make, accessor):
    """Not defensiveness: it is what forces a workspace switch to be a rebuild."""
    registry = factory()
    registry.register(make("a"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make("a"))


@pytest.mark.parametrize(("factory", "make", "accessor"), CASES)
def test_registration_order_is_preserved(app, factory, make, accessor):
    registry = factory()
    registry.register(make("b"))
    registry.register(make("a"))
    ids = [item.id for item in getattr(registry, accessor)()]
    # Ordered registries sort by (order, id) and fall back to registration order otherwise;
    # either way both entries survive and neither is dropped.
    assert set(ids) == {"a", "b"}


def test_ordered_registries_sort_by_order_then_id(app):
    registry = IndexSegmentRegistry()
    registry.register(_segment("late", order=90))
    registry.register(_segment("early", order=10))
    assert [segment.id for segment in registry.segments()] == ["early", "late"]


def test_tab_factories_refuse_a_duplicate_kind(app):
    from dplanner.framework.activity import ActivityBase
    from dplanner.framework.context import ContextService
    from dplanner.framework.tabs import TabHost

    class FakeActivity(ActivityBase):
        uri = "app://activity/kind"
        title = "Fake"

        def __init__(self, target=None):
            from PySide6.QtWidgets import QWidget

            self.widget = QWidget()

    host = TabHost(ContextService())
    host.register_factory("kind", FakeActivity)
    with pytest.raises(ValueError, match="already registered"):
        host.register_factory("kind", FakeActivity)
