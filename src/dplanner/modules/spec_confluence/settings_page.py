"""Settings ▸ Confluence: the sites this person is connected to, as a table with its verbs
on a strip above it — *Reconnect…* and *Forget*, greyed until a site is picked. Per user,
per machine — the rows are ``user_config``'s and the tokens the keychain's; the plan never
learns either. Forgetting deletes a token the person can only get back from Atlassian, so
it asks first."""

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.settings_registry import settings_page
from dplanner.framework.table import Column, Table
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState, block, captioned, confirm
from dplanner.theme.icons import connect_icon, trash_icon

SITES_HINT = (
    "A token is kept in this computer's keychain and read only when a source is fetched;"
    " forgetting a site deletes it."
)
NO_SITES = (
    "Not connected to any site yet — a Confluence source is added from a project's Specs tab."
)


def build_page(
    parent: QWidget | None,
    *,
    sites: Callable[[], dict[str, str]],
    reconnect: Callable[[QWidget, str], bool],
    forget: Callable[[str], None],
) -> QWidget:
    page, layout = settings_page(parent)
    page.setObjectName("ConfluenceSettingsPage")

    table = Table(
        (Column("Site", resize="interactive"), Column("Account", resize="stretch")),
        parent=page,
    )
    empty = EmptyState("", page, stands_in_for=table)

    def picked() -> str | None:
        chosen = table.selectedItems()
        return str(chosen[0].data(HOST_ROLE)) if chosen else None

    def rebuild() -> None:
        table.clear_rows()
        for site, email in sorted(sites().items()):
            table.add_row([site, email], data={HOST_ROLE: site})
        table.fit_columns()
        empty.say("" if table.rowCount() else NO_SITES)
        reword()

    def on_reconnect() -> None:
        site = picked()
        if site is not None:
            reconnect(page, site)
            rebuild()

    def on_forget() -> None:
        site = picked()
        if site is not None and confirm(
            page,
            "Forget Site",
            f"Forget {site}? Its token is deleted from this computer's keychain.",
            verb="Forget",
        ):
            forget(site)
            rebuild()

    strip = Toolbar(page)
    reconnect_action = strip.add_verb("Reconnect…", connect_icon, on_reconnect)
    forget_action = strip.add_verb("Forget", trash_icon, on_forget)

    def reword() -> None:
        on = picked() is not None
        reconnect_action.setEnabled(on)
        forget_action.setEnabled(on)

    table.itemSelectionChanged.connect(reword)
    column = block(layout, captioned("Connected sites", page, SITES_HINT), strip)
    column.addWidget(table, 1)
    column.addWidget(empty, 1)
    rebuild()
    return page
