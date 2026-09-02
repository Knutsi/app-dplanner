"""The prose stack's editor: markdown source, and files that arrive by paste or drop.

Every prose document here is markdown kept as *plain text* — :mod:`.markdown_highlight` has
the reason: a rich-text widget edits a document tree and writes back a normalised
serialisation, so a keystroke stops being the one small splice :class:`.TextBinding` needs.
A plain-text editor therefore cannot show a picture, and pretending otherwise would cost the
binding. So this does the honest half instead, which is the half that matters: the file is
attached to the module's content-addressed file area and a markdown link to it is typed at
the caret. The gallery under the editor renders the thumbnail; the CLI's ``attach`` verbs
have been writing to that same place all along.

**Typing the link is the whole implementation.** Going in through the cursor makes it an
ordinary edit — ``contentsChange`` → the field's command → the undo stack → every other view
bound to the same document — so an expanded editor tracks it keystroke for keystroke and
Ctrl+Z removes it like any other typing. The *file* write deliberately does not join it on
the stack: undoing a paste must never leave prose pointing at a file that had gone. An
orphaned blob is recoverable; a dangling link is not (``FORMAT.md``, ``domain/assets.py``).

**The editor does not write the file itself.** It is handed an :data:`Attach` callable —
:meth:`AssetGallery.attach_bytes` in every host — because attaching is three steps, not one:
resolve the area, write, and redraw the thumbnails. An editor that only did the middle step
would put a pasted image on disk with nothing beside it, and would need its own answer for a
node autosave has not flushed yet. Borrowing the gallery's gives one answer to both.

**Why the context menu is built by hand.** ``CLAUDE.md`` says a right-click renders a menu
from ``MENU_STRUCTURE``, never a hand-built copy — a rule about menus of *application verbs*,
which this is not. ``Insert Image…`` acts on this widget's caret, means nothing without one,
and would be permanently greyed in the palette and the menu bar. That is the same call the
spec editor made for its formatting verbs, for the same reason.
"""

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QFileDialog, QPlainTextEdit, QWidget

from dplanner.framework.mime_files import (
    IMAGE_FILTER,
    Payload,
    carries_files,
    file_payload,
    payloads,
)
from dplanner.framework.undo import UndoService

# Bytes and a filename in, the area-relative path to link to out — or None when the node has
# no directory yet and the host has said so in its own words.
type Attach = Callable[[bytes, str], str | None]

# Runs a modal picker over what the project already holds and returns the chosen files —
# empty when the person cancelled. Payloads, not paths: a picked asset arrives exactly as a
# paste would, copied into this editor's own area, so reuse never creates a link into
# somebody else's directory.
type Pick = Callable[[], list[Payload]]


class ProseEdit(QPlainTextEdit):
    """A markdown editor that turns a pasted or dropped file into an attachment and a link."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        undo: UndoService[Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._attach: Attach | None = None
        self._pick: Pick | None = None
        self._undo = undo

    def set_attach(self, attach: Attach | None) -> None:
        """Say where an arriving file should go, or that this editor takes none.

        ``None`` — a host with no file storage, or nothing selected — leaves a plain text
        widget: a paste is Qt's own and the menu entry is greyed.
        """
        self._attach = attach

    def set_pick(self, pick: Pick | None) -> None:
        """Say how to offer the project's existing assets, or that this editor cannot.

        Separate from :meth:`set_attach` because they answer different questions — where a
        file goes, and where one can come from — and a host may have the first without the
        second.
        """
        self._pick = pick

    # -- files in ------------------------------------------------------------------------------

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802 - Qt override
        """Also what enables Paste in the standard context menu: Qt's own answer is False
        for image-only clipboard data, which would grey the entry on the one thing here
        that most wants pasting."""
        if self._attach is not None and carries_files(source, images_only=False):
            return True
        return bool(super().canInsertFromMimeData(source))

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802 - Qt override
        """Qt routes both a paste and a drop through here, so one override covers both."""
        if self._attach is not None and self._embed(payloads(source, images_only=False)):
            return
        super().insertFromMimeData(source)

    def insert_image_from_file(self) -> None:
        """The right-click entry. The filter names images and still ends in *All files*,
        so it leads with the common case without refusing the others a drop accepts."""
        chosen, _filter = QFileDialog.getOpenFileName(self, "Insert Image", "", IMAGE_FILTER)
        if chosen:
            self._embed([file_payload(Path(chosen))])

    def insert_from_assets(self) -> None:
        """The right-click entry for reusing what the project already holds. The chosen
        assets travel :meth:`_embed` exactly as a paste does — copied into this editor's
        own area, linked at the caret, one undo step."""
        if self._pick is not None:
            self._embed(self._pick())

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 - Qt override
        menu = self.createStandardContextMenu(event.pos())
        menu.addSeparator()
        action = menu.addAction("Insert Image…")
        # CLAUDE.md: an entry that does not apply right now is disabled, never hidden.
        action.setEnabled(self._attach is not None and not self.isReadOnly())
        action.triggered.connect(self.insert_image_from_file)
        existing = menu.addAction("Insert from Assets…")
        existing.setEnabled(
            self._attach is not None and self._pick is not None and not self.isReadOnly()
        )
        existing.triggered.connect(self.insert_from_assets)
        menu.exec(event.globalPos())
        menu.deleteLater()

    # -- internals -----------------------------------------------------------------------------

    def _embed(self, items: list[Payload]) -> bool:
        """Attach every payload and type the links. False means "nothing of ours arrived",
        which is the caller's signal to let Qt paste whatever it was."""
        attaching = self._attach
        if not items or attaching is None:
            return False
        links = []
        for item in items:
            name = attaching(item.data, item.filename)
            if name is not None:
                links.append(_link(name, item))
        if not links:
            return True  # The host has already said why — do not paste a file path instead.
        # A link is not a keystroke: without sealing, EditTextCommand merges it into the
        # sentence being typed and one Ctrl+Z takes both. Seal after as well, so the next
        # keystroke starts its own step rather than growing this one.
        self._break_coalescing()
        # One insert, so a multi-file drop is one edit and one undo step.
        self.textCursor().insertText("\n".join(links))
        self._break_coalescing()
        return True

    def _break_coalescing(self) -> None:
        if self._undo is not None:
            self._undo.break_coalescing()


def _link(name: str, item: Payload) -> str:
    """The markdown that references an attachment: an image shows, anything else is a link."""
    if item.is_image:
        return f"![{PurePosixPath(item.filename).stem}]({name})"
    return f"[{item.filename}]({name})"
