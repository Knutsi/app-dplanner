"""Python's cyclic garbage collector, on our terms where it meets Qt objects.

Freeing a PySide wrapper deletes its C++ object whenever Python owns that object — no Qt
parent, or ownership handed back — immediately, on the thread doing the freeing. Two things
follow, and this module owns both.

**Collect on the GUI thread only, at safe points.** Left to itself the collector runs
wherever an allocation trips its threshold: on a worker thread (an LLM call allocates
plenty), where deleting a QObject races the GUI thread's event delivery; or inside a Qt
event handler on the GUI thread, mid-dispatch. The crash then lands somewhere unrelated,
later: the "random" segfault. So the automatic collector is switched off and collections
run from a timer slot on the GUI thread, following the interpreter's own generational
thresholds, so memory behaves as before. The test suite pumps events by hand, so that timer
rarely fires there; it collects after every test instead (tests/conftest.py).

**Never hand a Qt-owned object back to Python.** Released shiboken (every 6.x as of
6.11) clears a garbage cycle one wrapper at a time, and ``SbkObject_tp_clear`` starts by
detaching the wrapper from its parent, which hands the wrapper ownership of a C++ object
its parent still holds. A wrapper cleared before its parent — a ``QWidgetItem`` from
``itemAt``, a ``QSpacerItem`` from ``addStretch``, a ``viewport()``, a ``document()`` —
then deletes that object on its way out, and the parent deletes it again: the double
delete the 2026-09-04 crashes were (the `suite-crash` skill's *A `QLayoutItem` wrapper is a double
delete waiting for a gc pass*). The fix on shiboken's ``dev`` branch (PYSIDE-2221) invalidates a
cleared wrapper's children instead; nothing released has it. Python gives us the same
moment from the outside: it runs every finalizer of a garbage cycle before it clears any
object in it (PEP 442). So every QObject wrapper's ``__del__`` invalidates the wrappers of
its C++-created children while the tree is still intact, and by the time ``tp_clear``
reaches any of them there is nothing left to hand back. A wrapper freed the ordinary way,
by its reference count, already gets this from shiboken's own dealloc; the finalizer only
matters inside a collection.

Why those crashes moved with any allocation elsewhere in the build: the collector clears
garbage in its list order, and a full collection walks generation 0 before generation 1,
so a young collection that happened to land between the creation of a layout's wrapper and
the creation of its items' wrappers put the items ahead of the layout. That is the order
``scripts/layout_item_double_delete.py`` builds on purpose (it dies without the finalizer
and survives with it), and ``tests/framework/test_gc_policy.py`` pins. The one shape the
finalizer cannot see is a ``QLayoutItem`` constructed in Python and handed to ``addItem``:
shiboken counts that as a Python-made object and ``invalidate`` leaves it alone. Nothing
here builds one; use ``addStretch``/``addSpacing`` and keep it that way.
"""

import contextlib
import gc

import shiboken6
from PySide6.QtCore import QObject, QTimer

CHECK_INTERVAL_MS = 200


def collect_if_due() -> int:
    """One step of the interpreter's own policy: when the youngest generation's
    allocation count has reached its threshold, collect it — and the older generations
    whose counts have reached theirs. Returns the generation collected, or -1."""
    counts = gc.get_count()
    thresholds = gc.get_threshold()
    if counts[0] < thresholds[0]:
        return -1
    generation = 0
    if counts[1] >= thresholds[1]:
        generation = 1
        if counts[2] >= thresholds[2]:
            generation = 2
    gc.collect(generation)
    return generation


class GuiThreadGarbageCollector(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        gc.disable()
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(collect_if_due)
        self._timer.start()


def release_cpp_children(wrapper: QObject) -> None:
    """The finalizer every QObject wrapper gets: its C++-created children's wrappers are
    invalidated while the tree is intact, so a later ``tp_clear`` in the same collection
    cannot make one of them Python-owned. Idempotent, and harmless on a dead wrapper."""
    with contextlib.suppress(Exception):
        shiboken6.invalidate(wrapper)


def install_gc_policy(app: QObject) -> GuiThreadGarbageCollector:
    """Install both halves on ``app`` (once; the application object outlives every
    window, so the timer runs for the whole process)."""
    QObject.__del__ = release_cpp_children  # type: ignore[attr-defined]
    existing = app.findChild(GuiThreadGarbageCollector)
    if isinstance(existing, GuiThreadGarbageCollector):
        return existing
    return GuiThreadGarbageCollector(app)
