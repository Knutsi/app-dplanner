"""The "Reports" settings page: whether Save writes the plan repository's site, and a
button to write it now.

Per user, per machine — a GLOBAL-scope section — because whether *this* window publishes
on Save is this person's behaviour; where the site goes is not a setting at all
(``cli/report/website.py`` says why), so the page states the place rather than asking.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtWidgets import QCheckBox, QWidget

from dplanner.cli.report.website import REPORTS_DIR
from dplanner.framework.settings_registry import settings_page
from dplanner.framework.signalling import Spinner
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import GlyphButton, block, captioned
from dplanner.theme.icons import refresh_icon

MODULE_ID = "reporting"
PUBLISH_KEY = "publish_on_save"

ON_SAVE_HINT = (
    f"Every Save writes each dirty repository's projects under {REPORTS_DIR}/ — one page per"
    " project and an index — and records them in the same commit, so anyone with the"
    " repository has the plan as a web page. A clean plan writes nothing; Write Now does."
)


def build_page(
    parent: QWidget | None,
    *,
    write_now: Callable[[], None],
    busy_changed: SignalInstance | None = None,
) -> QWidget:
    """The page. ``busy_changed`` is the reporting module's runner signal: the button that
    started the work says so in its own glyph while a report is being written (DESIGN.md's
    *Signalling*, *Working*) — one runner, so "a report is being written" is the truth."""
    page, layout = settings_page(parent)
    page.setObjectName("ReportsSettingsPage")

    switch = QCheckBox("Write the report site into the plan repository", page)
    switch.setObjectName("publishOnSave")
    switch.setChecked(bool(get_global(MODULE_ID, PUBLISH_KEY, True)))
    switch.toggled.connect(lambda on: set_global(MODULE_ID, PUBLISH_KEY, bool(on)))
    block(layout, captioned("On Save", page, ON_SAVE_HINT), switch)

    # The glyph slot is always there, so the arc turning in it moves nothing; the glyph is
    # re-inked on a theme change, because this page lives as long as the window.
    button = GlyphButton(
        "Write Now",
        refresh_icon,
        page,
        tip="Write every repository's report site now, whatever the switch says",
    )
    button.setObjectName("writeSiteNow")
    button.clicked.connect(lambda: write_now())
    layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)

    # Parented to the page, which is what keeps it alive; a test finds it by type.
    spinner = Spinner(page)
    spinner.attach(button)
    if busy_changed is not None:
        busy_changed.connect(lambda busy: spinner.start() if busy else spinner.stop())
    layout.addStretch(1)
    return page
