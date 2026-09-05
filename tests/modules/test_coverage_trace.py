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
    """work → Import (feature f1) → M1; other → Export (feature f2, no milestone);
    a login step under M1 that no feature gathers; f3 unplaced."""
    library = Library()
    project = Project(title="P")
    library.add_child(library.id, project)
    titles = ["work", "Import", "M1", "other", "Export", "login"]
    for title in titles:
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    work, imp, m1, other, export, login = project.steps
    SetEdgesCommand(imp.id, "requires", [work.id]).redo(library)
    SetEdgesCommand(m1.id, "requires", [imp.id, login.id]).redo(library)
    SetEdgesCommand(export.id, "requires", [other.id]).redo(library)
    return library, project


def item(trace, item_id):
    found = trace.item(item_id)
    assert found is not None
    return found


def no_files(_node_id, _module_id):
    raise KeyError("no store behind this library")


def anchored(start: int, end: int) -> Anchor:
    return Anchor("anchored", start, end, digest="d")


def readers(project) -> Readers:
    work, imp, m1, other, export, login = project.steps
    csv_at = anchored(SPEC_TEXT.index("Operators"), SPEC_TEXT.index("readings.") + 9)
    login_at = anchored(SPEC_TEXT.index("Every"), SPEC_TEXT.index("logged.") + 7)
    lost = Anchor("lost", digest="d")
    features = [
        Feature(
            "f1",
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
            "f2",
            "Export",
            export.id,
            (Citation("spec", "Every login is logged.", None, login_at),),
        ),
        Feature("f3", "Dark mode", None, ()),
        Feature("f4", "Ghost", None, (Citation("spec", "vanished", None, lost),)),
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
        is_feature=lambda step: step.id in (imp.id, export.id),
        is_milestone=lambda step: step.id == m1.id,
        milestone_label=lambda step: "M1" if step.id == m1.id else "",
        is_done=lambda step: step.id == export.id,
        tests=tests_of,
        results=lambda _p: {"T100": "ok", "T102": "failed"},
        docs=lambda _l, _p, step_id: {imp.id: "current", m1.id: "stale"}.get(step_id, ""),
    )


def test_the_columns_hold_documents_passages_features_milestones_tests_and_docs():
    library, project = graph()
    work, imp, m1, _other, _export, _login = project.steps
    trace = build(readers(project), library, project, no_files)
    spec = [item.id for item in trace.column(SPEC)]
    assert spec == ["doc:spec", "passage:spec:0", "passage:spec:1", "passage:spec:2", "doc:empty"]
    # Passages sit in document order; the lost one last. A passage two features cite is one item.
    titles = {item.id: item.title for item in trace.items}
    assert titles["passage:spec:0"].startswith("Operators MUST")
    assert item(trace, "passage:spec:1").features == {"f1", "f2"}
    assert item(trace, "passage:spec:2").state == "lost"
    assert item(trace, "doc:spec").detail == "2 of 3 paragraphs cited · 1 to review"
    assert item(trace, "doc:empty").muted
    # Features come milestone-first, then the rest in catalogue order.
    assert [item.id for item in trace.column(FEATURES)] == [
        "feature:f1",
        "feature:f2",
        "feature:f3",
        "feature:f4",
    ]
    assert item(trace, "feature:f3").detail == "not placed" and item(trace, "feature:f3").muted
    assert item(trace, "feature:f2").tone == "good"
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
    assert [f.id for f in trace.unsourced] == ["f3"]


def test_links_join_neighbouring_columns_only():
    library, project = graph()
    _work, _imp, m1, _other, _export, _login = project.steps
    trace = build(readers(project), library, project, no_files)
    pairs = {(link.source, link.target) for link in trace.links}
    m = milestone_token(m1.id)
    assert ("passage:spec:0", "feature:f1") in pairs
    assert ("passage:spec:1", "feature:f1") in pairs and ("passage:spec:1", "feature:f2") in pairs
    assert ("feature:f1", m) in pairs and ("feature:f2", NO_MILESTONE) in pairs
    assert (m, "test:T100") in pairs and (NO_MILESTONE, "test:T103") in pairs
    assert (m, "test:T102") in pairs and (m, f"docs:{m1.id}") in pairs
    by_id = {item.id: item for item in trace.items}
    for link in trace.links:
        assert by_id[link.target].column == by_id[link.source].column + 1


def test_the_path_is_feature_membership():
    library, project = graph()
    _work, imp, m1, _other, _export, _login = project.steps
    trace = build(readers(project), library, project, no_files)
    m = milestone_token(m1.id)
    # A feature lights exactly its chain — not the other feature's tests, not the
    # milestone's direct work.
    lit = trace.path("feature:f1").items
    assert lit == {
        "doc:spec",
        "passage:spec:0",
        "passage:spec:1",
        "feature:f1",
        m,
        "test:T100",
        "test:T101",
        f"docs:{imp.id}",
        f"docs:{m1.id}",
    }
    # A milestone lights everything behind it, including what it holds directly.
    lit = trace.path(m).items
    assert "test:T102" in lit and "feature:f1" in lit and "feature:f2" not in lit
    # A passage two features cite lights both chains.
    lit = trace.path("passage:spec:1").items
    assert {"feature:f1", "feature:f2", "test:T103", "test:T100"} <= lit
    # A test held directly by the milestone lights the milestone and its docs, nothing else.
    lit = trace.path("test:T102").items
    assert lit == {m, "test:T102", f"docs:{m1.id}"}
    # Every lit link joins two lit items.
    path = trace.path("feature:f1")
    for index in path.links:
        link = trace.links[index]
        assert link.source in path.items and link.target in path.items
    assert trace.path("no:such").items == frozenset()
