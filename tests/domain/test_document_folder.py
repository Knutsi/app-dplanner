"""A directory read as a document source: the keys, the nesting, the digests and the
sentences it writes for what it left out. Qt-free, over real directories under tmp_path.
"""

import hashlib

import pytest
from tests.platforms import SYMLINKS

from dplanner.domain.assets import asset_name
from dplanner.domain.document_folder import (
    FolderScan,
    entries,
    freshness,
    is_document,
    snapshot,
)
from dplanner.domain.document_source import SourceUnavailableError

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
OTHER_PNG = b"\x89PNG\r\n\x1a\n" + b"other pixels"


def write(root, path, data=b"body"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data if isinstance(data, bytes) else data.encode())
    return target


@pytest.fixture
def folder(tmp_path):
    """A small documentation tree: an index at the top, a subdirectory with its own."""
    root = tmp_path / "specs"
    write(root, "README.md", "# The Product\n\nWhat it is.\n")
    write(root, "glossary.md", "# Glossary\n")
    write(root, "design/README.md", "# Design\n")
    write(root, "design/auth.md", "# Auth\n\n![flow](images/flow.png)\n")
    write(root, "design/images/flow.png", PNG)
    write(root, "design/notes.txt", "plain")
    write(root, "handbook.pdf", b"%PDF-1.4 body")
    write(root, ".hidden/secret.md", "# Secret\n")
    return root


def keys(scan):
    return [entry.key for entry in entries(scan, [])]


def parents(scan):
    return {entry.key: entry.parent_key for entry in entries(scan, [])}


# -- what it finds -------------------------------------------------------------------------------


def test_a_key_is_the_path_and_the_order_is_readable(folder):
    """Index document first in each directory, then its files, then its subdirectories."""
    assert keys(FolderScan(root=folder)) == [
        "README.md",
        "glossary.md",
        "handbook.pdf",
        "design/README.md",
        "design/auth.md",
        "design/notes.txt",
    ]


def test_a_dot_directory_is_never_walked(folder):
    assert not any(key.startswith(".hidden") for key in keys(FolderScan(root=folder)))
    assert not is_document(".hidden/secret.md") and is_document("design/auth.md")
    assert not is_document("design/diagram.png") and is_document("notes.txt")


def test_documents_nest_under_their_directorys_index_document(folder):
    found = parents(FolderScan(root=folder))
    assert found["README.md"] == ""  # The top index hangs under the source itself.
    assert found["glossary.md"] == "README.md"
    assert found["design/README.md"] == "README.md"
    assert found["design/auth.md"] == "design/README.md"


def test_a_directory_with_no_index_is_transparent(tmp_path):
    """The rule adds nesting only where somebody wrote the page that means it."""
    root = tmp_path / "flat"
    write(root, "one.md", "# One\n")
    write(root, "deep/two.md", "# Two\n")
    assert parents(FolderScan(root=root)) == {"one.md": "", "deep/two.md": ""}


def test_a_subdirectory_is_the_whole_source_when_one_is_named(folder):
    scan = FolderScan(root=folder, subdirectory="design")
    assert keys(scan) == ["README.md", "auth.md", "notes.txt"]
    assert parents(scan)["auth.md"] == "README.md"


def test_a_title_is_the_first_heading_and_falls_back_to_the_stem(folder):
    titles = {entry.key: entry.title for entry in entries(FolderScan(root=folder), [])}
    assert titles["README.md"] == "The Product"
    assert titles["design/notes.txt"] == "notes"
    assert titles["handbook.pdf"] == "handbook"


# -- what it hands over --------------------------------------------------------------------------


def test_a_fetch_carries_bytes_a_filename_and_the_pictures_it_links(folder):
    taken = snapshot(FolderScan(root=folder), {})
    auth = next(doc for doc in taken.documents if doc.key == "design/auth.md")
    name = asset_name(PNG, "image.png")
    assert f"![flow]({name})" in auth.data.decode()
    assert [image.data for image in taken.images] == [PNG]
    assert auth.filename == "auth.md"
    pdf = next(doc for doc in taken.documents if doc.key == "handbook.pdf")
    assert pdf.data == b"%PDF-1.4 body" and pdf.filename == "handbook.pdf"


def test_an_unchanged_document_is_kept_without_its_body(folder):
    first = snapshot(FolderScan(root=folder), {})
    known = {doc.key: doc.version for doc in first.documents}
    again = snapshot(FolderScan(root=folder), known)
    assert again.documents == () and set(again.kept) == set(known)
    assert again.keys() == first.keys()


def test_a_version_moves_when_a_picture_beside_the_text_is_redrawn(folder):
    """The body's own digest would not move, the row would be kept, and the page would go
    on showing a picture that is no longer there."""
    before = {entry.key: entry.version for entry in entries(FolderScan(root=folder), [])}
    write(folder, "design/images/flow.png", OTHER_PNG)
    after = {entry.key: entry.version for entry in entries(FolderScan(root=folder), [])}
    assert after["design/auth.md"] != before["design/auth.md"]
    assert after["glossary.md"] == before["glossary.md"]


def test_a_skipped_picture_never_shifts_the_link_of_the_next_one(tmp_path):
    root = tmp_path / "specs"
    write(root, "one.md", "![a](gone.png)\n\n![b](there.png)\n")
    write(root, "there.png", PNG)
    taken = snapshot(FolderScan(root=root), {})
    body = taken.documents[0].data.decode()
    assert "![a](gone.png)" in body
    assert f"![b]({asset_name(PNG, 'image.png')})" in body


def test_an_external_or_area_link_is_left_alone(tmp_path):
    root = tmp_path / "specs"
    write(root, "one.md", "![a](https://x/y.png) ![b](assets/abc.png) ![c](/tmp/d.png)\n")
    body = snapshot(FolderScan(root=root), {}).documents[0].data.decode()
    assert "https://x/y.png" in body and "assets/abc.png" in body and "/tmp/d.png" in body


def test_freshness_names_what_changed_added_and_went(folder):
    known = {entry.key: entry.version for entry in entries(FolderScan(root=folder), [])}
    write(folder, "glossary.md", "# Glossary\n\nmore\n")
    write(folder, "new.md", "# New\n")
    (folder / "handbook.pdf").unlink()
    found = freshness(FolderScan(root=folder), known)
    assert found.changed == ("glossary.md",)
    assert found.added == ("new.md",)
    assert found.removed == ("handbook.pdf",)
    assert found.stale


# -- what it refuses -----------------------------------------------------------------------------


def test_every_skip_is_one_sentence(tmp_path):
    root = tmp_path / "specs"
    write(root, "big.md", "x" * 40)
    write(root, "latin.txt", "caf\xe9".encode("latin-1"))
    write(root, "links.md", "![a](missing.png)\n![b](logo.svg)\n")
    write(root, "logo.svg", b"<svg/>")
    notes: list[str] = []
    found = entries(FolderScan(root=root, max_file_bytes=35), notes, lambda: False)
    assert [entry.key for entry in found] == ["links.md"]
    assert notes == [
        "big.md: larger than the cap and was left out",
        "latin.txt: not UTF-8 text and was left out",
        "links.md: image missing.png is not in the folder",
        "links.md: image logo.svg is not a raster image and was left out",
    ]


@SYMLINKS
def test_a_symlink_out_of_the_folder_is_left_out(tmp_path):
    outside = tmp_path / "outside"
    write(outside, "secret.md", "# Secret\n")
    root = tmp_path / "specs"
    write(root, "one.md", "# One\n")
    (root / "escape").symlink_to(outside)
    notes: list[str] = []
    assert [entry.key for entry in entries(FolderScan(root=root), notes, lambda: False)] == [
        "one.md"
    ]
    assert notes == ["escape: a symlink out of the folder, left out"]


@SYMLINKS
def test_a_symlink_pointing_back_up_cannot_loop_the_walk(tmp_path):
    root = tmp_path / "specs"
    write(root, "one.md", "# One\n")
    (root / "loop").symlink_to(root)
    assert keys(FolderScan(root=root)) == ["one.md"]


def test_more_documents_than_the_cap_leaves_a_note(tmp_path):
    root = tmp_path / "specs"
    for number in range(4):
        write(root, f"{number}.md", f"# {number}\n")
    notes: list[str] = []
    found = entries(FolderScan(root=root, max_documents=2), notes, lambda: False)
    assert len(found) == 2
    assert notes == ["more than 2 documents — the rest were left out"]


def test_a_folder_deeper_than_the_cap_is_not_descended(tmp_path):
    root = tmp_path / "specs"
    write(root, "a/b/deep.md", "# Deep\n")
    notes: list[str] = []
    assert entries(FolderScan(root=root, max_depth=1), notes, lambda: False) == []
    assert notes == ["a/b: deeper than 1 levels"]


def test_a_missing_folder_and_an_oversized_one_refuse_the_whole_fetch(tmp_path, folder):
    with pytest.raises(SourceUnavailableError, match="not a folder on this computer"):
        entries(FolderScan(root=tmp_path / "gone"), [])
    with pytest.raises(SourceUnavailableError, match="point the source at a subdirectory"):
        entries(FolderScan(root=folder, max_total_bytes=1), [])


def test_cancelling_stops_the_walk(folder):
    with pytest.raises(SourceUnavailableError, match="cancelled"):
        entries(FolderScan(root=folder), [], lambda: True)


def test_an_image_lands_under_its_content_address(folder):
    taken = snapshot(FolderScan(root=folder), {})
    assert hashlib.sha256(PNG).hexdigest()[:16] in asset_name(
        taken.images[0].data, taken.images[0].filename
    )
