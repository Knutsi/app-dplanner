"""The controls a strip holds settings with: a popover a face drops, a segmented row of
choices, and a slider over steps with a step either way (``framework/popover.py``,
``segmented.py``, ``slider_row.py``)."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from dplanner.framework.popover import PopoverButton
from dplanner.framework.segmented import Segmented
from dplanner.framework.slider_row import SliderRow


@pytest.fixture
def host(app):
    widget = QWidget()
    widget.show()
    yield widget
    widget.deleteLater()


def test_a_face_drops_its_popover_and_stays_lit_while_it_is_open(host, qtbot):
    face = PopoverButton("Budget · 1p/2a · 50%", host, tip="Who works on the plan")
    face.popover.body.addWidget(Segmented([(1, "1", ""), (2, "2", "")], face.popover))
    face.click()
    assert face.popover.isVisible() and face.isChecked()
    qtbot.keyClick(face.popover, Qt.Key.Key_Escape)
    assert not face.popover.isVisible() and not face.isChecked()
    face.click()
    face.click()  # Its own button closes it rather than opening it again.
    assert not face.popover.isVisible() and not face.isChecked()


def test_a_popover_keeps_what_it_holds_across_openings(host):
    face = PopoverButton("History", host)
    row = SliderRow(face.popover)
    face.popover.body.addWidget(row)
    row.set_count(5)
    face.click()
    row.set_value(2, say=True)
    face.popover.close()
    face.click()
    assert row.value() == 2
    face.popover.close()


def test_a_segmented_row_speaks_in_values_and_lights_the_one_picked(host):
    heard: list[object] = []
    pages = Segmented(
        [("milestones", "Milestones", ""), ("work", "Work", ""), ("calendar", "Calendar", "")],
        host,
    )
    pages.picked.connect(heard.append)
    assert pages.value() is None
    pages.set_value("work")  # A host placing it is not a pick.
    assert pages.value() == "work" and heard == []
    pages.button("calendar").click()
    assert pages.value() == "calendar" and heard == ["calendar"]
    assert [pages.button(v).property("segment") for v in ("milestones", "work", "calendar")] == [
        "first",
        "middle",
        "last",
    ]


def test_a_slider_row_says_every_move_but_the_hosts_and_greys_its_ends(host):
    moved: list[int] = []
    row = SliderRow(host, earlier="The record before", later="The record after")
    row.moved.connect(moved.append)
    row.set_count(4)
    row.set_value(3)
    assert moved == [] and not row.later.isEnabled() and row.earlier.isEnabled()
    row.earlier.click()
    row.slider.setValue(0)  # A drag or a key.
    assert moved == [2, 0] and not row.earlier.isEnabled()
    assert row.earlier.toolTip() == "The record before"
    row.set_count(2)
    assert row.value() == 0 and row.later.isEnabled()
