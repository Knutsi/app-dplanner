"""The files a paste or a drop is carrying, in the vocabulary both editors share.

Two editors in this application accept files this way, and they agree on almost nothing: the
spec module's :class:`~dplanner.modules.spec.editor.SpecMarkdownEditor` is a rich-text widget
that embeds a picture and takes images only, and the prose stack's
:class:`~dplanner.framework.prose_edit.ProseEdit` is plain text that writes a markdown link
and takes anything. What they *do* share is the rule for reading a ``QMimeData`` — local
files first, clipboard pixels second — and that rule has one definition here so the two
cannot drift over what a drop meant.

Two functions, because Qt asks the question twice and the two askings cost different things:
:func:`carries_files` answers "would you take this?" on every drag-move and never reads a
byte; :func:`payloads` answers "then here it is" once, on the drop, and does.

:data:`IMAGE_SUFFIXES` and :data:`IMAGE_FILTER` live here too, as one answer to "what does
this application call an image" — used to filter a drop and to filter a file dialog, which
must not disagree.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QMimeData
from PySide6.QtGui import QImage

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All files (*)"

# Pixels off the clipboard have no name of their own — a screenshot, a crop, a copy out of a
# browser. The stem is the alt text a markdown link gets, so this reads as ``![image](…)``.
PASTED_IMAGE = "image.png"


@dataclass(frozen=True)
class Payload:
    """One arriving file: its bytes, the name to derive an asset name from, and whether it
    is an image — which is all a caller needs to decide how a link to it should read."""

    data: bytes
    filename: str
    is_image: bool


def carries_files(source: QMimeData, *, images_only: bool) -> bool:
    """Whether ``source`` holds anything :func:`payloads` would return, without reading it.

    Qt asks this on every drag-move event, so it stays a ``stat`` at worst. It may say yes
    to an image the decoder later rejects; the caller falls back to Qt's own paste then,
    which is the same answer it would have given anyway.
    """
    return bool(_candidates(source, images_only)) or source.hasImage()


def payloads(source: QMimeData, *, images_only: bool) -> list[Payload]:
    """The files ``source`` carries, read.

    Local files win over clipboard pixels: a drop out of a file manager offers both, and the
    file on disk is the better original — it keeps its format and its name.
    """
    files = [file_payload(path) for path in _candidates(source, images_only)]
    if files:
        return files
    if source.hasImage():
        image = QImage(source.imageData())
        if not image.isNull():
            return [Payload(png_bytes(image), PASTED_IMAGE, True)]
    return []


def file_payload(path: Path) -> Payload:
    """One local file, read and classified — the shape a file picker also produces."""
    return Payload(path.read_bytes(), path.name, _is_image(path))


def png_bytes(image: QImage) -> bytes:
    """An image as PNG bytes, ready for a file area."""
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    # The stubs want bytes here; the runtime only accepts str. The runtime wins.
    image.save(buffer, "PNG")  # type: ignore[call-overload]
    buffer.close()
    return bytes(buffer.data().data())


def _candidates(source: QMimeData, images_only: bool) -> list[Path]:
    """The local files ``source`` names that this caller would take. Directories and URLs
    pointing off this machine are not files and never survive here."""
    if not source.hasUrls():
        return []
    paths = [Path(url.toLocalFile()) for url in source.urls() if url.isLocalFile()]
    keep = [path for path in paths if path.is_file()]
    return [path for path in keep if _is_image(path)] if images_only else keep


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES
