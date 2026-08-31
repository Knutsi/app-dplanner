"""Pluggable sections for a detail panel: "a module-owned surface about the current thing".

A module that has something to say about whatever the user has selected registers an
:class:`InspectorSection` and appears as a sibling tab beside whatever else is registered.
The host panel is created once per tab that shows one, so ``factory`` returns a fresh
extension per panel instance and the host drives its lifecycle: ``show_target`` on every
selection change (``None`` when nothing is shown), ``dispose`` when the panel goes away.

Register sections before the first panel is built. Module order in the composition root is
what guarantees that, which is why positions there carry comments.

The registry is deliberately instantiated more than once: the contract for "a module-owned
surface that appears when it has something to say" turned out to be identical for a panel
tab, for a card stacked inside one, and for a block on the step panel's Details tab, so
each later use reuses the type rather than copying it. The only difference is which host
renders the sections — and a host is addressed by which registry instance you register
into, never by a mode field on the section.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget


class InspectorExtension(Protocol):
    """One module-owned tab in the panel, satisfied structurally."""

    @property
    def widget(self) -> QWidget: ...

    def show_target(self, target_id: str | None) -> None: ...

    def dispose(self) -> None: ...


@dataclass(frozen=True)
class InspectorSection:
    id: str  # Module-prefixed, globally unique.
    label: str  # Tab text: "Properties".
    factory: Callable[[], InspectorExtension]  # One extension per panel instance.
    order: int = 50
    # Tab glyph, colour-parameterized like everything in dplanner.theme.icons; the panel
    # paints it in the theme's secondary text colour and repaints on theme change.
    icon: Callable[[str], QIcon] | None = None
    # Whether this section's tab is shown for a target; None means always. The host still
    # builds every extension once — this governs visibility only, re-asked on every target
    # change and on model changes to the shown target, so a toggled-off aspect's tab
    # disappears rather than sitting empty.
    shown_for: Callable[[str | None], bool] | None = None
    # How much of the leftover height a vertically stacking host gives this section's
    # widget; tab and card hosts ignore it. One editor per host claims the room (1), the
    # compact rows keep their size hint (0).
    stretch: int = 0
    # A standing convention the reader may not know — the unit a number is in, what a
    # default means. A captioned host puts it behind an info glyph beside the caption
    # rather than on a line of its own under the field, which is DESIGN.md's *Words* rule:
    # a sentence that never changes is re-read on every visit and earns none of them.
    hint: str = ""


class InspectorSectionRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, InspectorSection] = {}

    def register(self, section: InspectorSection) -> None:
        if section.id in self._sections:
            raise ValueError(f"inspector section {section.id!r} already registered")
        self._sections[section.id] = section

    def sections(self) -> list[InspectorSection]:
        return sorted(self._sections.values(), key=lambda s: (s.order, s.id))
