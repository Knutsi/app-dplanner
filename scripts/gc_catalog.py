"""A pytest plugin that catalogs the Qt-bearing garbage each test leaves, without freeing it.

`suite-crash`'s recipe for a SIGSEGV inside the suite's boundary ``gc.collect()``: under
``gc.DEBUG_SAVEALL`` nothing is freed, so the run cannot crash, and ``gc.garbage`` holds every
collected cycle **in the order the collector would have cleared it** — which is the order
that decides whether a wrapper dies before or after the C++ object it belongs to. Run one
pass over the crashing worker's tests, single-threaded, in the order that worker ran them
(``pytest -v`` under ``-n`` prints which worker ran what)::

    PYTHONPATH=scripts QT_QPA_PLATFORM=offscreen uv run pytest -q -n0 -s -p gc_catalog tests/...

For every test it prints that test's wrappers in that order with validity, ownership and
C++ parent, and flags the shapes that have crashed the suite: a live Python-owned top-level
widget (its whole C++ tree dies inside the collector, after whatever was cleared before it),
a ``QLayoutItem`` wrapper (cleared before its layout, it is handed ownership of an item the
C++ layout still holds — the 2026-09-04 crash), and a live parentless ``QObject``.
"""

import gc
import sys
from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    gc.set_debug(gc.DEBUG_SAVEALL)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Any:
    start = len(gc.garbage)
    yield
    report(item.nodeid, gc.garbage[start:])


def report(nodeid: str, garbage: list[Any]) -> None:
    import shiboken6
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget

    wrappers = [obj for obj in garbage if isinstance(obj, shiboken6.Shiboken.Object)]
    print(
        f"\n### {nodeid}: {len(garbage)} objects in the collector's order, "
        f"{len(wrappers)} Qt wrappers",
        file=sys.stderr,
    )
    for position, obj in enumerate(garbage):
        if not isinstance(obj, shiboken6.Shiboken.Object):
            continue
        valid = shiboken6.isValid(obj)
        owned = valid and shiboken6.ownedByPython(obj)
        parent = "-"
        flag = ""
        if valid and isinstance(obj, QObject):
            qt_parent = obj.parent()
            parent = type(qt_parent).__name__ if qt_parent is not None else "none"
            if owned and qt_parent is None:
                what = "WIDGET" if isinstance(obj, QWidget) else "QOBJECT"
                flag = f"<== live Python-owned top-level {what}"
        if valid and isinstance(obj, QLayoutItem) and not isinstance(obj, QLayout):
            flag = "<== QLayoutItem wrapper"
        print(
            f"{position:6d}  {type(obj).__name__:32s} valid={valid!s:5} owned={owned!s:5} "
            f"parent={parent:20s} {flag}",
            file=sys.stderr,
        )
