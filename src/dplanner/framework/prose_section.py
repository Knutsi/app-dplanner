"""A detail-panel section over one prose document, and the files that document references.

The framework already owns the hard half of editing prose — :class:`TextBinding` turns every
keystroke into an undo command and keeps other views of the same document in sync. What was
missing is the small, easy-to-get-wrong half around it: a widget that re-binds when the panel
is told to show something else, and detaches when it is told to show nothing.

That is worth writing once because getting it wrong is quiet. A binding left pointing at a
deleted node reaches the model on the next keystroke and fails to find it; a binding not
closed before re-binding leaves the old one listening.

**Every prose editor here wears the markdown strip.** The documents are markdown and the
marks are typed by hand, so the strip is part of what a prose editor *is* rather than
something a host opts into — which is also what gives it to the description, the notes,
the test bodies, the documentation fragments and the feature editor without any of them
learning a thing. It never takes focus, so the caret stays where a verb was aimed.

**A document's images belong to the same section as its prose.** Give the section an
``attach_title`` and it grows an :class:`AssetGallery` under the editor and wires the editor's
paste and drop into it, so a host gets the whole aspect — text, thumbnails, and Ctrl+V — from
one constructor instead of hanging a gallery on the side and hoping the two stay pointed at
the same node. :meth:`set_area` is the one call that aims both; a host makes it from its own
``show_target``, where the node id the *files* are keyed by is in scope. That id is not always
the id the *field* is keyed by — a test's body is keyed by the test and its images by the step
— which is why the area arrives through a call rather than another ``…_for`` callable.

It knows nothing about any model: the caller supplies a factory that turns a target id into a
:class:`TextField`, or into ``None`` when there is nothing to edit.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.framework.asset_gallery import AreaFor, AssetGallery
from dplanner.framework.markdown_highlight import MarkdownHighlighter
from dplanner.framework.markdown_toolbar import MarkdownToolbar
from dplanner.framework.prose_edit import Pick, ProseEdit
from dplanner.framework.text_binding import TextBinding, TextField
from dplanner.framework.text_dialog import ExpandedTextDialog, attach_expand
from dplanner.framework.undo import UndoService

# DESIGN.md: side panels get 16 px outer margins.
PANEL_MARGIN = 16
FIELD_GAP = 6  # DESIGN.md: within a block, as the editor and its gallery are.


class ProseSection(QWidget):
    """One editable document, bound through the undo stack, re-bound on every target."""

    def __init__(
        self,
        field_for: Callable[[str], TextField[Any] | None],
        undo: UndoService[Any],
        placeholder: str = "",
        margin: int = PANEL_MARGIN,
        expand_title: str = "Editor",
        attach_title: str | None = None,
        hide_gallery_when_empty: bool = False,
    ) -> None:
        super().__init__()
        self._field_for = field_for
        self._undo = undo
        self._binding: TextBinding[Any] | None = None
        self._field: TextField[Any] | None = None
        self._pick: Pick | None = None
        self._placeholder = placeholder
        self._expand_title = expand_title

        self.edit = ProseEdit(self, undo=undo)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrameShape(ProseEdit.Shape.NoFrame)
        # Every document this section edits is markdown; show its structure while the
        # text stays exactly what is on disk. Re-inked on theme change below.
        self._highlighter = MarkdownHighlighter(self.edit.document(), self.edit)
        self.tools = MarkdownToolbar(self.edit, undo=undo, parent=self)
        self.expand_button = attach_expand(self.edit)
        self.expand_button.clicked.connect(self._open_expanded)
        self.expand_button.setEnabled(False)

        # ``margin`` is 0 when a host (a card, the Details tab) already owns the spacing.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.tools)
        layout.addWidget(self.edit)

        self.gallery: AssetGallery | None = None
        if attach_title is not None:
            self.gallery = AssetGallery(
                self,
                editable=True,
                attach_title=attach_title,
                hide_when_empty=hide_gallery_when_empty,
            )
            layout.addWidget(self.gallery)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            # The highlighter's inks come from the palette; a theme change owes a repaint.
            self._highlighter.rehighlight()
        super().changeEvent(event)

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._close_binding()
        # Always clear first: a section re-pointed at another node must never keep writing
        # files beside the last one — nor picking for it — and a host that has neither
        # simply never sets one.
        self.set_area(None)
        self.set_picker(None)
        field = self._field_for(target_id) if target_id is not None else None
        self._field = field
        self.expand_button.setEnabled(field is not None)
        if field is None:
            self.edit.setPlainText("")
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self._binding = TextBinding(self.edit, field, self._undo)

    def set_area(self, area_for: AreaFor | None) -> None:
        """Aim the gallery and the editor's paste at one node's file area, or at nothing."""
        if self.gallery is None:
            return
        self.gallery.set_area(area_for)
        self.edit.set_attach(self.gallery.attach_bytes if area_for is not None else None)

    def set_picker(self, pick: Pick | None) -> None:
        """Offer the project's existing assets in this editor, or stop doing so.

        :meth:`set_area`'s sibling, made from the same ``show_target`` — picking without
        an area to copy into would have nowhere to put the choice, so the editor greys
        the entry until both have arrived.
        """
        self._pick = pick
        self.edit.set_pick(pick)

    def dispose(self) -> None:
        self._field = None
        self._close_binding()

    def _open_expanded(self) -> None:
        """The same document in a big modal editor — a second binding, kept in sync
        through the foreign-change path, so typing in either shows in both."""
        if self._field is None:
            return
        dialog = ExpandedTextDialog.over_field(
            self._field,
            self._undo,
            title=self._expand_title,
            placeholder=self._placeholder,
            attach=self.gallery.attach_bytes if self.gallery is not None else None,
            pick=self._pick,
            parent=self.window(),
        )
        dialog.exec()
        dialog.dispose()

    def _close_binding(self) -> None:
        if self._binding is not None:
            self._binding.close()
            # close() only disconnects; the binding is parented to the editor, which
            # outlives it, so without this every selection change would leave one behind.
            self._binding.setParent(None)
            self._binding = None
