"""``dplanner coverage``: the trace an agent reads, over a real library — the spec,
its features, their milestone, tests and docs, and what to do after the spec changed."""

import json

import pytest
from tests.cli.spec_helpers import source

SPEC = """# Readings

## Import

Operators MUST be able to import a CSV of readings in one go.

Every rejected row is reported with its line number.

## Export

Operators MAY export the last month as a spreadsheet.

## Dashboard

The dashboard shows a graph of every sensor's readings.
"""


def data(text):
    return json.loads(text)


@pytest.fixture
def project(cli, cli_stdin, tmp_path):
    cli("project", "create", "Readings")
    cli_stdin("topology", "set", "Readings", "--file", "-", stdin="Features under milestones.")
    cli("topology", "show", "Readings")
    cli("spec", "import", "Readings", source(tmp_path, "readings.md", SPEC))
    cli("feature", "add", "Readings", "Import", "--document", "readings", "--quote", "import a CSV")
    cli("feature", "cite", "Readings", "f1", "--document", "readings", "--quote", "rejected row")
    cli("feature", "add", "Readings", "Export", "--document", "readings", "--quote", "MAY export")
    cli("feature", "add", "Readings", "Dark mode")
    cli("step", "add", "Readings", "Parse the file")
    cli("test", "add", "Parse the file", "parses a CSV")
    cli("step", "add", "Readings", "Import", "--feature", "f1", "--after", "Parse the file")
    cli("step", "add", "Readings", "Export", "--feature", "f2")
    cli("step", "add", "Readings", "Beta", "--after", "Import")
    cli("milestone", "set", "Beta", "--label", "M1")
    cli("--project", "Readings", "test-run", "start")
    cli("test-run", "mark", "T100", "ok")
    return "Readings"


def test_show_walks_from_the_document_to_the_tests(cli, project):
    out = cli("coverage", "show", project)
    assert "readings: 3 of 4 paragraphs cited" in out
    assert '"import a CSV"' in out and "→ f1 Import" in out
    assert "↳ Beta (M1 · 1 feature)" in out
    assert "T100   parses a CSV" in out
    assert "↳ Not in a milestone" in out  # f2 has a step but no milestone gathers it.
    assert "Features citing no passage:" in out and "f3 Dark mode  (not placed)" in out

    shown = data(cli("coverage", "show", project, "--json"))
    columns = {item["id"]: item["column"] for item in shown["items"]}
    assert columns["doc:readings"] == 0 and columns["feature:f1"] == 1
    assert columns["test:T100"] == 3 and [f["id"] for f in shown["unsourced"]] == ["f3"]
    assert shown["documents"][0]["cited"] == 3
    only = data(cli("coverage", "show", project, "--feature", "Export", "--json"))
    assert {item["id"] for item in only["items"]} >= {"feature:f2", "bucket:none"}
    assert "feature:f1" not in {item["id"] for item in only["items"]}
    assert "several" in cli("coverage", "show", project, "--feature", "port", expect=1)


def test_spec_reads_a_document_paragraph_by_paragraph(cli, project):
    out = cli("coverage", "spec", project, "readings")
    assert "[f1]  Readings > Import" in out and "[-]  Readings > Dashboard" in out
    assert "3 of 4 paragraphs cited" in out
    uncovered = data(cli("coverage", "spec", project, "readings", "--uncovered", "--json"))
    assert [block["heading"] for block in uncovered["blocks"]] == ["Readings > Dashboard"]
    assert uncovered["blocks"][0]["text"].startswith("The dashboard")
    assert "1 uncited" in cli("coverage", "spec", project, "readings", "--uncovered")
    assert "no spec document" in cli("coverage", "spec", project, "ghost", expect=1)


def test_review_is_quiet_until_the_spec_moves_on(cli, project, tmp_path):
    out = cli("coverage", "review", project)
    # Dark mode cites nothing: the one finding on a fresh project.
    assert "unsourced: Dark mode" in out and "coverage spec" in out
    changed = SPEC.replace("import a CSV", "upload a CSV").replace(
        "Every rejected row is reported", "Every rejected row is reported, loudly,"
    )
    cli("spec", "import", project, source(tmp_path, "readings2.md", changed), "--name", "readings")
    report = data(cli("coverage", "review", project, "--json"))
    kinds = {(row["kind"], row["subject"]) for row in report["findings"]}
    assert kinds == {("drifted", "f1"), ("behind", "f1"), ("unsourced", "f3")}
    advice = {row["kind"]: row["advice"] for row in report["findings"]}
    assert "--accept-drift" in advice["drifted"] and "feature reanchor" in advice["behind"]
    cli("feature", "reanchor", project, "--all", "--accept-drift")
    assert "unsourced" in cli("coverage", "review", project)
    cli("feature", "cite", project, "f3", "--document", "readings", "--quote", "dashboard shows")
    assert "every passage anchors" in cli("coverage", "review", project)
