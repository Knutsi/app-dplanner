"""Font selection.

There is no font family guaranteed to exist on both a stock macOS and a stock Linux system, so
every family below is expressed as a fallback chain rather than a single name. Qt 6 honours
comma-separated lists properly (``QFont.setFamilies``), with ``setStyleHint`` as the terminal
fallback when nothing in the chain resolves.
"""

from PySide6.QtGui import QFont, QFontDatabase

# Ordered best-to-worst, spanning macOS, GNOME, Ubuntu and bare-container defaults.
UI_FAMILIES: list[str] = [
    "Inter",
    "SF Pro Text",
    "Segoe UI Variable",
    "Cantarell",
    "Ubuntu",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
]

MANUSCRIPT_FAMILIES: list[str] = [
    "EB Garamond",
    "Iowan Old Style",
    "Palatino",
    "Charter",
    "Source Serif 4",
    "Noto Serif",
    "Liberation Serif",
    "DejaVu Serif",
    "Georgia",
]

MONO_FAMILIES: list[str] = [
    "SF Mono",
    "Menlo",
    "JetBrains Mono",
    "Fira Code",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Noto Sans Mono",
]


def ui_font() -> QFont:
    """Return the font for application chrome.

    Deliberately the platform's own UI font: it is always present, respects the user's system
    font-size setting, and makes the chrome feel native on each platform. The chains above are
    for content, where identical rendering matters more than native feel.

    Note that the offscreen platform used by the tests reports a system font of "Sans Serif",
    which does not exist, so headless runs log ``Populating font family aliases took N ms``.
    That is an artifact of that platform only — cocoa and a fontconfig-configured Linux both
    resolve a real family. Prepending the fallback chain does not silence it (Qt warns while
    resolving the first family) and filtering by availability would wrongly discard macOS's
    hidden ``.AppleSystemUIFont``, so the warning is left alone.
    """
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)


def manuscript_font(point_size: float = 13.0) -> QFont:
    """Return the serif font for manuscript text."""
    font = QFont()
    font.setFamilies(MANUSCRIPT_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Serif)
    font.setPointSizeF(point_size)
    return font


def mono_font(point_size: float = 12.0) -> QFont:
    """Return the monospace font, for metadata and frontmatter views."""
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSizeF(point_size)
    return font
