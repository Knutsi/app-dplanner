"""State signalling: the indicator turns while one debouncer owes a run, the status line
wears a tone, and a progress bar is a four-pixel accent strip in every theme."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QProgressBar, QWidget

from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.signalling import StatusLine, UpdatingIndicator
from dplanner.theme import apply_theme
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.themes import DARK, LIGHT
from dplanner.theme.tones import STATUS_TONES


@pytest.fixture
def host(app):
    widget = QWidget()
    yield widget
    widget.deleteLater()


def test_the_indicator_shows_from_the_first_trigger_until_the_rebuild_ran(host):
    service = DebounceService()
    debounced = Debounced(lambda: None, 30, parent=host, service=service)
    indicator = UpdatingIndicator(host)
    indicator.follow(debounced)
    assert indicator.isHidden() and not indicator.is_spinning()
    debounced.trigger()
    debounced.trigger()
    assert not indicator.isHidden() and indicator.is_spinning()
    service.flush_all()
    assert indicator.isHidden() and not indicator.is_spinning()


def test_the_indicator_is_an_arc_and_no_words(host):
    """The words would be the only prose on a strip of controls; they are the tooltip."""
    indicator = UpdatingIndicator(host)
    assert indicator.text() == "" and indicator.toolTip() == "Updating…"
    assert indicator.size() == QSize(ICON_SIZE, ICON_SIZE)
    debounced = Debounced(lambda: None, 30, parent=host)
    indicator.follow(debounced)
    debounced.trigger()
    turning = indicator.pixmap()
    assert not turning.isNull()
    indicator._spinner._advance()  # A frame on, so the arc is at a different rotation.
    assert indicator.pixmap().cacheKey() != turning.cacheKey()
    debounced.cancel()
    assert indicator.pixmap().isNull()  # Idle shows nothing at all.


def test_in_immediate_mode_the_indicator_is_up_and_down_within_the_trigger(host):
    service = DebounceService()
    service.set_immediate(True)
    debounced = Debounced(lambda: None, 30, parent=host, service=service)
    indicator = UpdatingIndicator(host)
    indicator.follow(debounced)
    debounced.trigger()
    assert indicator.isHidden()


def test_the_indicator_keeps_its_room_while_hidden(host):
    assert UpdatingIndicator(host).sizePolicy().retainSizeWhenHidden()


def test_follow_returns_the_unsubscribe(host):
    debounced = Debounced(lambda: None, 30, parent=host)
    indicator = UpdatingIndicator(host)
    stop = indicator.follow(debounced)
    stop()
    debounced.trigger()
    assert indicator.isHidden()
    debounced.cancel()


def test_a_debouncer_outliving_its_indicator_reports_into_nothing(app, host):
    """The slot holds the widget weakly, so nothing calls into a dead C++ side."""
    debounced = Debounced(lambda: None, 30, parent=host)
    strip = QWidget()
    UpdatingIndicator(strip).follow(debounced)
    strip.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    debounced.trigger()  # Nothing raises.
    debounced.cancel()


def test_a_status_line_wears_its_tone_and_clears(host):
    line = StatusLine(host)
    assert line.isHidden()
    line.say("Connected — this account can read the space", "ok")
    assert not line.isHidden()
    assert line.words() == "Connected — this account can read the space" and line.tone() == "ok"
    assert STATUS_TONES["good"].name() in line.text()
    line.say("<script>", "error")
    assert "&lt;script&gt;" in line.text() and STATUS_TONES["bad"].name() in line.text()
    line.say("Reading…", "busy")
    assert STATUS_TONES["busy"].name() in line.text()
    line.clear()
    assert line.isHidden() and line.words() == ""


def test_information_wears_the_lines_own_ink(host):
    line = StatusLine(host)
    line.say("12 pages")
    assert line.tone() == "info" and "color:" not in line.text()


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_a_progress_bar_is_a_four_pixel_accent_strip(themed, theme):
    """Rendered, not read: a bar that Fusion still paints striped would pass a rule check."""
    apply_theme(themed, theme)
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(50)
    bar.setTextVisible(False)
    bar.resize(200, 20)
    bar.show()
    themed.processEvents()
    try:
        assert bar.maximumHeight() == 4
        image = bar.grab().toImage()
        assert image.height() == 4
        assert image.pixel(20, 2) == QColor(theme.accent).rgb()
        assert image.pixel(180, 2) == QColor(theme.bg_overlay).rgb()
    finally:
        bar.deleteLater()


def test_a_spinner_turns_the_glyph_while_pending_and_puts_it_back(host):
    from PySide6.QtWidgets import QToolButton

    from dplanner.framework.signalling import Spinner
    from dplanner.theme.icons import plus_icon

    service = DebounceService()
    debounced = Debounced(lambda: None, 30, parent=host, service=service)
    button = QToolButton(host)
    button.setText("Change something")
    button.setIcon(plus_icon("#ffffff"))
    idle = button.icon().cacheKey()
    before = button.sizeHint()
    spinner = Spinner(host).attach(button)
    spinner.follow(debounced)
    debounced.trigger()
    assert spinner.is_spinning() and button.icon().cacheKey() != idle
    first = button.icon().cacheKey()
    spinner._advance()
    assert button.icon().cacheKey() != first  # The arc turned.
    assert button.sizeHint() == before  # And nothing moved.
    service.flush_all()
    assert not spinner.is_spinning() and button.icon().cacheKey() == idle


def test_a_spinner_refuses_a_button_with_no_glyph(host):
    from PySide6.QtWidgets import QPushButton

    from dplanner.framework.signalling import Spinner

    with pytest.raises(ValueError):
        Spinner(host).attach(QPushButton("Change something", host))


def test_a_spinner_turns_a_toolbar_verb_too(host):
    from dplanner.framework.signalling import Spinner
    from dplanner.framework.toolbar import Toolbar
    from dplanner.theme.icons import refresh_icon

    bar = Toolbar(host)
    refresh = bar.add_verb("Refresh", refresh_icon, lambda: None)
    idle = refresh.icon().cacheKey()
    spinner = Spinner(host).attach(refresh)
    spinner.start()
    assert refresh.icon().cacheKey() != idle
    spinner.stop()
    assert refresh.icon().cacheKey() == idle
