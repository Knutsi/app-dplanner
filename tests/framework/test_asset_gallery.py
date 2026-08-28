"""The asset gallery: thumbnails from a file area or an explicit file list, click to view."""

import pytest

from dplanner.domain.assets import assets, attach
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.framework import asset_gallery
from dplanner.framework.asset_gallery import AssetGallery

MODULE_ID = "step_agent_instruction"


def png_bytes():
    from dplanner.core.png import encode_rgb

    return encode_rgb(2, 2, 6, b"\x00" * 12)


@pytest.fixture
def step(services):
    project = Project(title="Discovery")
    AddNodeCommand(services.document.id, project).redo(services.document)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def test_area_mode_shows_thumbnails_and_chips_and_removes(app, services, step):
    area = services.repo.files(step.id, MODULE_ID)
    attach(area, png_bytes(), "figure.png")
    attach(area, b"not an image", "notes.bin")

    gallery = AssetGallery(editable=True)
    gallery.set_area(lambda: services.repo.files(step.id, MODULE_ID))
    items = gallery._grid_host.findChildren(asset_gallery._AssetItem)
    assert len(items) == 2
    assert gallery._grid_host.findChildren(asset_gallery._Thumb)  # the image
    assert gallery.attach_button.isVisibleTo(gallery)

    doomed = assets(area)[0]
    gallery._remove(doomed)
    assert doomed not in assets(area)


def test_files_mode_is_read_only(app, services, step):
    area = services.repo.files(step.id, MODULE_ID)
    name = attach(area, png_bytes(), "figure.png")
    workspace_path = f"{area.directory}/{name}"

    gallery = AssetGallery(editable=True)
    gallery.set_files([workspace_path], services.repo.storage.read_bytes)
    assert gallery._grid_host.findChildren(asset_gallery._Thumb)
    # Files mode never edits, even on a gallery constructed editable.
    assert not gallery.attach_button.isVisibleTo(gallery)


def test_an_unflushed_node_answers_in_words(app):
    gallery = AssetGallery(editable=True)
    gallery.set_area(lambda: (_ for _ in ()).throw(KeyError("unflushed")))
    gallery._attach_bytes(b"", "x.png")  # as if a file was chosen in the dialog
    assert "Not saved yet" in gallery.note.text()


def test_clicking_a_thumbnail_opens_the_preview(app, services, step, monkeypatch):
    area = services.repo.files(step.id, MODULE_ID)
    name = attach(area, png_bytes(), "figure.png")

    shown = []

    class FakeDialog:
        def __init__(self, image, shown_name, parent=None, *, caption="", path=""):
            shown.append((image.width(), shown_name, path))

        def exec(self):
            return 0

    monkeypatch.setattr(asset_gallery, "ImagePreviewDialog", FakeDialog)
    gallery = AssetGallery()
    gallery.set_area(lambda: services.repo.files(step.id, MODULE_ID))
    gallery._view(name)
    assert len(shown) == 1
    width, shown_name, path = shown[0]
    assert width == 2  # the full image, not the thumbnail
    assert shown_name == name.split("/")[-1]
    assert path.endswith(name.split("/")[-1]) and path.startswith("/")


def test_thumbnails_stay_thumbnail_sized(app, services, step):
    area = services.repo.files(step.id, MODULE_ID)
    name = attach(area, png_bytes(), "figure.png")
    gallery = AssetGallery()
    gallery.set_area(lambda: services.repo.files(step.id, MODULE_ID))
    _ratio, pixmap = gallery._thumbs[name]
    assert pixmap is not None
    assert pixmap.deviceIndependentSize().width() <= asset_gallery.THUMBNAIL_SIZE
