"""The topology gate: a graph-editing verb runs only after the topology has been read.

The shared ``registry`` fixture carries a read record with no file, so every other CLI test
adds steps freely. The ``gated_cli`` fixture (``tests/cli/conftest.py``) is the real thing,
over a record under ``tmp_path``; the house format behind the same record is
``test_test_format.py``.
"""

import json

import pytest
from tests.cli.skill_helpers import noun_verbs

from dplanner.cli.gate import ReadRecord, TopologyGate, digest


def data(text):
    return json.loads(text)


# -- the gate on its own -----------------------------------------------------------------------


def test_digest_is_stable_and_short():
    assert digest("abc") == digest("abc") and len(digest("abc")) == 16
    assert digest("abc") != digest("abd")


def test_a_record_with_no_file_refuses_nothing_and_writes_nothing(tmp_path):
    from dplanner.domain.model import Project

    gate = TopologyGate(reads=ReadRecord(None), topology_of=lambda _project: "")
    assert gate.refusal(Project(title="P")) is None
    gate.record("p", "text")
    assert list(tmp_path.iterdir()) == []


def test_the_record_is_one_digest_per_project_under_its_own_door(tmp_path):
    """One file serves both doors, so a key says which one it was read through."""
    from dplanner.domain.model import Project

    record = tmp_path / "deep" / "reads.json"
    texts = {"p1": "Shape one.", "p2": ""}
    gate = TopologyGate(reads=ReadRecord(record), topology_of=lambda project: texts[project.id])
    one, two = Project(title="One"), Project(title="Two")
    one.id, two.id = "p1", "p2"
    assert "has not been read" in (gate.refusal(one) or "")
    assert "no topology yet" in (gate.refusal(two) or "")
    gate.record("p1", "Shape one.")
    assert gate.refusal(one) is None
    assert json.loads(record.read_text()) == {
        "format": 2,
        "read": {"topology:p1": digest("Shape one.")},
    }
    texts["p1"] = "Shape one, revised."
    assert "changed since you read it" in (gate.refusal(one) or "")


def test_a_corrupt_record_reads_as_nothing_read(tmp_path):
    from dplanner.domain.model import Project

    record = tmp_path / "reads.json"
    record.write_text("not json")
    gate = TopologyGate(reads=ReadRecord(record), topology_of=lambda _project: "Shape.")
    assert "has not been read" in (gate.refusal(Project(title="P")) or "")


# -- the verbs behind it -----------------------------------------------------------------------


GATED = [
    ("step", "add", "Discovery", "Deploy"),
    ("project", "clear-steps", "Discovery"),
    ("step", "add", "Discovery", "Bulk import", "--feature"),
]


@pytest.mark.parametrize("argv", GATED, ids=lambda argv: " ".join(argv[:2]))
def test_a_project_without_a_topology_refuses_graph_edits(gated_cli, argv):
    out = gated_cli(*argv, expect=1)
    assert "no topology yet" in out and "topology set 'Discovery'" in out
    assert data(gated_cli("step", "list", "Discovery", "--json"))["steps"] == []


def test_the_topology_must_be_read_before_the_graph_is_edited(gated_cli):
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Views are features.")
    out = gated_cli("step", "add", "Discovery", "Deploy", expect=1)
    assert "has not been read" in out and "topology show 'Discovery'" in out
    gated_cli("topology", "show", "Discovery")
    gated_cli("step", "add", "Discovery", "Deploy")
    gated_cli("step", "add", "Discovery", "Test", "--after", "Deploy")
    gated_cli("step", "unlink", "Test", "Deploy")
    gated_cli("step", "link", "Test", "Deploy")
    gated_cli("step", "add", "Discovery", "Bulk import", "--feature")
    gated_cli("feature", "set", "Deploy")
    gated_cli("feature", "clear", "Deploy")
    gated_cli("step", "remove", "Bulk import")
    gated_cli("step", "remove", "Test")
    gated_cli("step", "duplicate", "Deploy")


def test_a_changed_topology_is_unread_again(gated_cli):
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Views are features.")
    gated_cli("topology", "show", "Discovery")
    gated_cli("step", "add", "Discovery", "Deploy")
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Views and APIs are features.")
    out = gated_cli("step", "add", "Discovery", "Test", expect=1)
    assert "changed since you read it" in out
    gated_cli("topology", "show", "Discovery")
    gated_cli("step", "add", "Discovery", "Test")


def test_the_read_is_per_project(gated_cli, workspace):
    gated_cli("project", "create", "Other", "--dir", str(workspace / "other"))
    for title in ("Discovery", "Other"):
        gated_cli("topology", "set", title, "--file", "-", stdin=f"{title} shape.")
    gated_cli("topology", "show", "Discovery")
    gated_cli("step", "add", "Discovery", "Deploy")
    assert "has not been read" in gated_cli("step", "add", "Other", "Deploy", expect=1)


def test_content_edits_are_never_gated(gated_cli):
    """A title, a description, a feature's wording: content, not shape. Only the graph
    waits on the topology — and so does a project with no steps at all."""
    gated_cli("project", "rename", "Discovery", "--title", "Discovery 2")
    gated_cli("topology", "set", "Discovery 2", "--file", "-", stdin="Shape.")
    gated_cli("topology", "show", "Discovery 2")
    gated_cli("step", "add", "Discovery 2", "Deploy")
    gated_cli("step", "add", "Discovery 2", "Bulk import", "--feature")
    gated_cli("topology", "set", "Discovery 2", "--file", "-", stdin="Shape, revised.")
    gated_cli("step", "rename", "Deploy", "--title", "Ship")
    gated_cli("describe", "set", "Ship", "--file", "-", stdin="The release step.")
    gated_cli("feature", "uncite", "Bulk import", "--all")
    gated_cli("estimate", "set", "Ship", "--days", "1")
    assert "changed since you read it" in gated_cli("step", "add", "Discovery 2", "Test", expect=1)


def test_nothing_is_written_when_the_gate_refuses(gated_cli, workspace):
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Shape.")
    before = sorted(str(p) for p in (workspace / "discovery").rglob("*"))
    gated_cli("step", "add", "Discovery", "Deploy", "--days", "2", expect=1)
    after = sorted(str(p) for p in (workspace / "discovery").rglob("*"))
    assert before == after


def test_the_skill_marks_gated_verbs(gated_cli):
    """The dagger is where an agent reads that a verb costs a `topology show` first."""
    skill = gated_cli("skill", "show")
    verbs = noun_verbs(skill)
    assert "add†" in verbs["step"] and "duplicate†" in verbs["step"]
    # Reading the graph is never gated, and `step list` sits next to verbs that are.
    assert "list" in verbs["step"] and "list†" not in verbs["step"]
    assert not any(verb.endswith("†") for verb in verbs["describe"])
    # Moving cards about is presentation, not shape: never gated.
    assert not any(verb.endswith("†") for verb in verbs["layout"])
    assert "† reads the topology first" in skill


def test_reading_the_default_is_not_reading_the_topology(gated_cli):
    """`topology show` prints the house default on a project with none — and a project
    with none still refuses, because the default is not that project's own claim."""
    out = gated_cli("topology", "show", "Discovery")
    assert "# How a graph is shaped" in out
    refused = gated_cli("step", "add", "Discovery", "Deploy", expect=1)
    assert "no topology yet" in refused
    assert "topology show 'Discovery'" in refused and "topology set 'Discovery'" in refused


def test_brief_records_the_read_like_any_other(gated_cli):
    """The flag chooses what is printed, never what is recorded."""
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Views are features.")
    gated_cli("topology", "show", "Discovery", "--brief")
    gated_cli("step", "add", "Discovery", "Deploy")
