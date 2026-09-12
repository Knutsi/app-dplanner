"""The dialog frame: a title in the body, footer slots in one order, Enter and Escape where
DESIGN.md puts them, focus on the first field, and the accent on exactly one button — in
both themes, and even inside a dialog the stylesheet once had to name."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from dplanner.framework.dialog import FIT_WIDTH, DialogFrame, LinePrompt
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT
from dplanner.theme.tokens import SCREEN_SHARE


@pytest.fixture
def frame(app):
    dialog = DialogFrame("Run Agent")
    yield dialog
    dialog.deleteLater()


def test_the_title_names_the_window_and_nothing_is_printed_in_the_body(frame):
    """The frame prints no heading: a title inside a dialog repeats its title bar and
    pushes the content down. What the dialog is about is what the body shows."""
    assert frame.windowTitle() == "Run Agent"
    frame.set_title("Run 3 Agents")
    assert frame.windowTitle() == "Run 3 Agents"
    assert frame.findChild(QLabel, "DialogTitle") is None
    assert frame.findChild(QLabel, "DialogLead") is None


def test_the_footer_is_hidden_until_a_button_arrives(frame):
    assert frame.footer.isHidden()
    frame.add_dismiss("Close")
    assert not frame.footer.isHidden()


def test_buttons_land_destructive_status_stretch_secondaries_dismiss_primary(frame):
    primary = frame.set_primary("Run Anyway", lambda: None)
    cancel = frame.add_dismiss()
    browse = frame.add_button("Browse…", lambda: None)
    delete = frame.add_button("Delete", lambda: None, destructive=True)
    layout = frame.footer_layout
    order = [layout.indexOf(w) for w in (delete, frame.status, browse, cancel, primary)]
    assert order == sorted(order) and layout.indexOf(delete) == 0
    assert frame.footer_buttons() == [primary, cancel, browse, delete]


def test_the_primary_is_the_default_and_the_dismiss_rejects(frame):
    ran = []
    primary = frame.set_primary("Apply", lambda: ran.append(True))
    cancel = frame.add_dismiss()
    assert primary.isDefault() and not cancel.isDefault()
    primary.click()
    assert ran == [True]
    cancel.click()
    assert frame.result() == QDialog.DialogCode.Rejected


def test_the_dismiss_is_the_default_only_while_there_is_no_primary(frame):
    cancel = frame.add_dismiss()
    assert cancel.isDefault()
    primary = frame.set_primary("Apply", lambda: None)
    assert primary.isDefault() and not cancel.isDefault() and not cancel.autoDefault()


def test_a_dialog_has_one_primary(frame):
    frame.set_primary("Apply", lambda: None)
    with pytest.raises(ValueError):
        frame.set_primary("Also Apply", lambda: None)


def test_refuse_disables_the_primary_and_says_why(frame):
    primary = frame.set_primary("Clone", lambda: None)
    frame.refuse("Pick a repository first")
    assert not primary.isEnabled() and primary.text() == "Clone"
    assert frame.status.words() == "Pick a repository first" and not frame.status.isHidden()
    frame.refuse(None)
    assert primary.isEnabled() and frame.status.isHidden()


def test_a_framed_size_is_clamped_to_the_screen_share(app):
    screen = QGuiApplication.primaryScreen().availableGeometry()
    dialog = DialogFrame("Wide", size=(screen.width() * 4, screen.height() * 4))
    try:
        assert dialog.width() == round(screen.width() * SCREEN_SHARE)
        assert dialog.height() == round(screen.height() * SCREEN_SHARE)
    finally:
        dialog.deleteLater()


def test_an_editor_claims_the_share_and_a_fit_dialog_keeps_the_floor(app):
    screen = QGuiApplication.primaryScreen().availableGeometry()
    editor = DialogFrame("Edit", editor=True)
    fit = DialogFrame("Prompt")
    try:
        assert editor.width() == round(screen.width() * SCREEN_SHARE)
        assert fit.minimumWidth() == FIT_WIDTH
    finally:
        editor.deleteLater()
        fit.deleteLater()


def two_fields(frame):
    first = QLineEdit(frame.body)
    second = QLineEdit(frame.body)
    frame.body_layout.addWidget(first)
    frame.body_layout.addWidget(second)
    return first, second


def test_the_first_field_takes_focus_and_tab_runs_body_primary_secondaries_destructive(frame, app):
    first, second = two_fields(frame)
    primary = frame.set_primary("Apply", lambda: None)
    cancel = frame.add_dismiss()
    delete = frame.add_button("Delete", lambda: None, destructive=True)
    frame.show()
    app.processEvents()
    assert frame.focusWidget() is first
    chain = [first]
    for _ in range(4):
        chain.append(chain[-1].nextInFocusChain())
    assert chain == [first, second, primary, cancel, delete]


def test_a_confirmation_with_no_field_focuses_its_default_button(frame, app):
    frame.add_button("Discard", lambda: None)
    cancel = frame.add_dismiss()
    frame.show()
    app.processEvents()
    assert frame.focusWidget() is cancel


def test_ctrl_enter_runs_the_primary_from_anywhere(frame, app):
    ran = []
    frame.set_primary("Apply", lambda: ran.append(True))
    frame.show()
    app.processEvents()
    QTest.keyClick(frame, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert ran == [True]


def test_a_line_prompt_refuses_blank_and_bad_values(app):
    prompt = LinePrompt(
        "New Feature",
        "Title",
        "Create",
        validate=lambda text: "That name is taken" if text == "Search" else None,
    )
    try:
        primary = prompt.primary()
        assert primary is not None and not primary.isEnabled()
        prompt.field.setText("Search")
        assert not primary.isEnabled()
        assert prompt.problem.words() == "That name is taken" and prompt.problem.tone() == "error"
        prompt.field.setText("Login")
        assert primary.isEnabled() and prompt.problem.isHidden() and prompt.value() == "Login"
    finally:
        prompt.deleteLater()


def test_ask_returns_the_text_on_the_verb_and_none_on_escape(app, monkeypatch):
    def type_and_create(self):
        self.field.setText("  Login  ")
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(LinePrompt, "exec", type_and_create)
    assert LinePrompt.ask(None, "New Feature", "Title", "Create") == "Login"
    monkeypatch.setattr(LinePrompt, "exec", lambda self: int(QDialog.DialogCode.Rejected))
    assert LinePrompt.ask(None, "New Feature", "Title", "Create", text="Login") is None


def inside(button, dialog):
    """A point inside the button's padding — the centre is antialiased label text."""
    return button.mapTo(dialog, QPoint(4, button.height() // 2))


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_the_primary_wears_the_accent_and_the_others_are_quiet(themed, theme):
    apply_theme(themed, theme)
    dialog = DialogFrame("Move Plan")
    primary = dialog.set_primary("Move Plan", lambda: None)
    cancel = dialog.add_dismiss()
    dialog.show()
    themed.processEvents()
    try:
        image = dialog.grab().toImage()
        assert image.pixelColor(inside(primary, dialog)) == QColor(theme.accent)
        assert image.pixelColor(inside(cancel, dialog)) == QColor(theme.bg_overlay)
        # The footer is a band on the elevated ground, the page above it on the base.
        band = dialog.footer.mapTo(dialog, QPoint(dialog.footer.width() // 2, 4))
        assert image.pixelColor(band) == QColor(theme.bg_elevated)
        assert image.pixelColor(QPoint(band.x(), band.y() - 12)) == QColor(theme.bg_base)
        assert dialog.footer.width() == dialog.width()  # Edge to edge.
    finally:
        dialog.deleteLater()


def test_a_primary_inside_a_dialog_the_stylesheet_once_named_still_wears_the_accent(themed):
    """`#ProjectDialog QPushButton` outranks a bare `#PrimaryButton`; the type-prefixed rule
    ties it and wins by position. A rule check cannot see that — a render can."""
    apply_theme(themed, DARK)
    host = QWidget()
    host.setObjectName("ProjectDialog")
    button = QPushButton("Create", host)
    button.setObjectName("PrimaryButton")
    QVBoxLayout(host).addWidget(button)
    host.show()
    themed.processEvents()
    try:
        image = host.grab().toImage()
        assert image.pixelColor(inside(button, host)) == QColor(DARK.accent)
    finally:
        host.deleteLater()
