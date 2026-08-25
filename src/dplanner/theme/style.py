"""A thin proxy over Fusion for platform conventions the stylesheet cannot express.

Style hints are decided in C++ by the ``QStyle``, so they are reachable neither from a QPalette
nor from a stylesheet — a proxy style is the supported way to override them.
"""

import sys

from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleHintReturn, QStyleOption, QWidget


class WriterStyle(QProxyStyle):
    """Fusion, adjusted per platform.

    Forcing Fusion everywhere is what makes the theme render identically on macOS and Linux, but
    it also imports Fusion's assumptions wholesale. ``SH_UnderlineShortcut`` is the one that
    shows: Fusion draws the mnemonic underline permanently (F̲ile, Q̲uit), which is right on
    Linux and wrong on macOS, where menu mnemonics are not a platform concept and the underlines
    read as a stray artifact.
    """

    _HIDE_MNEMONIC_UNDERLINES = sys.platform == "darwin"

    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,
    ) -> int:
        if hint == QStyle.StyleHint.SH_UnderlineShortcut and self._HIDE_MNEMONIC_UNDERLINES:
            return 0
        return super().styleHint(hint, option, widget, returnData)


def build_style() -> WriterStyle:
    """Return the application style, wrapping Fusion."""
    return WriterStyle("Fusion")
