"""The asset picker: a modal grid of named files that answers in payloads, not paths.

Bytes come back rather than paths because the caller copies its choice into its own file
area — the copy-by-value rule that keeps a link from pointing into somebody else's
directory.
"""

import pytest

from dplanner.core.png import encode_rgb
from dplanner.framework.asset_picker import AssetPickerDialog, PickerEntry


def png_bytes():
    return encode_rgb(2, 2, 6, b"\x00" * 12)


@pytest.fixture
def dialog(app):
    entries = [
        PickerEntry(
            key="assets/aa11.png",
            title="Login mock",
            detail="Descriptions · used by Deploy",
            filename="Login mock.png",
            read=png_bytes,
        ),
        PickerEntry(
            key="assets/bb22.txt",
            title="notes.txt",
            filename="notes.txt",
            read=lambda: b"findings",
        ),
        PickerEntry(key="assets/cc33.png", title="gone.png", read=lambda: None),
    ]
    widget = AssetPickerDialog(entries)
    yield widget
    widget.deleteLater()


def test_chosen_returns_payloads_for_the_picked_entries_in_entry_order(dialog):
    dialog.grid.item(1).setSelected(True)
    dialog.grid.item(0).setSelected(True)

    picked = dialog.chosen()

    assert [payload.filename for payload in picked] == ["Login mock.png", "notes.txt"]
    assert [payload.is_image for payload in picked] == [True, False]
    assert picked[0].data == png_bytes()


def test_an_entry_whose_bytes_are_gone_is_skipped_not_fatal(dialog):
    dialog.grid.item(2).setSelected(True)
    assert dialog.chosen() == []


def test_a_filename_falls_back_to_the_key_s_basename(app):
    widget = AssetPickerDialog(
        [PickerEntry(key="assets/dd44.png", title="dd44.png", read=png_bytes)]
    )
    widget.grid.item(0).setSelected(True)
    assert [payload.filename for payload in widget.chosen()] == ["dd44.png"]
    widget.deleteLater()


def test_an_empty_picker_says_so_in_words(app):
    widget = AssetPickerDialog([])
    assert not widget.empty.isHidden() or not widget.grid.count()
    assert "Nothing to pick from" in widget.empty.text()
    widget.deleteLater()


def test_insert_is_the_primary_and_is_refused_until_something_is_picked(dialog):
    from dplanner.framework.dialog import DialogFrame

    assert isinstance(dialog, DialogFrame)
    assert [b.text() for b in dialog.footer_buttons()] == ["Insert", "Cancel"]
    primary = dialog.primary()
    assert primary is not None and primary.isDefault() and not primary.isEnabled()
    dialog.grid.item(0).setSelected(True)
    assert primary.isEnabled()
    dialog.grid.clearSelection()
    assert not primary.isEnabled()


def test_an_empty_picker_trades_the_grid_for_the_empty_state_and_refuses_insert(app):
    widget = AssetPickerDialog([])
    try:
        assert widget.empty.stands_in_for is widget.grid
        assert widget.grid.isHidden() and not widget.empty.isHidden()
        primary = widget.primary()
        assert primary is not None and not primary.isEnabled()
    finally:
        widget.deleteLater()
