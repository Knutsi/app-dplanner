"""The Description block on the Details tab: the prose, the images the prose references,
and the one switch that decides whether an agent step gets instructions of its own.

`dplanner describe attach` has always written images beside the step; this is the surface
that shows them, and — since the editor takes a paste or a drop — the one most people will
use to put one there. Text, thumbnails and Ctrl+V all come from the framework's
:class:`ProseSection`, which grows a gallery when given an ``attach_title``, so this subclass
has only two jobs of its own: aim that gallery at the step being shown, and offer the
"Separate agent instruction" checkbox on agent steps.

The description *is* an agent step's instructions; the checkbox is the opt-out, reached
through :class:`SeparateInstructionLink` — typed callbacks wired by the composition root, so
this module never learns the agent module's name.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import QCheckBox

from dplanner.domain.model import Library
from dplanner.framework.asset_gallery import AreaFor
from dplanner.framework.prose_edit import Pick
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm


@dataclass(frozen=True)
class SeparateInstructionLink:
    """The Description block's window onto the agent aspect, in this module's vocabulary."""

    agent_enabled: Callable[[str], bool]  # Is this an agent step at all?
    separate: Callable[[str], bool]  # Does it keep instructions distinct from the prose?
    has_text: Callable[[str], bool]  # Is there separate text that unchecking would drop?
    set_separate: Callable[[str, bool], None]  # The write, pushed through the undo stack.


class DescriptionSection(ProseSection):
    """The prose editor with its image gallery under it."""

    def __init__(
        self,
        field_for: Callable[[str], TextField[Any] | None],
        undo: UndoService[Any],
        placeholder: str,
        area_for_target: Callable[[str], AreaFor | None] | None = None,
        agent_link: SeparateInstructionLink | None = None,
        library: Library | None = None,
        pick_for_target: Callable[[str], Pick | None] | None = None,
    ) -> None:
        # margin 0: the Details tab hosts this as a block and owns the outer spacing.
        super().__init__(
            field_for,
            undo,
            placeholder,
            margin=0,
            expand_title="Description",
            attach_title="Attach to Description",
        )
        self._area_for_target = area_for_target
        self._pick_for_target = pick_for_target
        self._agent_link = agent_link
        self._target_id: str | None = None
        self._loading = False
        self.separate_check = QCheckBox("Separate agent instruction", self)
        self.separate_check.setToolTip(
            "By default this description is what the agent is briefed with. Tick to write"
            " execution-specific instructions on the Agent tab instead."
        )
        self.separate_check.toggled.connect(self._on_separate_toggled)
        self.separate_check.hide()
        layout = self.layout()
        if layout is not None:
            layout.addWidget(self.separate_check)

        # The checkbox mirrors another module's aspect, so it follows the model, not the
        # selection: toggling the aspect elsewhere must reach a tab already on screen.
        self._unsubscribes: list[Callable[[], None]] = []
        if library is not None and agent_link is not None:
            self._unsubscribes = [
                library.module_data_changed.connect(
                    lambda node_id, _module, _origin: self._refresh_agent_link(node_id)
                ),
                library.text_edited.connect(
                    lambda edit, _origin: self._refresh_agent_link(edit.node_id)
                ),
            ]

    def show_target(self, target_id: str | None) -> None:
        # The base clears the area first, so a step with no files never inherits the last
        # step's; this only has to point it somewhere when there is somewhere to point.
        super().show_target(target_id)
        self._target_id = target_id
        if target_id is not None and self._area_for_target is not None:
            self.set_area(self._area_for_target(target_id))
        if target_id is not None and self._pick_for_target is not None:
            self.set_picker(self._pick_for_target(target_id))
        self._reload_separate()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        super().dispose()

    # -- the separate-instruction switch ---------------------------------------------------

    def _refresh_agent_link(self, node_id: str) -> None:
        if node_id == self._target_id:
            self._reload_separate()

    def _reload_separate(self) -> None:
        link, target_id = self._agent_link, self._target_id
        if link is None or target_id is None or not self.isEnabled():
            self.separate_check.hide()
            return
        self.separate_check.setVisible(link.agent_enabled(target_id))
        self._loading = True
        try:
            self.separate_check.setChecked(link.separate(target_id))
        finally:
            self._loading = False

    def _on_separate_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        link, target_id = self._agent_link, self._target_id
        if link is None or target_id is None:
            return
        if not checked and link.has_text(target_id):
            question = (
                "Drop the separate agent instruction? The description becomes the"
                " instructions; the separate text is not kept."
            )
            if not confirm(self, "Separate Agent Instruction", question):
                self._loading = True
                try:
                    self.separate_check.setChecked(True)
                finally:
                    self._loading = False
                return
        link.set_separate(target_id, checked)
