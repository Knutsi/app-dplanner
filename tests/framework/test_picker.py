"""The picker primitive: a field over rich rows, ranked by what was typed, and one pick.

Two surfaces read this file's behaviour — the command palette and the graph's Find —
so what is asserted here is the shape both rely on: the label outranks what a row merely
answers to, the landmarks are what an untyped picker opens on, and the pick is reported
after the dialog has closed.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE
from dplanner.framework.picker import PickerDialog, PickerRow, fuzzy_score, rank


@pytest.fixture
def host(app):
    widget = QWidget()
    yield widget
    widget.deleteLater()


ROWS = (
    PickerRow("m1", "Ship the importer", detail="Milestone", also="M1", landmark=True),
    PickerRow("f1", "Bulk import", detail="Feature", trailing="F2", also="F2", landmark=True),
    PickerRow("s1", "Write the parser", detail="Step", trailing="S7", also="S7"),
    PickerRow("s2", "Import the fixtures", detail="Step", trailing="S8", also="S8"),
)


def listed(picker):
    return [picker.list.item(i).text() for i in range(picker.list.count())]


def built(host, rows=ROWS, query=""):
    picked: list[str] = []
    picker = PickerDialog(rows, picked.append, host)
    picker._refilter(query)
    return picker, picked


def test_a_subsequence_matches_and_a_contiguous_run_scores_higher():
    assert fuzzy_score("opit", "Open Item") is not None
    assert fuzzy_score("zz", "Open Item") is None
    assert fuzzy_score("", "anything") == 0
    run, scattered = fuzzy_score("open", "Open Item"), fuzzy_score("oe", "Open Item")
    assert run is not None and scattered is not None and run > scattered


def test_a_label_match_outranks_one_that_needed_what_the_row_answers_to():
    label = rank("import", PickerRow("a", "Bulk import", also="F2"))
    through = rank("f2", PickerRow("b", "Ship the importer", also="F2"))
    assert label is not None and through is not None and label < through
    assert rank("nothing here", PickerRow("c", "Bulk import")) is None


def test_an_untyped_picker_opens_on_its_landmarks(host, app):
    """Three hundred steps is not a list anybody scrolls; the dozen that name the plan is."""
    picker, _picked = built(host)
    assert listed(picker) == ["Ship the importer", "Bulk import"]

    picker._refilter("import")
    assert "Write the parser" not in listed(picker)
    # Everything is in play once something is typed, and the obvious hit — the name that
    # *starts* with what was typed — leads.
    assert listed(picker) == ["Import the fixtures", "Bulk import", "Ship the importer"]


def test_a_list_with_no_landmarks_opens_whole(host, app):
    """Which is what the command palette wants: every runnable verb, from the first look."""
    plain = tuple(PickerRow(row.id, row.label) for row in ROWS)
    picker, _picked = built(host, plain)
    assert len(listed(picker)) == len(plain)


def test_a_row_shows_its_second_line_and_its_note(host, app):
    picker, _picked = built(host, query="parser")
    item = picker.list.item(0)
    assert item.data(DETAIL_ROLE) == "Step" and item.data(TRAILING_ROLE) == "S7"


def test_the_pick_is_reported_after_the_dialog_has_closed(host, app):
    """A verb that opens a dialog of its own must not be nested inside this one's modality."""
    picker, picked = built(host, query="parser")
    seen: list[bool] = []

    def record(row_id):
        seen.append(picker.isVisible())
        picked.append(row_id)

    picker._picked = record
    picker._take()
    assert picked == ["s1"] and seen == [False]


def test_the_arrows_move_the_list_while_the_field_keeps_the_keyboard(host, app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    picker, _picked = built(host)
    assert picker.list.currentRow() == 0
    down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    assert picker.eventFilter(picker.field, down)
    assert picker.list.currentRow() == 1
    up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    picker.eventFilter(picker.field, up)
    assert picker.list.currentRow() == 0


def test_a_query_that_matches_nothing_says_so_where_the_rows_would_be(host):
    picker, _picked = built(host, query="zzqx")
    assert listed(picker) == []
    assert picker.empty.isVisibleTo(picker) and not picker.list.isVisibleTo(picker)
    picker._refilter("parser")
    assert listed(picker) == ["Write the parser"] and not picker.empty.isVisibleTo(picker)
