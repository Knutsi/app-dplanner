"""The index tree's memory: which folders were open, kept per library.

Built here with a stub segment rather than through a whole application, because what is
under test is the *panel's* bookkeeping — a segment supplies rows and a key per row, and
the panel is what writes them down and puts them back. The keys are the segment's own node
ids, which is what makes a stale one harmless: a key naming no row restores nothing.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem
from tests.index_helpers import click

from dplanner.framework.context import ContextService
from dplanner.framework.index_panel import IndexPanel, IndexSegment, IndexSegmentRegistry
from dplanner.framework.user_config import get_scoped, set_scoped

SCOPE = "a-library"


class StubSegment:
    """One folder of flat rows, keyed the way every segment keys its own."""

    def __init__(
        self, root: QTreeWidgetItem, keys: tuple[str, ...], heard: list[tuple[str, str]]
    ) -> None:
        self._heard = heard
        for key in keys:
            row = QTreeWidgetItem([key.title()])
            row.setData(0, Qt.ItemDataRole.UserRole, key)
            row.addChild(QTreeWidgetItem(["a child, so the row can be opened"]))
            root.addChild(row)

    def selection_nodes(self, items):
        return ()

    def clicked(self, item):
        self._heard.append(("clicked", item.text(0)))

    def activated(self, item):
        self._heard.append(("activated", item.text(0)))

    def context_menu(self, item):
        self._heard.append(("menu", item.text(0)))
        return None

    def dispose(self):
        pass


def rows(panel):
    root = panel.tree.topLevelItem(0)
    return {root.child(i).text(0): root.child(i) for i in range(root.childCount())}


@pytest.fixture
def build(app):
    """Open a panel over the stub folder. Every panel stays alive for the whole test —
    dropped, PySide takes its tree items with it and the next line reads a deleted row."""
    opened = []

    def open_one(*, scope=SCOPE, keys=("alpha", "beta"), heard=None):
        registry = IndexSegmentRegistry()
        heard = [] if heard is None else heard
        registry.register(
            IndexSegment(
                id="stub", label="Stub", factory=lambda root: StubSegment(root, keys, heard)
            )
        )
        panel = IndexPanel(registry, ContextService(), scope=scope)
        opened.append(panel)
        return panel

    yield open_one
    for panel in opened:
        panel.dispose()


def test_a_folder_nobody_has_touched_opens(build):
    assert build().tree.topLevelItem(0).isExpanded()


def test_an_open_row_is_open_again_next_time(build):
    rows(build())["Alpha"].setExpanded(True)
    reopened = rows(build())
    assert reopened["Alpha"].isExpanded()
    assert not reopened["Beta"].isExpanded()


def test_a_folder_the_user_closed_stays_closed(build):
    """The folder is its own expansion key, so one walk covers the folder and its rows."""
    build().tree.topLevelItem(0).setExpanded(False)
    assert not build().tree.topLevelItem(0).isExpanded()


def test_a_remembered_row_that_is_gone_costs_nothing(build):
    """The library changed underneath: 'beta' is not there any more, and 'alpha' still is."""
    opened = rows(build())
    opened["Alpha"].setExpanded(True)
    opened["Beta"].setExpanded(True)
    survivors = rows(build(keys=("alpha", "gamma")))
    assert list(survivors) == ["Alpha", "Gamma"]
    assert survivors["Alpha"].isExpanded()


def test_another_library_remembers_its_own_folders(build):
    rows(build())["Alpha"].setExpanded(True)
    assert not rows(build(scope="another-library"))["Alpha"].isExpanded()


def test_a_panel_with_no_scope_remembers_nothing(build):
    rows(build(scope=""))["Alpha"].setExpanded(True)
    assert not rows(build(scope=""))["Alpha"].isExpanded()


def test_a_folder_that_is_not_in_this_build_keeps_what_it_had(build):
    """A save is a merge, not a replacement.

    Segments arrive one module at a time, so the first expansion in a half-built tree
    would otherwise erase every folder that had not registered yet.
    """
    # "stub" carries the folder's own key: the folder was open, with no row open under it.
    set_scoped(SCOPE, "index", "expanded", {"gone": ["something"], "stub": ["stub"]})
    rows(build())["Alpha"].setExpanded(True)
    stored = get_scoped(SCOPE, "index", "expanded", {})
    assert stored["gone"] == ["something"]
    assert stored["stub"] == ["alpha", "stub"]


def test_the_folder_row_itself_is_its_segments_to_answer(build):
    """A click, an activation and a right-click on a folder's own row reach its segment like
    any other row's — the Home row is a folder with nothing under it, and the Projects
    folder's right-click adds a project. Selection is the one thing a folder row never has."""
    heard: list[tuple[str, str]] = []
    panel = build(heard=heard)
    folder = panel.tree.topLevelItem(0)
    click(panel, folder)
    panel.tree.itemActivated.emit(folder, 0)
    assert panel.context_menu(folder) is None
    assert heard == [("clicked", "Stub"), ("activated", "Stub"), ("menu", "Stub")]
    assert panel.context_menu(None) is None  # Empty space under the last folder.
