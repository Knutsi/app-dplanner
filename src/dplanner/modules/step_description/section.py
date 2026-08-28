"""The Description tab: the prose, and the images the prose references.

`dplanner describe attach` has always written images beside the step; this is the first
surface that shows them. The editor half is the framework's :class:`ProseSection`
unchanged — this subclass only hangs an editable :class:`AssetGallery` under it and
retargets the gallery whenever the section is shown a different step.
"""

from collections.abc import Callable
from typing import Any

from dplanner.framework.asset_gallery import AreaFor, AssetGallery
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService

FIELD_GAP = 6


class DescriptionSection(ProseSection):
    """The prose editor with its image gallery under it."""

    def __init__(
        self,
        field_for: Callable[[str], TextField[Any] | None],
        undo: UndoService[Any],
        placeholder: str,
        area_for_target: Callable[[str], AreaFor | None] | None = None,
    ) -> None:
        super().__init__(field_for, undo, placeholder)
        self._area_for_target = area_for_target
        self.gallery = AssetGallery(self, editable=True, attach_title="Attach to Description")
        layout = self.layout()
        if layout is not None:
            layout.setSpacing(FIELD_GAP)
            layout.addWidget(self.gallery)

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        provider = None
        if target_id is not None and self._area_for_target is not None:
            provider = self._area_for_target(target_id)
        self.gallery.set_area(provider)
