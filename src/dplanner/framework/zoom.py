"""One text size for every text surface, persisted per user.

Every text surface zooms together, because this is a reading-comfort preference and not a
property of the document — so it lives beside the theme in ``QSettings`` rather than inside
the workspace. A workspace shared with a colleague must not carry your eyesight with it.
"""

from PySide6.QtCore import QSettings

from dplanner.core.signals import Signal

SETTINGS_KEY = "appearance/text_size"
DEFAULT_SIZE = 13.0
MIN_SIZE = 9.0
MAX_SIZE = 32.0
STEP = 1.0


def _clamp(size: float) -> float:
    return max(MIN_SIZE, min(MAX_SIZE, size))


class ZoomService:
    def __init__(self) -> None:
        raw = QSettings().value(SETTINGS_KEY, DEFAULT_SIZE)
        try:
            saved = float(raw) if isinstance(raw, int | float | str) else DEFAULT_SIZE
        except ValueError:
            saved = DEFAULT_SIZE
        self.size = _clamp(saved)
        self.changed: Signal[float] = Signal()

    def change(self, steps: int) -> None:
        self.set_size(self.size + steps * STEP)

    def set_size(self, size: float) -> None:
        size = _clamp(size)
        if size == self.size:
            return
        self.size = size
        QSettings().setValue(SETTINGS_KEY, size)
        self.changed.emit(size)
