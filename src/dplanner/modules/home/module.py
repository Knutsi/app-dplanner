"""Home: where a window starts — the getting-started guide, and a garden that says what
DPlanner does.

Home is the ``home`` tab, a singleton like any library-wide tab, and there are three ways
to it:

- the program's start, when there were no tabs to reopen — the composition root's
  ``start_window``, called by ``app.open_at_startup`` and never by a reload, so a window
  whose last tab was closed stays blank;
- the index's first row, a folder of its own whose segment answers its own row: a click
  previews Home, activation keeps it;
- *Go ▸ Home*, because Go seats the index's rows.

Its one preference — whether the garden shows — is *Settings ▸ Home*; ``garden_changed`` is
how an open Home tab hears it change.
"""

from dataclasses import dataclass

from dplanner.core.signals import Signal
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import ContextService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry, SurfaceSegment
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.modules.home.page import HOME_KIND, HomeActivity
from dplanner.modules.home.settings_page import MODULE_ID, build_page
from dplanner.theme.icons import home_icon


@dataclass(frozen=True)
class HomeDeps:
    tabs: TabHost
    actions: ActionRegistry
    context: ContextService
    segments: IndexSegmentRegistry
    settings_sections: SettingsSectionRegistry


class HomeModule:
    id = MODULE_ID

    def __init__(self, deps: HomeDeps) -> None:
        self._deps = deps
        # Whether the garden shows changed — from Settings ▸ Home or the garden's close.
        self.garden_changed: Signal[()] = Signal()

    def register(self) -> None:
        deps = self._deps
        changed = self.garden_changed
        deps.tabs.register_factory(HOME_KIND, lambda _target: HomeActivity(deps, changed))
        deps.settings_sections.register(
            SettingsSection(
                id=f"{MODULE_ID}.page",
                category=("Home",),
                factory=lambda parent: build_page(parent, changed),
            )
        )
        deps.segments.register(
            IndexSegment(
                id=MODULE_ID,
                label="Home",
                factory=lambda _root: SurfaceSegment(self.open),
                order=0,  # The top of the index: where a window starts.
                icon=home_icon,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="home.open",
                label="&Home",
                menu="Go",
                group="home",
                order=10,
                tip="The getting-started guide",
                icon=home_icon,
                run=lambda _context: self.open(),
            )
        )

    def open(self, preview: bool = False) -> None:
        self._deps.tabs.open(HOME_KIND, preview=preview)
