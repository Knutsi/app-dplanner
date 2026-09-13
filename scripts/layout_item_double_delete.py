"""The 2026-09-04 layout-item double delete, on demand — and the finalizer that closes it.

`suite-crash`'s *A QLayoutItem wrapper is a double delete waiting for a gc pass* named the
mechanism; this script builds the order it needs. Python's collector clears garbage in its
list order, and a full collection walks generation 0 before generation 1 (each younger
generation is appended to the tail of the oldest one, generation 0 first). So a young
collection that lands between the creation of a layout's wrapper and the creation of its
items' wrappers puts the items *ahead* of the layout — which is why the crash moved with
any allocation elsewhere in the build: it was the young-generation threshold crossing at
that spot, or not. Released shiboken's ``tp_clear`` (every 6.x through 6.11) then hands the
item wrapper ownership back before the layout is touched, and the item is deleted twice::

    MALLOC_PERTURB_=165 QT_QPA_PLATFORM=offscreen \
        uv run python scripts/layout_item_double_delete.py plain   # dies at gc.collect()
    ... guard   # the QObject finalizer framework/gc_policy.py installs: survives
    ... order   # gc.DEBUG_SAVEALL: print the collector's order, free nothing

On macOS use ``MallocScribble=1`` in place of ``MALLOC_PERTURB_``. The second argument picks
the shape: ``fill_first`` (a parentless row given a widget and a stretch before
``addLayout`` — the evening crash) or ``itemat`` (a layout read back — the morning one).
``tests/framework/test_gc_policy.py`` pins both under the guard.
"""

import gc
import sys

import shiboken6
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

MODE = sys.argv[1] if len(sys.argv) > 1 else "plain"
SHAPE = sys.argv[2] if len(sys.argv) > 2 else "fill_first"


def release_cpp_children(wrapper: QObject) -> None:
    shiboken6.invalidate(wrapper)


def build() -> None:
    page = QWidget()  # The bare top-level Python-owned widget: its tree dies in the collector.
    column = QVBoxLayout(page)
    if SHAPE == "fill_first":
        row = QHBoxLayout()  # Parentless, filled before addLayout.
        row.addWidget(QPushButton("attach"))
        row.addStretch(1)
        gc.collect(0)  # A young collection lands here: the wrappers so far -> generation 1.
        column.addLayout(row)  # PySide wraps the row's QWidgetItem + QSpacerItem: generation 0.
    else:
        column.addWidget(QPushButton("card"))
        column.addStretch(1)
        gc.collect(0)
        column.itemAt(0)  # The read-back: a QWidgetItem wrapper parented to the layout.
        column.itemAt(1)  # And the QSpacerItem.
    page.cycle = page  # The cycle every app build hands the boundary collector.


def main() -> None:
    gc.disable()
    app = QApplication([])
    if MODE == "guard":
        QObject.__del__ = release_cpp_children  # type: ignore[attr-defined]
    if MODE == "order":
        gc.set_debug(gc.DEBUG_SAVEALL)
    build()
    gc.collect()  # "plain" dies here: ~QBoxLayout calling through the deleted item's vtable.
    if MODE == "order":
        for position, obj in enumerate(gc.garbage):
            if isinstance(obj, shiboken6.Shiboken.Object):
                owned = shiboken6.ownedByPython(obj)
                print(f"{position:3d} {type(obj).__name__:<14} ownedByPython={owned}")
    print("survived", MODE, SHAPE)
    del app


if __name__ == "__main__":
    main()
