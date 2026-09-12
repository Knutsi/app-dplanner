"""Settings ▸ Confluence: the sites this person is connected to, each with Reconnect…
and Forget. Per user, per machine — the rows are ``user_config``'s and the tokens the
keychain's; the plan never learns either."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def build_page(
    parent: QWidget | None,
    *,
    sites: Callable[[], dict[str, str]],
    reconnect: Callable[[QWidget, str], bool],
    forget: Callable[[str], None],
) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("ConfluenceSettingsPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    note = QLabel(
        "Confluence sites this computer is connected to. A token is kept in the OS keychain "
        "and read only when a source is fetched; forgetting a site deletes it. Sources are "
        "added from a project's Specs tab.",
        page,
    )
    note.setObjectName("InspectorNote")
    note.setWordWrap(True)
    layout.addWidget(note)
    rows = QVBoxLayout()
    rows.setSpacing(8)
    layout.addLayout(rows)
    layout.addStretch(1)

    def rebuild() -> None:
        while rows.count():
            item = rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        connected = sites()
        if not connected:
            empty = QLabel("Not connected to any site yet.", page)
            empty.setObjectName("InspectorNote")
            rows.addWidget(empty)
            return
        for site, email in sorted(connected.items()):
            row = QWidget(page)
            row.setObjectName("ConfluenceSiteRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            facts = QLabel(f"{site}  —  {email}", row)
            facts.setTextFormat(Qt.TextFormat.PlainText)
            line.addWidget(facts, 1)
            again = QPushButton("Reconnect…", row)
            again.clicked.connect(lambda _c=False, s=site: reconnected(s))
            line.addWidget(again)
            drop = QPushButton("Forget", row)
            drop.setObjectName("forgetSite")
            drop.clicked.connect(lambda _c=False, s=site: forgotten(s))
            line.addWidget(drop)
            rows.addWidget(row)

    def reconnected(site: str) -> None:
        reconnect(page, site)
        rebuild()

    def forgotten(site: str) -> None:
        forget(site)
        rebuild()

    rebuild()
    return page
