"""Sources in the Specs tab, with a kind built from lambdas: the seam works without
Confluence. The + dropdown lists the kind, a source added shows Connect until the kind
is ready, a fetch lands as one undo entry and nests its pages read-only, a check writes
nothing, and a refusal flips the button to Reconnect."""

import time
from dataclasses import dataclass, field, replace

import pytest
from PySide6.QtGui import QColor, QIcon

from dplanner.core.signals import Signal
from dplanner.domain.document_source import (
    FetchedDocument,
    FetchedImage,
    Freshness,
    Snapshot,
    SourceUnavailableError,
)
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.spec.activity import SpecsActivity
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import read_index
from dplanner.modules.spec.refresh import REFRESH_ALL_LABEL
from dplanner.modules.spec.source_kind import SourceStatus
from dplanner.theme.icons import spec_icon

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


def page(key, title, body, parent="", version="1", filename="page.md"):
    return FetchedDocument(
        key=key,
        parent_key=parent,
        title=title,
        data=body.encode() if isinstance(body, str) else body,
        filename=filename,
        version=version,
        url=f"https://x/{key}",
    )


@dataclass
class FakeKind:
    """A document source kind from lambdas — everything the spec module needs, nothing
    Confluence. ``ready`` flips on connect; ``snapshot`` and ``freshness`` are what the
    worker returns; ``raises`` makes the next call refuse."""

    id: str = "fake"
    name: str = "Fake"
    label: str = "Fake Source…"
    ready: bool = False
    connectable: bool = True
    located: tuple[str, dict[str, str]] | None = ("Auth", {"site": "https://f", "id": "1"})
    snapshot: Snapshot = field(
        default_factory=lambda: Snapshot(
            documents=(
                page("1", "Auth Overview", "# Auth\n\nsee\n", version="3"),
                page("2", "Tokens", "# T\n", parent="1"),
            ),
            order=("1", "2"),
        )
    )
    freshness: Freshness = field(default_factory=Freshness)
    raises: SourceUnavailableError | None = None
    fetches: list[dict[str, str]] = field(default_factory=list)
    checks: list[dict[str, str]] = field(default_factory=list)
    connects: int = 0
    config_changed: Signal[()] = field(default_factory=lambda: Signal[()]("fake.config"))

    def icon(self, color: str | QColor) -> QIcon:
        return spec_icon(color if isinstance(color, str) else color.name())

    def locate(self, _parent):
        return self.located

    def status(self, _locator):
        if self.ready:
            return SourceStatus(True)
        # `connectable` is the kind's claim that its own Connect closes this gap; a
        # malformed locator would say False and get the sentence and no button.
        return SourceStatus(False, "Not connected to f", connectable=self.connectable)

    def connect(self, _parent, _locator):
        self.connects += 1
        self.ready = True
        self.config_changed.emit()
        return True

    def open_url(self, locator):
        return f"https://f/{locator['id']}"

    def fetch(self, locator, known, progress, cancelled):
        self.fetches.append(dict(known))
        if self.raises is not None:
            raise self.raises
        progress(1.0)
        return self.snapshot

    def check(self, locator, known):
        self.checks.append(dict(known))
        if self.raises is not None:
            raise self.raises
        return self.freshness


@pytest.fixture
def kind():
    return FakeKind()


@pytest.fixture
def fake_kind(kind, monkeypatch):
    """Hand the fake in through the composition root's one seam. **Listed before
    ``services`` in a test's signature**: the patch must be in place before the
    application is built, and fixture order is what guarantees that."""
    import dplanner.modules as root

    monkeypatch.setattr(root, "_source_kinds", lambda *_real: (kind,))
    return kind


@pytest.fixture
def project(fake_kind, services, make_project):
    return make_project("Discovery")


def select(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    return services.context.current()


def opened(services, project) -> SpecsActivity:
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    assert isinstance(activity, SpecsActivity)
    return activity


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the worker never delivered"
        app.processEvents()
        time.sleep(0.01)


def settled(services, project):
    """Both the answer and the runner's own completion have been delivered."""
    refresher = services.tabs.activities()[0]._refresher
    return lambda: not refresher.is_fetching() and not refresher._checker.is_busy()


def index_of(services, project):
    return read_index(services.document.project(project.id))


def added(services, project) -> SpecsActivity:
    services.actions.run("spec.add_source.fake", select(services, project))
    activity = services.tabs.activities()[0]
    assert isinstance(activity, SpecsActivity)
    return activity


# -- the dropdown and the add ---------------------------------------------------------------


def test_the_plus_dropdown_lists_the_kind_after_the_built_ins(fake_kind, services, project):
    activity = opened(services, project)
    popup = activity.toolbar.menu_for("spec.new")
    assert popup is not None
    entries = [
        entry.text().replace("&", "") for entry in popup.actions() if not entry.isSeparator()
    ]
    assert entries == ["New Spec Document…", "Import Spec Document…", "Fake Source…"]
    assert not popup.actions()[-1].icon().isNull()


def test_adding_a_source_is_one_undo_entry_and_lands_on_its_row(fake_kind, services, project):
    activity = added(services, project)
    index = index_of(services, project)
    assert [(source.id, source.kind, source.title) for source in index.sources] == [
        ("src1", "fake", "Auth")
    ]
    assert index.sources[0].locator == {"site": "https://f", "id": "1"}
    assert activity.rows() == [("\x00topology", 0), ("src1", 0)]
    assert activity.current_row() == 1
    assert services.context.current().selected_entity("spec_source") == "src1"
    assert fake_kind.fetches == []  # Not ready: nothing was fetched.
    services.undo.undo()
    assert index_of(services, project).sources == []


def test_a_cancelled_locate_adds_nothing(fake_kind, services, project):
    fake_kind.located = None
    services.actions.run("spec.add_source.fake", select(services, project))
    assert index_of(services, project).sources == [] and services.tabs.activities() == []


# -- connect --------------------------------------------------------------------------------


def test_the_strip_offers_connect_until_the_kind_is_ready_then_fetches(
    app, fake_kind, services, project
):
    activity = added(services, project)
    assert not activity._source_strip.isHidden()
    assert (
        activity.connect_button.isVisible() and activity.connect_button.text() == "Connect to Fake…"
    )
    assert (activity.source_state.words(), activity.source_state.tone()) == (
        "Not connected to f",
        "error",
    )
    state = services.actions.spec("spec.refresh_source").state(services.context.current())
    assert not state.enabled and state.label == "Refresh Source — Not connected to f"

    activity.connect_button.click()
    assert fake_kind.connects == 1
    wait_for(app, lambda: len(index_of(services, project).documents) == 2)
    wait_for(app, settled(services, project))
    assert activity.connect_button.isHidden()
    assert services.actions.spec("spec.refresh_source").state(services.context.current()).enabled


# -- fetch ----------------------------------------------------------------------------------


@pytest.fixture
def fetched(app, fake_kind, services, project):
    fake_kind.ready = True
    activity = added(services, project)
    wait_for(app, lambda: len(index_of(services, project).documents) == 2)
    wait_for(app, settled(services, project))
    return activity


def test_a_fetch_nests_its_pages_read_only_under_the_source(fetched, services, project):
    activity = fetched
    assert activity.rows() == [
        ("\x00topology", 0),
        ("src1", 0),
        ("auth-overview", 1),
        ("tokens", 2),
    ]
    index = index_of(services, project)
    assert [doc.label for doc in index.documents] == ["Auth Overview", "Tokens"]
    assert index.sources[0].fetched
    activity.select_document("tokens")
    assert not activity.is_editing
    assert activity._views.currentWidget() is activity._text
    assert "T" in activity._text.toPlainText()
    assert services.context.current().selected_entity("spec_document") == "tokens"
    assert services.context.current().selected_entity("spec_source") == "src1"
    facts = activity.source_facts.text()
    assert "from Fake" in facts and "2 documents" in facts
    assert activity.source_state.words() == "2 added"


def test_the_add_and_the_fetch_are_two_undo_entries(fetched, services, project):
    services.undo.undo()
    index = index_of(services, project)
    assert index.documents == [] and len(index.sources) == 1
    services.undo.undo()
    assert index_of(services, project).sources == []


def test_a_refresh_replaces_changed_pages_keeps_previous_and_is_its_own_entry(
    app, fetched, fake_kind, services, project
):
    fake_kind.snapshot = Snapshot(
        documents=(page("1", "Auth Overview", "# Auth v2\n", version="4"),),
        kept=("2",),
        order=("1", "2"),
    )
    services.actions.run("spec.refresh_source", services.context.current())
    wait_for(app, lambda: index_of(services, project).documents[0].version == "4")
    wait_for(app, settled(services, project))
    assert fake_kind.fetches[-1] == {"1": "3", "2": "1"}
    index = index_of(services, project)
    assert index.documents[0].previous is not None and index.documents[1].version == "1"
    assert fetched.source_state.words() == "1 updated"
    services.undo.undo()
    assert index_of(services, project).documents[0].version == "3"
    assert len(index_of(services, project).documents) == 2  # The fetch before it stands.


def test_images_land_under_their_content_addressed_names(app, fake_kind, services, project):
    from dplanner.domain.assets import asset_name

    name = asset_name(PNG, "image.png")
    fake_kind.snapshot = Snapshot(
        documents=(page("1", "Pic", f"![pic]({name})\n"),), images=(FetchedImage(PNG, "image.png"),)
    )
    fake_kind.ready = True
    added(services, project)
    wait_for(app, lambda: index_of(services, project).documents)
    area = services.repo.files(project.id, MODULE_ID)
    assert area.read_bytes(name) == PNG
    assert [asset.file for asset in index_of(services, project).assets] == [name]


def test_a_sourced_page_cannot_be_removed_alone_but_the_source_can(
    fetched, services, project, monkeypatch
):
    from dplanner.modules.spec import module as spec_module

    fetched.select_document("tokens")
    state = services.actions.spec("spec.remove").state(services.context.current())
    assert not state.enabled and "part of Auth" in (state.label or "")
    monkeypatch.setattr(spec_module, "confirm", lambda *a, **k: True)
    services.actions.run("spec.remove_source", services.context.current())
    index = index_of(services, project)
    assert index.sources == [] and index.documents == []
    services.undo.undo()
    assert len(index_of(services, project).documents) == 2


def test_open_source_goes_through_the_browser_seam(fetched, services, monkeypatch):
    from dplanner.modules.spec import module as spec_module

    opened_urls: list[str] = []
    monkeypatch.setattr(spec_module, "open_url", opened_urls.append)
    services.actions.run("spec.open_source", services.context.current())
    assert opened_urls == ["https://f/1"]


# -- check, then ask ----------------------------------------------------------------------------


def test_a_check_says_what_changed_and_writes_nothing(app, fetched, fake_kind, services, project):
    before = index_of(services, project)
    fake_kind.freshness = Freshness(changed=("2",), added=("9",), removed=())
    refresher = services.tabs.activities()[0]._refresher
    refresher.check_all(project.id)
    wait_for(app, lambda: refresher.freshness(project.id, "src1") is not None)
    assert fake_kind.checks[-1] == {"1": "3", "2": "1"}
    assert index_of(services, project) == before
    assert (
        fetched.source_state.words()
        == "2 documents changed at the source — Refresh to take them in"
    )
    services.actions.run("spec.refresh_source", services.context.current())
    wait_for(app, lambda: refresher.freshness(project.id, "src1") is None)
    wait_for(app, settled(services, project))
    assert fetched.source_state.words() == "up to date"


def test_a_check_is_not_started_for_a_source_that_is_not_ready(app, fake_kind, services, project):
    activity = added(services, project)
    assert activity._refresher is not None
    activity._refresher.check_all(project.id)
    app.processEvents()
    assert fake_kind.checks == []


def test_a_refused_credential_flips_the_button_to_reconnect(
    app, fetched, fake_kind, services, project
):
    fake_kind.raises = SourceUnavailableError("f rejected the token", needs_reconnect=True)
    services.actions.run("spec.refresh_source", services.context.current())
    wait_for(app, lambda: fetched.connect_button.isVisible())
    wait_for(app, settled(services, project))
    assert (fetched.source_state.words(), fetched.source_state.tone()) == (
        "f rejected the token",
        "error",
    )
    assert fetched.connect_button.text() == "Reconnect to Fake…"
    state = services.actions.spec("spec.refresh_source").state(services.context.current())
    assert not state.enabled and "rejected" in (state.label or "")
    fake_kind.raises = None
    fake_kind.config_changed.emit()  # Reconnected: the refusal is forgotten.
    assert fetched.connect_button.isHidden()
    assert services.actions.spec("spec.refresh_source").state(services.context.current()).enabled


def test_a_source_with_no_kind_in_this_build_is_shown_but_not_fetchable(services, make_project):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.spec.documents import SpecIndex, write_index
    from dplanner.modules.spec.sourced import add_source

    project = make_project("Other")
    index, _src = add_source(SpecIndex([], []), "sharepoint", "Docs", {"url": "https://s"})
    SetModuleDataCommand(project.id, MODULE_ID, write_index(index)).redo(services.document)
    activity = opened(services, project)
    activity.select_source("src1")
    assert "no sharepoint support" in activity.source_state.words()
    assert activity.connect_button.isHidden()


# -- refreshing every source at once ------------------------------------------------------------


@pytest.fixture
def two_kinds(monkeypatch):
    """Two kinds, so a project can hold two sources the refresher fetches together."""
    import dplanner.modules as root

    first = FakeKind(id="one", name="One", label="One Source…", ready=True)
    second = FakeKind(
        id="two",
        name="Two",
        label="Two Source…",
        ready=True,
        located=("Guide", {"site": "https://g", "id": "9"}),
        snapshot=Snapshot(documents=(page("9", "Guide", "# Guide\n"),), order=("9",)),
    )
    monkeypatch.setattr(root, "_source_kinds", lambda *_real: (first, second))
    return first, second


@pytest.fixture
def pair(app, two_kinds, services, make_project):
    """A project with one source of each kind, both fetched.

    The adds are settled one at a time: a fetch is single-flight, so adding the second
    source while the first is still out would leave it unfetched.
    """
    project = make_project("Discovery")
    for kind in ("one", "two"):
        services.actions.run(f"spec.add_source.{kind}", select(services, project))
        wait_for(app, settled(services, project))
    return project


def test_refresh_all_lands_every_source_as_one_undo_entry(app, two_kinds, services, pair):
    refresher = services.tabs.activities()[0]._refresher
    wait_for(app, settled(services, pair))
    assert len(index_of(services, pair).documents) == 3
    depth = len(services.undo._stack)

    for kind in two_kinds:
        kind.snapshot = replace(
            kind.snapshot,
            documents=(*kind.snapshot.documents, page("x", f"New in {kind.name}", "# New\n")),
        )
    assert refresher.refresh_all(pair.id)
    wait_for(app, settled(services, pair))
    assert len(index_of(services, pair).documents) == 5
    # One gesture, one entry — and one Ctrl+Z puts both sources back where they were.
    assert len(services.undo._stack) == depth + 1
    assert services.undo.undo_text() == REFRESH_ALL_LABEL
    services.undo.undo()
    assert len(index_of(services, pair).documents) == 3


def test_refreshing_one_source_still_writes_its_own_entry(app, two_kinds, services, pair):
    """The one-source path is the same machinery: a gesture holding one push places that
    push itself, so nothing about it changed."""
    refresher = services.tabs.activities()[0]._refresher
    wait_for(app, settled(services, pair))
    assert refresher.refresh(pair.id, "src1")
    wait_for(app, settled(services, pair))
    # A gesture holding one push places that push itself, with its own label.
    assert services.undo.undo_text() == "Refresh One"


def test_one_source_refusing_never_stops_the_others(app, two_kinds, services, pair):
    first, second = two_kinds
    refresher = services.tabs.activities()[0]._refresher
    wait_for(app, settled(services, pair))
    failures: list[tuple[str, str]] = []
    refresher.failed.connect(lambda _p, source, message: failures.append((source, message)))
    first.raises = SourceUnavailableError("the site is down")
    second.snapshot = replace(
        second.snapshot, documents=(page("9", "Guide", "# Guide\n\nmore\n", version="2"),)
    )
    assert refresher.refresh_all(pair.id)
    wait_for(app, settled(services, pair))
    assert failures == [("src1", "the site is down")]
    landed = next(d for d in index_of(services, pair).documents if d.key == "9")
    assert landed.version == "2"  # The other source landed all the same.


def test_the_verb_is_greyed_with_its_reason(app, two_kinds, services, pair):
    wait_for(app, settled(services, pair))
    spec = services.actions.spec("spec.refresh_sources")
    assert spec.state(select(services, pair)).enabled
    for kind in two_kinds:
        kind.ready = False
    state = spec.state(select(services, pair))
    assert not state.enabled and "no source is ready" in (state.label or "")


def test_the_freshness_of_each_project_is_its_own(app, two_kinds, services, pair, make_project):
    """Source ids are minted per project: two projects both have a src1."""
    other = make_project("Second")
    services.actions.run("spec.add_source.one", select(services, other))
    wait_for(app, settled(services, other))
    refresher = services.tabs.activities()[0]._refresher
    two_kinds[0].freshness = Freshness(changed=("1",))
    refresher.check_all(pair.id)
    wait_for(app, lambda: refresher.freshness(pair.id, "src1") is not None)
    assert refresher.freshness(other.id, "src1") is None
    assert len(refresher.stale(pair.id)) == 1 and refresher.stale(other.id) == []


# -- what the tab says before you open it -------------------------------------------------------


def specs_row(services):
    from dplanner.framework.builder import INDEX_PANEL_ID

    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    project_row = panel.tree.topLevelItem(0).child(0)
    return next(
        project_row.child(i)
        for i in range(project_row.childCount())
        if project_row.child(i).text(0).startswith("Specs")
    )


def test_a_stale_source_marks_the_tab_title_the_index_row_and_the_line_over_the_tree(
    app, fetched, fake_kind, services, project
):
    """One derivation, three readings: the mark says *there is something here* without
    opening the tab, and the line over the tree says what it is."""
    assert services.tabs.tab_title(fetched) == "Discovery — Specs"
    assert specs_row(services).text(0) == "Specs"
    assert fetched.updates.words() == ""

    fake_kind.freshness = Freshness(changed=("2",), added=("9",))
    refresher = fetched._refresher
    refresher.check_all(project.id)
    wait_for(app, lambda: refresher.freshness(project.id, "src1") is not None)
    services.debounce.flush_all()

    assert services.tabs.tab_title(fetched) == "Discovery — Specs •"
    assert specs_row(services).text(0) == "Specs •"
    assert fetched.updates.words() == (
        "2 documents changed in 1 source — Refresh All to take them in"
    )

    services.actions.run("spec.refresh_source", services.context.current())
    wait_for(app, lambda: refresher.freshness(project.id, "src1") is None)
    wait_for(app, settled(services, project))
    services.debounce.flush_all()
    assert services.tabs.tab_title(fetched) == "Discovery — Specs"
    assert specs_row(services).text(0) == "Specs"
    assert fetched.updates.words() == ""


def test_checking_goes_on_while_the_tab_is_not_the_pane_in_front(
    app, fetched, fake_kind, services, project
):
    """A badge that only lit while you were already looking at the tab would say nothing.
    The watch follows whether a Specs tab is open, and `close` is what ends it."""
    before = len(fake_kind.checks)
    fetched.on_deactivated()
    fetched._refresher.check_all(project.id)
    wait_for(app, lambda: len(fake_kind.checks) > before)
    services.tabs.close_activity(fetched)
    closed = len(fake_kind.checks)
    fetched._refresher.check_all(project.id)
    app.processEvents()
    assert len(fake_kind.checks) == closed


def test_connect_is_not_offered_where_connecting_cannot_help(app, fake_kind, services, project):
    """A malformed locator and a missing git are refusals no dialog lifts. The kind says
    so, and the strip gives the sentence its reason rather than a button about it."""
    tab = added(services, project)
    fake_kind.connectable = False
    fake_kind.ready = False
    tab._refresh_source_strip()
    assert tab.connect_button.isHidden()
    assert (tab.source_state.words(), tab.source_state.tone()) == (
        "Not connected to f",
        "error",
    )
    fake_kind.connectable = True
    tab._refresh_source_strip()
    assert not tab.connect_button.isHidden()
