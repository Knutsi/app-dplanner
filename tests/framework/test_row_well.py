"""The row well: a row built once and kept across every refresh, rows in the order of their
keys, the last row parted by nothing, verbs that keep their room and never take the
keyboard, a busy line with no bar and a known fraction with one — rendered in both themes."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor

from dplanner.framework.row_well import RowWell, WellRow
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT


@pytest.fixture
def well(app):
    made = RowWell()
    made.resize(400, 300)
    made.show()
    app.processEvents()
    yield made
    made.deleteLater()


def fill(well: RowWell, keys: list[int], built: list[int], updated: list[int]) -> None:
    def build(key: int) -> WellRow:
        built.append(key)
        return WellRow(f"row {key}")

    well.reconcile(keys, build, lambda key, _row: updated.append(key))


def test_a_row_is_built_once_and_kept_across_every_refresh(well):
    built: list[int] = []
    updated: list[int] = []
    fill(well, [1, 2], built, updated)
    first = well.row(1)
    fill(well, [1, 2, 3], built, updated)
    assert built == [1, 2, 3] and updated == [1, 2, 1, 2, 3]
    assert well.row(1) is first
    gone = well.row(2)
    assert gone is not None
    fill(well, [1, 3], built, updated)
    assert well.row(2) is None and gone.isHidden() and well.count() == 2


def test_rows_stand_in_the_order_of_their_keys(well, app):
    fill(well, [1, 3], [], [])
    fill(well, [2, 1, 3], [], [])
    rows = well.rows()
    assert [row.title.text() for row in rows] == ["row 2", "row 1", "row 3"]
    app.processEvents()
    tops = [row.geometry().top() for row in rows]
    assert tops == sorted(tops) and len(set(tops)) == 3


def test_only_the_last_row_goes_without_a_hairline(well):
    fill(well, [1, 2], [], [])
    first, second = well.row(1), well.row(2)
    assert first is not None and second is not None
    assert second.property("last") is True and not first.property("last")
    fill(well, [1, 2, 3], [], [])
    third = well.row(3)
    assert third is not None
    assert third.property("last") is True and second.property("last") is False
    fill(well, [1], [], [])
    assert first.property("last") is True


def test_a_rows_verbs_keep_their_room_and_never_take_the_keyboard(app):
    row = WellRow("Fetching 12 pages")
    try:
        cancel = row.add_button("Cancel", lambda: None, tip="Stop fetching")
        dismiss = row.add_dismiss(lambda: None)
        for button in (cancel, dismiss):
            assert button.sizePolicy().retainSizeWhenHidden()
            assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert cancel.objectName() == "ToolbarButton"
        assert dismiss.objectName() == "WellRowDismiss"
    finally:
        row.deleteLater()


def test_a_busy_row_has_no_bar_and_a_known_fraction_has_one(app):
    row = WellRow("Fetching 12 pages")
    try:
        row.status.say("12s · started 14:03", "busy")
        row.show_fraction(None)
        assert row.bar.isHidden() and row.status.tone() == "busy"
        row.show_fraction(0.4)
        assert not row.bar.isHidden() and row.bar.value() == 40
        row.show_fraction(None)
        assert row.bar.isHidden()
        assert row.bar.maximum() == 100  # Never Qt's animated indeterminate state.
    finally:
        row.deleteLater()


def test_a_note_is_plain_selectable_and_leaves_when_it_has_nothing_to_say(app):
    command = 'cd "/work/s15" && claude --resume 7bf756e8'
    row = WellRow("Deploy")
    try:
        row.set_note(command)
        assert not row.note.isHidden() and row.note.text() == command
        assert row.note.textFormat() == Qt.TextFormat.PlainText
        assert row.note.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
        row.set_note("")
        assert row.note.isHidden()
    finally:
        row.deleteLater()


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_the_well_is_a_framed_ground_with_hairlines_between_rows(themed, theme):
    apply_theme(themed, theme)
    made = RowWell()
    made.resize(400, 300)
    made.reconcile(
        [1, 2], lambda key: WellRow(f"row {key}"), lambda _key, row: row.status.say("done", "ok")
    )
    made.show()
    themed.processEvents()
    try:
        image = made.grab().toImage()
        first, second = made.rows()
        below = made.host.mapTo(made, QPoint(made.host.width() // 2, made.host.height() - 4))
        assert image.pixelColor(below) == QColor(theme.bg_surface)
        under_first = first.mapTo(made, QPoint(first.width() // 2, first.height() - 1))
        assert image.pixelColor(under_first) == QColor(theme.border)
        under_second = second.mapTo(made, QPoint(second.width() // 2, second.height() - 1))
        assert image.pixelColor(under_second) != QColor(theme.border)
    finally:
        made.deleteLater()
