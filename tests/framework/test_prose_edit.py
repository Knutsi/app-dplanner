"""The prose editor: a pasted or dropped file becomes an attachment and a markdown link.

The editor is plain text on purpose (see ``framework/markdown_highlight.py``), so what a
paste produces is a *reference* — ``![alt](assets/…)`` — beside a file the gallery under it
writes. These drive ``insertFromMimeData`` directly, exactly as ``tests/modules/
test_spec_editor.py`` does for the rich-text stack: Qt routes both a paste and a drop
through it, so one call covers the gesture the user makes either way.
"""

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QImage

from dplanner.core.png import encode_rgb
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.assets import assets
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.asset_gallery import AssetGallery
from dplanner.framework.prose_edit import ProseEdit


def png_bytes():
    return encode_rgb(2, 2, 6, b"\x00" * 12)


@pytest.fixture
def area(tmp_path):
    storage = LocalStorage(tmp_path / "ws")
    return ModuleFileArea(storage, "modules/step_description", lambda _p: None)


@pytest.fixture
def gallery(app, area):
    widget = AssetGallery(editable=True)
    widget.set_area(lambda: area)
    yield widget
    widget.deleteLater()


@pytest.fixture
def edit(app, gallery):
    widget = ProseEdit()
    widget.set_attach(gallery.attach_bytes)
    yield widget
    widget.deleteLater()


def image_mime():
    mime = QMimeData()
    mime.setImageData(QImage.fromData(png_bytes()))
    return mime


def url_mime(*paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


# -- what arrives ------------------------------------------------------------------------------


def test_pasted_pixels_attach_and_link(edit, area):
    """Clipboard pixels have no name of their own, so the alt text says what it is."""
    edit.insertFromMimeData(image_mime())
    names = assets(area)
    assert len(names) == 1 and names[0].endswith(".png")
    assert edit.toPlainText() == f"![image]({names[0]})"


def test_a_dropped_image_keeps_its_own_name_as_the_alt_text(edit, area, tmp_path):
    path = tmp_path / "diagram.png"
    path.write_bytes(png_bytes())
    edit.insertFromMimeData(url_mime(path))
    assert edit.toPlainText() == f"![diagram]({assets(area)[0]})"


def test_a_dropped_file_that_is_not_an_image_becomes_a_plain_link(edit, area, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("findings")
    edit.insertFromMimeData(url_mime(path))
    name = assets(area)[0]
    assert name.endswith(".txt")
    assert edit.toPlainText() == f"[notes.txt]({name})"


def test_several_files_at_once_are_one_link_per_line(edit, area, tmp_path):
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    first.write_bytes(png_bytes())
    second.write_bytes(encode_rgb(1, 1, 3, b"\xff\x00\x00"))
    edit.insertFromMimeData(url_mime(first, second))
    assert len(assets(area)) == 2
    assert edit.toPlainText().count("\n") == 1


def test_the_same_bytes_twice_attach_once(edit, area, tmp_path):
    path = tmp_path / "diagram.png"
    path.write_bytes(png_bytes())
    edit.insertFromMimeData(url_mime(path))
    edit.insertFromMimeData(url_mime(path))
    # Content-addressed: one file, two references to it.
    assert len(assets(area)) == 1
    assert edit.toPlainText().count("![diagram]") == 2


def test_the_caret_ends_after_the_link_so_a_second_paste_appends(edit):
    edit.insertPlainText("before ")
    edit.insertFromMimeData(image_mime())
    edit.insertPlainText(" after")
    assert edit.toPlainText().startswith("before ![image](")
    assert edit.toPlainText().endswith(" after")


def test_a_pasted_image_reaches_the_gallery(edit, gallery):
    """The bug this seam exists to prevent: a file on disk with no thumbnail beside it."""
    assert gallery._names == []
    edit.insertFromMimeData(image_mime())
    assert len(gallery._names) == 1


# -- what does not ------------------------------------------------------------------------------


def test_plain_text_is_still_qt_s_own_paste(edit, area):
    mime = QMimeData()
    mime.setText("just words")
    edit.insertFromMimeData(mime)
    assert edit.toPlainText() == "just words"
    assert assets(area) == []


def test_an_editor_with_nowhere_to_put_files_pastes_the_text_instead(app, tmp_path):
    """No area — a build without file storage, or nothing selected. A URL-only mime data
    auto-synthesises text, and falling through is what lets Qt insert the path."""
    widget = ProseEdit()
    path = tmp_path / "diagram.png"
    path.write_bytes(png_bytes())
    widget.insertFromMimeData(url_mime(path))
    assert str(path) in widget.toPlainText()
    widget.deleteLater()


def test_an_unflushed_node_inserts_nothing(app):
    """A step autosave has not written yet has no directory. The gallery says so in words;
    the editor must not paste a file path in the link's place."""
    gallery = AssetGallery(editable=True)
    gallery.set_area(lambda: (_ for _ in ()).throw(KeyError("unflushed")))
    widget = ProseEdit()
    widget.set_attach(gallery.attach_bytes)
    widget.insertFromMimeData(image_mime())
    assert widget.toPlainText() == ""
    assert "Not saved yet" in gallery.note.text()
    widget.deleteLater()
    gallery.deleteLater()


def test_image_mime_can_be_inserted_which_is_what_enables_menu_paste(edit):
    """Qt's own answer for image-only clipboard data is False, which greys Paste in the
    standard context menu — on the one thing here that most wants pasting."""
    assert edit.canInsertFromMimeData(image_mime())
