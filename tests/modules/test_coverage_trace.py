"""The trace over a bare library: columns, links, and the one path rule — no Qt, no
store, every fact handed in through fake readers."""

from dplanner.core.anchors import Anchor
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.coverage.trace import (
    FEATURES,
    MILESTONES,
    NO_MILESTONE,
    OUTCOMES,
    SPEC,
    Citation,
    Document,
    Feature,
    Readers,
    TestRow,
    build,
    milestone_token,
)

SPEC_TEXT = """# Auth

Operators MUST be able to import a CSV of readings.

Every login is logged.

Nobody cites this paragraph.
"""


def graph():
    """work → Import (a feature) → M1; other → Export (a feature, no milestone); a login
    step under M1 that no feature gathers; two more features standing on their own."""
    library = Library()
    project = Project(title="P")
    library.add_child(library.id, project)
    titles = ["work", "Import", "M1", "other", "Export", "login", "Dark mode", "Ghost"]
    for title in titles:
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    work, imp, m1, other, export, login, _dark, _ghost = project.steps
    SetEdgesCommand(imp.id, "requires", [work.id]).redo(library)
    SetEdgesCommand(m1.id, "requires", [imp.id, login.id]).redo(library)
    SetEdgesCommand(export.id, "requires", [other.id]).redo(library)
    return library, project


def feature_of(project, title):
    """A feature's item id: its step's, since a feature *is* a step."""
    step = next(s for s in project.steps if s.title == title)
    return f"feature:{step.id}"


def item(trace, item_id):
    found = trace.item(item_id)
    assert found is not None
    return found


def no_files(_node_id, _module_id):
    raise KeyError("no store behind this library")


def anchored(start: int, end: int) -> Anchor:
    return Anchor("anchored", start, end, digest="d")


def readers(project) -> Readers:
    work, imp, m1, other, export, login, dark, ghost = project.steps
    csv_at = anchored(SPEC_TEXT.index("Operators"), SPEC_TEXT.index("readings.") + 9)
    login_at = anchored(SPEC_TEXT.index("Every"), SPEC_TEXT.index("logged.") + 7)
    lost = Anchor("lost", digest="d")
    features = [
        Feature(
            imp.id,
            "Import",
            imp.id,
            (
                Citation(
                    "spec",
                    "Operators MUST be able to import a CSV of readings.",
                    None,
                    csv_at,
                ),
                Citation("spec", "Every login is logged.", None, login_at),
            ),
        ),
        Feature(
            export.id,
            "Export",
            export.id,
            (Citation("spec", "Every login is logged.", None, login_at),),
        ),
        Feature(dark.id, "Dark mode", dark.id, ()),
        Feature(ghost.id, "Ghost", ghost.id, (Citation("spec", "vanished", None, lost),)),
    ]
    tests = {
        work.id: [TestRow("T100", "imports", work.id, "work")],
        imp.id: [TestRow("T101", "imports fast", imp.id, "Import")],
        login.id: [TestRow("T102", "logs in", login.id, "login")],
        other.id: [TestRow("T103", "exports", other.id, "other")],
    }

    def tests_of(library, project, step_id, stops_at):
        from dplanner.domain.scope import cone

        held = cone(library, project, step_id, stops_at=stops_at)
        rows = []
        for step in [*held.steps, project.step(step_id)]:
            rows += tests.get(step.id, [])
        return rows

    return Readers(
        features=lambda _l, _p, _f: features,
        documents=lambda _p, _f: [
            Document("spec", "markdown", SPEC_TEXT),
            Document("empty", "markdown", ""),
        ],
        is_feature=lambda step: step.id in (imp.id, export.id, dark.id, ghost.id),
        is_milestone=lambda step: step.id == m1.id,
        milestone_label=lambda step: "M1" if step.id == m1.id else "",
        is_done=lambda step: step.id == export.id,
        tests=tests_of,
        results=lambda _p: {"T100": "ok", "T102": "failed"},
        docs=lambda _l, _p, step_id: {imp.id: "current", m1.id: "stale"}.get(step_id, ""),
    )


def test_the_columns_hold_documents_passages_features_milestones_tests_and_docs():
    library, project = graph()
    work, imp, m1, *_rest = project.steps
    trace = build(readers(project), library, project, no_files)
    spec = [item.id for item in trace.column(SPEC)]
    assert spec == ["doc:spec", "passage:spec:0", "passage:spec:1", "passage:spec:2", "doc:empty"]
    # Passages sit in document order; the lost one last. A passage two features cite is one item.
    titles = {item.id: item.title for item in trace.items}
    assert titles["passage:spec:0"].startswith("Operators MUST")
    imp, export = project.steps[1], project.steps[4]
    assert item(trace, "passage:spec:1").features == {imp.id, export.id}
    assert item(trace, "passage:spec:2").state == "lost"
    assert item(trace, "doc:spec").detail == "2 of 3 paragraphs cited · 1 to review"
    assert item(trace, "doc:empty").muted
    # Features come milestone-first, then the rest in catalogue order.
    assert [item.id for item in trace.column(FEATURES)] == [
        feature_of(project, "Import"),
        feature_of(project, "Export"),
        feature_of(project, "Dark mode"),
        feature_of(project, "Ghost"),
    ]
    assert item(trace, feature_of(project, "Dark mode")).detail == ""
    assert not item(trace, feature_of(project, "Dark mode")).muted
    assert item(trace, feature_of(project, "Export")).tone == "good"
    assert [item.id for item in trace.column(MILESTONES)] == [milestone_token(m1.id), NO_MILESTONE]
    assert item(trace, milestone_token(m1.id)).detail == "M1 · 1 feature"
    outcomes = [item.id for item in trace.column(OUTCOMES)]
    assert outcomes == [
        "test:T100",
        "test:T101",
        f"docs:{imp.id}",
        "test:T103",
        "test:T102",
        f"docs:{m1.id}",
    ]
    assert item(trace, "test:T100").state == "ok" and item(trace, "test:T101").state == "pending"
    assert item(trace, "test:T100").target == ("test", f"{work.id}\0T100")
    assert item(trace, f"docs:{m1.id}").state == "stale"
    assert [f.title for f in trace.unsourced] == ["Dark mode"]


def test_links_join_neighbouring_columns_only():
    library, project = graph()
    m1 = project.steps[2]
    trace = build(readers(project), library, project, no_files)
    pairs = {(link.source, link.target) for link in trace.links}
    m = milestone_token(m1.id)
    assert ("passage:spec:0", feature_of(project, "Import")) in pairs
    assert ("passage:spec:1", feature_of(project, "Import")) in pairs and (
        "passage:spec:1",
        feature_of(project, "Export"),
    ) in pairs
    assert (feature_of(project, "Import"), m) in pairs and (
        feature_of(project, "Export"),
        NO_MILESTONE,
    ) in pairs
    assert (m, "test:T100") in pairs and (NO_MILESTONE, "test:T103") in pairs
    assert (m, "test:T102") in pairs and (m, f"docs:{m1.id}") in pairs
    by_id = {item.id: item for item in trace.items}
    for link in trace.links:
        assert by_id[link.target].column == by_id[link.source].column + 1


def test_the_path_is_feature_membership():
    library, project = graph()
    imp, m1 = project.steps[1], project.steps[2]
    trace = build(readers(project), library, project, no_files)
    m = milestone_token(m1.id)
    # A feature lights exactly its chain — not the other feature's tests, not the
    # milestone's direct work.
    lit = trace.path(feature_of(project, "Import")).items
    assert lit == {
        "doc:spec",
        "passage:spec:0",
        "passage:spec:1",
        feature_of(project, "Import"),
        m,
        "test:T100",
        "test:T101",
        f"docs:{imp.id}",
        f"docs:{m1.id}",
    }
    # A milestone lights everything behind it, including what it holds directly.
    lit = trace.path(m).items
    assert (
        "test:T102" in lit
        and feature_of(project, "Import") in lit
        and feature_of(project, "Export") not in lit
    )
    # A passage two features cite lights both chains.
    lit = trace.path("passage:spec:1").items
    assert {
        feature_of(project, "Import"),
        feature_of(project, "Export"),
        "test:T103",
        "test:T100",
    } <= lit
    # A test held directly by the milestone lights the milestone and its docs, nothing else.
    lit = trace.path("test:T102").items
    assert lit == {m, "test:T102", f"docs:{m1.id}"}
    # Every lit link joins two lit items.
    path = trace.path(feature_of(project, "Import"))
    for index in path.links:
        link = trace.links[index]
        assert link.source in path.items and link.target in path.items
    assert trace.path("no:such").items == frozenset()
