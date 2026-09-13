"""The folder kind: what it asks for, what it answers without touching the disk, and the
snapshot the spec module applies. The walk itself is covered Qt-free in
``tests/domain/test_document_folder.py``.
"""

import pytest
from PySide6.QtWidgets import QFileDialog

from dplanner.domain.document_source import SourceUnavailableError
from dplanner.modules.spec_folder.module import SpecFolderKind

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


@pytest.fixture
def kind():
    return SpecFolderKind()


@pytest.fixture
def specs(tmp_path):
    root = tmp_path / "product specs"
    (root / "design").mkdir(parents=True)
    (root / "README.md").write_text("# The Product\n")
    (root / "design" / "auth.md").write_text("# Auth\n\n![flow](flow.png)\n")
    (root / "design" / "flow.png").write_bytes(PNG)
    return root


def test_locate_asks_for_a_folder_and_names_the_source_after_it(kind, specs, monkeypatch, app):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(specs))
    assert kind.locate(None) == ("product specs", {"path": str(specs)})
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    assert kind.locate(None) is None


def test_status_never_touches_the_disk(kind, tmp_path):
    """It runs from an action's state on every context change: a folder that has gone says
    so in the fetch's own words, not by grinding the filesystem on every menu opening."""
    gone = {"path": str(tmp_path / "never-existed")}
    assert kind.status(gone).ready


@pytest.mark.parametrize(
    "locator",
    [{}, {"path": ""}, {"path": "relative/specs"}, {"path": 7}, {"folder": "/specs"}],
)
def test_a_locator_from_a_colleagues_plan_is_refused_in_words(kind, locator):
    refused = kind.status(locator)
    assert not refused.ready and "not a folder on this computer" in refused.message
    assert kind.open_url(locator) == ""
    with pytest.raises(SourceUnavailableError, match="not a folder on this computer"):
        kind.check(locator, {})


def test_a_fetch_carries_the_tree_the_spec_module_writes(kind, specs):
    taken = kind.fetch({"path": str(specs)}, {}, lambda _f: None, lambda: False)
    assert [doc.key for doc in taken.documents] == ["README.md", "design/auth.md"]
    auth = taken.documents[1]
    assert auth.parent_key == "README.md" and auth.filename == "auth.md"
    assert "assets/" in auth.data.decode() and [i.data for i in taken.images] == [PNG]


def test_a_folder_that_has_gone_refuses_the_fetch_and_names_itself(kind, tmp_path):
    missing = tmp_path / "moved away"
    with pytest.raises(SourceUnavailableError, match="is not a folder on this computer"):
        kind.fetch({"path": str(missing)}, {}, lambda _f: None, lambda: False)


def test_open_url_points_at_the_folder(kind, specs):
    assert kind.open_url({"path": str(specs)}).startswith("file://")


def test_connect_has_nothing_to_obtain(kind, specs):
    assert not kind.connect(None, {"path": str(specs)})


def test_the_real_build_offers_it_first_in_the_add_menu(services):
    spec = services.actions.spec("spec.add_source.folder")
    assert spec.label == "&Folder on This Computer…"
    assert spec.order < services.actions.spec("spec.add_source.confluence_page").order
