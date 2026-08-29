"""The "Startup" settings page: whether a new window comes back to where you left it.

The one thing here is a preference rather than remembered state, so it is GLOBAL scope —
a person who does not want their tabs back does not want them back in any library. What is
remembered *per library* is the tab list itself, and that lives with the module.
"""

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from dplanner.framework.user_config import get_global, set_global

MODULE_ID = "reopen_tabs"
REOPEN_KEY = "reopen"


def reopen_wanted() -> bool:
    """On unless the user turned it off: coming back to the work you had open is what a
    person expects, and an empty window is the surprise."""
    return bool(get_global(MODULE_ID, REOPEN_KEY, True))


def build_page(parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("StartupSettingsPage")

    reopen_box = QCheckBox("Reopen the tabs from last time", page)
    reopen_box.setObjectName("ReopenTabsBox")
    reopen_box.setChecked(reopen_wanted())
    reopen_box.toggled.connect(lambda on: set_global(MODULE_ID, REOPEN_KEY, bool(on)))

    note = QLabel(
        "Each project library remembers its own tabs, and a tab whose project is gone is"
        " simply not reopened. Switching this off starts a window empty; the list is still"
        " kept, so switching it back on returns the session you last had.",
        page,
    )
    note.setObjectName("InspectorNote")
    note.setWordWrap(True)

    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("Startup", page))
    layout.addWidget(reopen_box)
    layout.addWidget(note)
    layout.addStretch(1)
    return page
