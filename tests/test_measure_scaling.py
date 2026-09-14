"""The scaling harness releases what it built — the clipboard included.

``discard`` is the script's teardown, and the one thing it does that ``AppSession.close``
does not is clear the clipboard: the paste scenario copies through ``steps.copy``, and a
Python-made ``QMimeData`` left there dies in Qt's static destructors after Python has gone
(the `suite-crash` skill's *A worker that segfaults after reporting green*). The suite's
own fixture clears it after every test; the script has to do it itself.
"""

from argparse import Namespace
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from scripts.measure_scaling import SCENARIOS, build, discard


def on_clipboard() -> list[str]:
    data = QGuiApplication.clipboard().mimeData()  # None once cleared, under offscreen.
    return list(data.formats()) if data is not None else []


def test_discarding_a_build_leaves_nothing_on_the_clipboard(app, tmp_path: Path) -> None:
    args = Namespace(tabs=("project",), projects=1, unplaced=0.0, immediate=True)
    harness = build(app, tmp_path, 10, args)
    try:
        harness.measure("paste", SCENARIOS["paste"])
        assert on_clipboard()  # The copy did land.
    finally:
        discard(harness, app)
    assert on_clipboard() == []
    assert harness.session.services is None
