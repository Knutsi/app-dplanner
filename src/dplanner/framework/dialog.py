"""The dialog frame: title, lead, body, footer — every dialog's anatomy, written once.

DESIGN.md's *Dialogs* is the standard this implements. A :class:`DialogFrame` prints its
title in its body (a window manager may draw no title bar, and the user's does not), a lead
line saying what this dialog is about, the body a subclass fills, and a footer whose slots
run destructive · status · stretch · secondaries · primary. Enter runs the primary, Escape
dismisses, a dismiss is the default only while there is no primary, and the first Tab out
of the body lands on the primary. A dialog whose every edit is live carries no button and
therefore no footer.

The frame names its *parts* — ``#DialogBody``, ``#DialogFooter`` — and leaves its own
object name to the subclass, so the stylesheet reaches every dialog through two constant
names and no dialog is ever added to a selector list. ``ARCHITECTURE.md``'s *A primitive
carries the rule* has the reasoning; ``modules/debug/design_example.py`` is the reference
to copy from.
"""

from collections.abc import Callable
from itertools import pairwise

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.signalling import StatusLine
from dplanner.framework.widgets import caption
from dplanner.theme.cards import title_font
from dplanner.theme.tokens import CAPTION_GAP, DIALOG_MARGIN, FIELD_GAP, SCREEN_SHARE, SECTION_GAP

# A fit-to-content dialog is never narrower than this: a one-line prompt or a confirmation
# sized to its words alone reads as a tooltip.
FIT_WIDTH = 420


class DialogFrame(QDialog):
    """Title, lead, body and footer; see the module docstring for the rules it keeps.

    ``size=(w, h)`` is a *framed* dialog: that preferred size, clamped to ``SCREEN_SHARE``
    of the screen. ``editor=True`` claims that share outright — a place to work. Neither
    is a *fit* dialog, sized to its content: a prompt, a confirmation, a connect form.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        lead: str = "",
        size: tuple[int, int] | None = None,
        editor: bool = False,
    ) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # The page carries the dialog's margins; the footer is a band below it, edge to
        # edge, with its own — so its ground can run the dialog's full width.
        self.page = QWidget(self)
        outer.addWidget(self.page, 1)
        column = QVBoxLayout(self.page)
        column.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        column.setSpacing(SECTION_GAP)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("DialogTitle")
        self.title_label.setFont(title_font(self.font()))
        self.title_label.setWordWrap(True)
        column.addWidget(self.title_label)

        self.lead_label = QLabel(self)
        self.lead_label.setObjectName("DialogLead")
        self.lead_label.setWordWrap(True)
        column.addWidget(self.lead_label)

        self.body = QWidget(self)
        self.body.setObjectName("DialogBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(SECTION_GAP)
        column.addWidget(self.body, 1)

        self.footer = QWidget(self)
        self.footer.setObjectName("DialogFooter")
        self.footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # Or no ground.
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(
            DIALOG_MARGIN, SECTION_GAP, DIALOG_MARGIN, SECTION_GAP
        )
        self.footer_layout.setSpacing(FIELD_GAP)
        self.status = StatusLine(self.footer)
        self.footer_layout.addWidget(self.status)
        self.footer_layout.addStretch(1)
        self.footer.hide()  # Until a button arrives: a live-edit dialog never shows one.
        outer.addWidget(self.footer)

        self._destructive: list[QPushButton] = []
        self._secondaries: list[QPushButton] = []
        self._primary: QPushButton | None = None
        self._dismiss: QPushButton | None = None

        self.set_title(title)
        self.set_lead(lead)
        self._size(size, editor)

    # -- what it says ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        """The title in the body, mirrored into the window title for the switcher."""
        self.title_label.setText(text)
        self.setWindowTitle(text)

    def set_lead(self, text: str) -> None:
        """One line under the title saying what this dialog is about — the thing's name in
        it, never a standing definition (DESIGN.md's *Words*). Hidden when empty."""
        self.lead_label.setText(text)
        self.lead_label.setVisible(bool(text))

    # -- the footer --------------------------------------------------------------------

    def set_primary(self, text: str, slot: Callable[[], object]) -> QPushButton:
        """The one accent button, rightmost, and Enter's."""
        if self._primary is not None:
            raise ValueError("a dialog has one primary action")
        button = QPushButton(text, self.footer)
        button.setObjectName("PrimaryButton")
        button.clicked.connect(lambda: slot())
        self.footer_layout.addWidget(button)
        self._primary = button
        self._make_default(button)
        self.footer.show()
        return button

    def add_button(
        self, text: str, slot: Callable[[], object], *, destructive: bool = False
    ) -> QPushButton:
        """A quiet secondary, left of the dismiss and the primary — or, ``destructive``, at
        the far left, as far from the accent as the footer allows."""
        button = QPushButton(text, self.footer)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: slot())
        if destructive:
            self.footer_layout.insertWidget(len(self._destructive), button)
            self._destructive.append(button)
        else:
            self._insert_before(button, self._dismiss or self._primary)
            self._secondaries.append(button)
        self.footer.show()
        return button

    def add_dismiss(self, text: str = "Cancel") -> QPushButton:
        """Escape's button, in words. The default only while there is no primary — so a
        confirmation whose only verb discards work answers Enter with nothing lost."""
        button = QPushButton(text, self.footer)
        button.setAutoDefault(False)
        button.clicked.connect(self.reject)
        self._insert_before(button, self._primary)
        self._secondaries.append(button)
        self._dismiss = button
        if self._primary is None:
            self._make_default(button)
        self.footer.show()
        return button

    def _insert_before(self, button: QPushButton, anchor: QPushButton | None) -> None:
        at = self.footer_layout.count() if anchor is None else self.footer_layout.indexOf(anchor)
        self.footer_layout.insertWidget(at, button)

    def refuse(self, reason: str | None) -> None:
        """Disable the primary and say why in the status slot; ``None`` lifts the refusal.

        DESIGN.md's rule for a verb that does not apply right now: disabled, never hidden,
        the reason in words. The button keeps its name, so the footer keeps its shape.
        """
        if self._primary is not None:
            self._primary.setEnabled(reason is None)
        self.status.say(reason or "")

    def primary(self) -> QPushButton | None:
        return self._primary

    def _make_default(self, button: QPushButton) -> None:
        for other in (self._primary, self._dismiss):
            if other is not None and other is not button:
                other.setDefault(False)
                other.setAutoDefault(False)
        button.setAutoDefault(True)
        button.setDefault(True)

    # -- keyboard and focus ------------------------------------------------------------

    def footer_buttons(self) -> list[QPushButton]:
        """In Tab order: the primary, the secondaries, the destructive last."""
        primary = [self._primary] if self._primary is not None else []
        return primary + self._secondaries + self._destructive

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        fields = self._body_fields()
        chain: list[QWidget] = [*fields, *self.footer_buttons()]
        for earlier, later in pairwise(chain):
            QWidget.setTabOrder(earlier, later)
        focused = self.focusWidget()
        if focused is None or self.footer.isAncestorOf(focused):
            default = next((b for b in self.footer_buttons() if b.isDefault()), None)
            target = fields[0] if fields else default
            if target is not None:
                target.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        """Ctrl+Enter is Enter from a multi-line field, which keeps plain Enter for itself."""
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self._primary is not None
            and self._primary.isEnabled()
        ):
            self._primary.click()
            return
        super().keyPressEvent(event)

    def _body_fields(self) -> list[QWidget]:
        return [
            widget
            for widget in self.body.findChildren(QWidget)
            if widget.focusPolicy() & Qt.FocusPolicy.TabFocus and widget.isVisibleTo(self.body)
        ]

    # -- size --------------------------------------------------------------------------

    def _size(self, size: tuple[int, int] | None, editor: bool) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if editor and available is not None:
            self.resize(
                round(available.width() * SCREEN_SHARE), round(available.height() * SCREEN_SHARE)
            )
        elif size is not None:
            width, height = size
            if available is not None:
                width = min(width, round(available.width() * SCREEN_SHARE))
                height = min(height, round(available.height() * SCREEN_SHARE))
            self.resize(width, height)
        else:
            self.setMinimumWidth(FIT_WIDTH)


class LinePrompt(DialogFrame):
    """One captioned field and a verb: the dialog behind *New Feature…* and *Rename…*.

    A fit dialog. The primary is named for the verb and refused — disabled, the reason in
    the note under the field — while ``validate`` objects or the field is blank. The field
    starts selected, so typing replaces a default.
    """

    def __init__(
        self,
        title: str,
        caption_text: str,
        verb: str,
        parent: QWidget | None = None,
        *,
        text: str = "",
        lead: str = "",
        placeholder: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__(title, parent, lead=lead)
        self._validate = validate
        self.body_layout.setSpacing(CAPTION_GAP)
        self.body_layout.addWidget(caption(caption_text, self.body))
        self.field = QLineEdit(text, self.body)
        self.field.setPlaceholderText(placeholder)
        self.body_layout.addWidget(self.field)
        self.problem = StatusLine(self.body)
        self.body_layout.addWidget(self.problem)
        self.add_dismiss()
        self.set_primary(verb, self.accept)
        self.field.textChanged.connect(self._check)
        self._check(text)
        self.field.selectAll()

    def value(self) -> str:
        return self.field.text().strip()

    def _check(self, text: str) -> None:
        reason = None
        if not text.strip():
            reason = ""  # Blank: refused, and the reason is plain to see.
        elif self._validate is not None:
            reason = self._validate(text.strip())
        primary = self.primary()
        if primary is not None:
            primary.setEnabled(reason is None)
        self.problem.say(reason or "", "error")

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        title: str,
        caption_text: str,
        verb: str,
        *,
        text: str = "",
        lead: str = "",
        placeholder: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str | None:
        """Run the prompt; the text on the verb, ``None`` on Escape or Cancel."""
        prompt = cls(
            title,
            caption_text,
            verb,
            parent,
            text=text,
            lead=lead,
            placeholder=placeholder,
            validate=validate,
        )
        accepted = prompt.exec() == QDialog.DialogCode.Accepted
        value = prompt.value()
        prompt.deleteLater()
        return value if accepted else None
