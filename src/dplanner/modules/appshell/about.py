"""About DPlanner: what it is, what it is built on, and under which licences.

The list of components is written here — a package cannot say what it *does for us* — but
every version and licence beside it is read from the installed distribution's own metadata
(:mod:`importlib.metadata`). A hand-kept licence table is a table that drifts, and the one
thing an acknowledgement must not do is claim the wrong licence; asking the package is the
only answer that cannot go stale.

A component this build does not have — an optional one, or a source checkout missing a
dependency — says so in its row rather than being dropped: an acknowledgement that quietly
shortens is worse than one that admits a gap.
"""

import platform
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import metadata as dist_metadata
from importlib.metadata import version as dist_version

from PySide6.QtWidgets import QLabel, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.widgets import caption, note
from dplanner.identity import APP_NAME, APP_VERSION
from dplanner.theme.cards import title_font
from dplanner.theme.icons import TABLER_TAG

ABOUT_SIZE = (820, 620)
MISSING = "not installed"


@dataclass(frozen=True)
class Component:
    """One thing DPlanner is built on: what a person reads, and where to ask about it."""

    name: str
    what: str  # What it does *here* — the one line no package's metadata can supply.
    distribution: str = ""  # The installed package to ask; "" for something that is not one.
    licence: str = ""  # Written only where there is no package to ask.
    release: str = ""  # Likewise: a vendored set carries the version it was taken at.


BUILT_ON: tuple[Component, ...] = (
    Component(
        "Qt for Python (PySide6)",
        "the window, the canvas, and every widget in it",
        "PySide6-Essentials",
    ),
    Component("Shiboken", "the binding between Python and Qt", "shiboken6"),
    Component("keyring", "the OS keychain a source's token is kept in", "keyring"),
    Component("pypdfium2", "rendering a specification's PDF pages", "pypdfium2"),
    Component("OpenAI Python", "talking to an OpenAI model, where one is configured", "openai"),
    Component(
        "Anthropic Python",
        "talking to a Claude model, where one is configured",
        "anthropic",
    ),
    Component("Python", "the language DPlanner is written in", licence="PSF-2.0"),
    # Vendored rather than depended on, so there is no distribution to ask: the version and
    # the licence are what `scripts/vendor_tabler_icons.py` took, and the notice it took
    # with them lives in `theme/glyphs/LICENSE`.
    Component("Tabler Icons", "every glyph in the application", licence="MIT", release=TABLER_TAG),
)


def _licence_of(name: str) -> str:
    """What a distribution declares, asked in the order the answers got vaguer.

    Packaging metadata has had three places for this: ``License-Expression``, an SPDX
    expression and the one to believe; ``License``, the free-text field before it; and the
    trove classifiers before that, which say *MIT License* where the package itself says
    *MIT*. Asking them in that order is what keeps two rows under one licence from reading
    as two different ones.
    """
    found = dist_metadata(name)
    expression = found.get("License-Expression") or ""
    if expression:
        return expression
    stated = (found.get("License") or "").strip()
    if stated:
        # The free-text field has held whole licence texts; one line is all a row can say.
        return stated.splitlines()[0]
    return ", ".join(
        line.split("::")[-1].strip()
        for line in found.get_all("Classifier") or []
        if line.startswith("License ::")
    )


def acknowledgements() -> list[tuple[str, str, str, str]]:
    """Every component as ``(name, what, version, licence)``, asked of the installation."""
    rows = []
    for part in BUILT_ON:
        if not part.distribution:
            release = part.release or platform.python_version()
            rows.append((part.name, part.what, release, part.licence))
            continue
        try:
            release = dist_version(part.distribution)
        except PackageNotFoundError:
            rows.append((part.name, part.what, MISSING, ""))
            continue
        rows.append((part.name, part.what, release, _licence_of(part.distribution)))
    return rows


class AboutDialog(DialogFrame):
    """What this is, and what it stands on — one dialog, because they are one question.

    DESIGN.md's *Dialogs*: it prints no heading of its own. The first line *is* the
    content — the application naming itself — and the table under it is what it is built
    on, a row per component with the licence it is used under.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(f"About {APP_NAME}", parent, size=ABOUT_SIZE)
        name = QLabel(f"{APP_NAME} {APP_VERSION}", self.body)
        name.setFont(title_font(name.font()))
        self.body_layout.addWidget(name)
        self.body_layout.addWidget(
            note("A development planner: a library of projects, each a graph of steps.", self.body)
        )
        self.body_layout.addWidget(caption("Built on", self.body))
        # Two columns, not three: the version is a fact *about* a component, so it goes
        # under its name with what it does (DESIGN.md's *Facts under the thing they are
        # about*). The licence is what a reader compares down the page, so it is a column.
        self.table = Table(
            (Column("Component", detail=True), Column("Licence", resize="stretch")),
            selection="none",
            parent=self.body,
        )
        for component, what, release, licence in acknowledgements():
            self.table.add_row((Cell(component, detail=f"{release} · {what}"), licence or "—"))
        self.body_layout.addWidget(self.table, 1)
        self.add_dismiss("Close")
