"""The image preview dialog: fitted, never upscaled, path on offer."""

from PySide6.QtGui import QColor, QImage

from dplanner.framework.image_preview import ImagePreviewDialog


def image(width, height):
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("black"))
    return img


def test_a_small_image_shows_at_its_own_size(app):
    dialog = ImagePreviewDialog(image(40, 30), "dot.png")
    pixmap = dialog.image_label.pixmap()
    size = pixmap.deviceIndependentSize()
    assert (size.width(), size.height()) == (40, 30)
    dialog.deleteLater()


def test_a_huge_image_is_fitted_to_the_screen(app):
    dialog = ImagePreviewDialog(image(20000, 100), "wide.png")
    available = dialog.screen().availableGeometry()
    assert dialog.image_label.pixmap().deviceIndependentSize().width() <= available.width() * 0.8
    dialog.deleteLater()


def test_the_title_names_the_file_and_its_size(app):
    dialog = ImagePreviewDialog(image(40, 30), "dot.png")
    assert dialog.windowTitle() == "dot.png — 40 x 30"
    captioned = ImagePreviewDialog(image(40, 30), "dot.png", caption="page 3 of auth-spec")
    assert captioned.windowTitle() == "page 3 of auth-spec"
    dialog.deleteLater()
    captioned.deleteLater()


def test_copy_path_exists_only_when_a_path_is_given(app):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QPushButton

    bare = ImagePreviewDialog(image(4, 4), "dot.png")
    labels = [b.text() for b in bare.findChildren(QPushButton)]
    assert not any("Copy Path" in label for label in labels)

    with_path = ImagePreviewDialog(image(4, 4), "dot.png", path="/tmp/dot.png")
    copy = next(b for b in with_path.findChildren(QPushButton) if "Copy Path" in b.text())
    copy.click()
    assert QGuiApplication.clipboard().text() == "/tmp/dot.png"
    bare.deleteLater()
    with_path.deleteLater()
