"""A thin proxy over Fusion for what neither the palette nor the stylesheet can reach.

Style hints are decided in C++ by the ``QStyle``, and so are the standard icons Qt draws
without asking anyone — a proxy style is the supported way to override either.
"""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleHintReturn, QStyleOption, QWidget

from dplanner.theme.icons import close_icon
from dplanner.theme.themes import DEFAULT, Theme


class WriterStyle(QProxyStyle):
    """Fusion, adjusted per platform.

    Forcing Fusion everywhere is what makes the theme render identically on macOS and Linux, but
    it also imports Fusion's assumptions wholesale. ``SH_UnderlineShortcut`` is the one that
    shows: Fusion draws the mnemonic underline permanently (F̲ile, Q̲uit), which is right on
    Linux and wrong on macOS, where menu mnemonics are not a platform concept and the underlines
    read as a stray artifact.
    """

    _HIDE_MNEMONIC_UNDERLINES = sys.platform == "darwin"

    def __init__(self, close_glyph: QIcon) -> None:
        super().__init__("Fusion")
        self._close_glyph = close_glyph

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

    def standardIcon(
        self,
        standardIcon: QStyle.StandardPixmap,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> QIcon:
        """Theme the cross on a tab, which a style otherwise draws from a bundled bitmap.

        Qt's own is a red ✕ that reads as an error badge on every theme, and no palette or
        stylesheet reaches it: ``PE_IndicatorTabClose`` asks the style for this icon and
        caches the answer, which is why the style is rebuilt on each theme change.
        """
        if standardIcon == QStyle.StandardPixmap.SP_TabCloseButton:
            return self._close_glyph
        return super().standardIcon(standardIcon, option, widget)


def build_style(theme: Theme = DEFAULT) -> WriterStyle:
    """Return the application style for ``theme``, wrapping Fusion."""
    return WriterStyle(close_icon(theme.text_secondary))
