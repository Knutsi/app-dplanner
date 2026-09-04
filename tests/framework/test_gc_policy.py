"""The two halves of framework/gc_policy.py: automatic collection is off once the
application is configured and the timer-driven step follows the interpreter's generational
thresholds; and a Qt-owned object is never handed back to Python by a collection."""

import gc
import weakref

import pytest

from dplanner.framework.gc_policy import (
    GuiThreadGarbageCollector,
    collect_if_due,
    install_gc_policy,
)


class Node:
    def __init__(self) -> None:
        self.me = self  # A reference cycle: only the cyclic collector can free it.


def make_garbage(count: int) -> list[weakref.ref[Node]]:
    return [weakref.ref(Node()) for _ in range(count)]


def test_configured_application_collects_only_from_its_own_timer(app) -> None:
    assert not gc.isenabled()
    collector = app.findChild(GuiThreadGarbageCollector)
    assert isinstance(collector, GuiThreadGarbageCollector)
    assert install_gc_policy(app) is collector  # One per application, ever.


def test_collect_if_due_waits_for_the_youngest_threshold(app) -> None:
    gc.collect()
    threshold = gc.get_threshold()[0]
    # Each Node costs two tracked allocations (the object and its dict).
    below = make_garbage(threshold // 4)
    assert collect_if_due() == -1
    assert all(ref() is not None for ref in below)

    enough = make_garbage(threshold)
    assert collect_if_due() == 0
    assert all(ref() is None for ref in below + enough)


def _layout_items_ahead_of_their_layout(shape: str) -> None:
    """The 2026-09-04 double delete, built to order.

    A full collection walks generation 0 before generation 1, so a young collection that
    lands between the creation of a layout's wrapper and the creation of its items'
    wrappers puts the items ahead of the layout in the collector's list. Released
    shiboken's ``tp_clear`` then hands the item wrapper ownership back before the layout is
    touched, and the item is deleted twice. Without the finalizer ``install_gc_policy``
    puts on every QObject wrapper, this function segfaults the process at ``gc.collect()``
    — that crash, not an assertion, is the finding.
    """
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

    class Page(QWidget):
        cycle: "Page | None" = None

    page = Page()  # Bare and Python-owned: its whole C++ tree dies inside the collector.
    column = QVBoxLayout(page)
    if shape == "row filled before addLayout":
        row = QHBoxLayout()
        row.addWidget(QPushButton("attach"))
        row.addStretch(1)
        gc.collect(0)  # The wrappers so far move to generation 1 ...
        column.addLayout(row)  # ... and PySide wraps the row's two items into generation 0.
    else:
        column.addWidget(QPushButton("card"))
        column.addStretch(1)
        gc.collect(0)
        column.itemAt(0)  # The read-back: a QWidgetItem wrapper parented to the layout.
        column.itemAt(1)  # And the QSpacerItem.
    page.cycle = page  # The cycle every app build hands the boundary collector.


@pytest.mark.parametrize("shape", ["row filled before addLayout", "layout read back"])
def test_a_layout_item_cleared_ahead_of_its_layout_is_not_deleted_twice(app, shape) -> None:
    gc.collect()
    _layout_items_ahead_of_their_layout(shape)
    gc.collect()  # Segfaults here without the finalizer guard.
