"""``dplanner feature``: which steps are features, what each was read from, and lint —
over a real library. No ``qapp`` fixture: this is an agent's workflow.

A feature is a step, so there is no verb here that creates one: ``step add --feature`` is
the door in and ``step remove`` the door out.
"""

import json

import pytest
from tests.cli.spec_helpers import source, tiny_pdf


def data(text):
    return json.loads(text)


def checks_in(report):
    return sorted({row["check"] for row in report["findings"]})


@pytest.fixture
def project(cli):
    cli("project", "create", "Search rewrite")
    return "Search rewrite"


# -- a feature is a step -----------------------------------------------------------------------


def test_step_add_with_the_flag_is_born_a_feature(cli, project, workspace):
    cli("step", "add", project, "Build the importer")
    out = cli("step", "add", project, "Bulk import", "--feature", "--after", "Build the importer")
    assert "feature" in out
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [(row["step"]["key"], row["step"]["title"]) for row in listed] == [("F2", "Bulk import")]
    entry = json.loads(next(workspace.glob("*/steps/bulk-import/modules/feature.json")).read_text())
    assert entry == {"on": True, "format": 3}
    assert "F2   Bulk import  — cites nothing" in cli("feature", "list", project)


def test_set_and_clear_are_idempotent_and_the_passages_are_shelved(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here."))
    cli("step", "add", project, "Search")
    assert "is a feature" in cli("feature", "set", "Search")
    assert "already a feature" in cli("feature", "set", "Search")
    cli("feature", "cite", "Search", "--document", "s", "--quote", "rule is here")
    assert "passages are shelved" in cli("feature", "clear", "Search")
    assert "not a feature" in cli("feature", "clear", "Search")
    assert data(cli("feature", "list", project, "--json"))["features"] == []
    # Back on, and what it cited comes back with it — the shelf's promise.
    cli("feature", "set", "Search")
    shown = data(cli("feature", "show", "Search", "--json"))
    assert [row["quote"] for row in shown["cites"]] == ["rule is here"]


def test_removing_the_step_removes_the_feature(cli, project):
    cli("step", "add", project, "Search", "--feature")
    cli("step", "remove", "Search")
    assert data(cli("feature", "list", project, "--json"))["features"] == []


def test_two_steps_may_both_be_features(cli, project):
    """The one-instance rule went with the catalogue: there is nothing to instantiate."""
    cli("step", "add", project, "One", "--feature")
    cli("step", "add", project, "Two", "--feature")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [row["step"]["title"] for row in listed] == ["One", "Two"]


def test_a_verb_refuses_a_step_that_is_not_a_feature(cli, project):
    cli("step", "add", project, "Search")
    out = cli("feature", "show", "Search", expect=1)
    assert "is not a feature" in out and "feature set" in out


# -- where in the spec it came from --------------------------------------------------------------


def test_the_flag_finds_the_quote_and_records_its_page(cli, project, tmp_path):
    pdf = tiny_pdf("Nothing here.", "All credentials MUST be hashed.")
    cli("spec", "import", project, source(tmp_path, "s.pdf", pdf))
    out = cli(
        "step",
        "add",
        project,
        "Hashing",
        "--feature",
        "--document",
        "s",
        "--quote",
        "MUST be hashed",
    )
    assert "s p.2" in out
    [passage] = data(cli("feature", "show", "Hashing", "--json"))["cites"]
    assert (passage["document"], passage["quote"], passage["page"]) == ("s", "MUST be hashed", 2)
    assert passage["anchoring"] == "anchored" and len(passage["digest"]) == 16
    assert "s p.2" in cli("feature", "list", project)


def test_an_absent_quote_warns_but_still_adds(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing here.")))
    out = cli(
        "step",
        "add",
        project,
        "Ghost",
        "--feature",
        "--document",
        "s",
        "--quote",
        "does not appear",
    )
    assert "warning" in out and "not found" in out
    assert data(cli("feature", "list", project, "--json"))["features"]


def test_a_page_that_disagrees_with_the_quote_warns_but_is_kept(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing.", "The rule.")))
    out = cli(
        "step",
        "add",
        project,
        "Rule",
        "--feature",
        "--document",
        "s",
        "--quote",
        "The rule",
        "--page",
        "1",
    )
    assert "not found on page 1 — it anchors on 2" in out
    assert data(cli("feature", "show", "Rule", "--json"))["cites"][0]["page"] == 1


def test_a_quote_on_several_pages_accepts_any_of_them_as_page(cli, project, tmp_path):
    # The same sentence on pages 1 and 2: --page is disambiguation, not a mismatch.
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("The rule.", "The rule.")))
    out = cli(
        "step",
        "add",
        project,
        "Rule",
        "--feature",
        "--document",
        "s",
        "--quote",
        "The rule",
        "--page",
        "2",
    )
    assert "warning" not in out
    assert data(cli("feature", "show", "Rule", "--json"))["cites"][0]["page"] == 2
    # Unnamed, the first occurrence is recorded.
    cli("step", "add", project, "Again", "--feature", "--document", "s", "--quote", "The rule")
    assert data(cli("feature", "show", "Again", "--json"))["cites"][0]["page"] == 1


def test_strict_refuses_a_quote_that_does_not_anchor(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing here.")))
    out = cli(
        "step",
        "add",
        project,
        "Ghost",
        "--feature",
        "--document",
        "s",
        "--quote",
        "does not appear",
        "--strict",
        expect=1,
    )
    assert "--strict" in out
    # The run is one transaction: a refused author leaves no step behind.
    assert data(cli("step", "list", project, "--json"))["steps"] == []
    # An anchoring quote passes strict; no quote at all passes too (nothing to refute).
    cli(
        "step",
        "add",
        project,
        "Real",
        "--feature",
        "--document",
        "s",
        "--quote",
        "Nothing here",
        "--strict",
    )
    cli("step", "add", project, "Quoteless", "--feature", "--document", "s", "--strict")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [row["step"]["title"] for row in listed] == ["Real", "Quoteless"]


def test_quotes_are_validated_against_prose_documents_too(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule\nis here."))
    out = cli(
        "step",
        "add",
        project,
        "Rule",
        "--feature",
        "--document",
        "s",
        "--quote",
        "rule is here",
    )
    assert "warning" not in out
    assert data(cli("feature", "show", "Rule", "--json"))["cites"][0]["page"] is None


def test_a_quote_needs_a_document_and_a_document_needs_the_flag(cli, project):
    assert "--document" in cli(
        "step", "add", project, "Rule", "--feature", "--quote", "orphan", expect=1
    )
    assert "needs --feature" in cli("step", "add", project, "Rule", "--document", "s", expect=1)


def test_list_filters_by_document(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "# S"))
    cli("spec", "import", project, source(tmp_path, "t.md", "# T"))
    cli("step", "add", project, "From S", "--feature", "--document", "s")
    cli("step", "add", project, "From T", "--feature", "--document", "t")
    cli("step", "add", project, "By hand", "--feature")
    listed = data(cli("feature", "list", project, "--document", "t", "--json"))["features"]
    assert [row["step"]["title"] for row in listed] == ["From T"]


def test_cite_adds_passages_and_uncite_takes_them_away(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here.\n\nAnd there."))
    cli("step", "add", project, "Rule", "--feature", "--document", "s", "--quote", "rule is here")
    out = cli("feature", "cite", "Rule", "--document", "s", "--quote", "And there")
    assert "cites 2 passages" in out
    # The same passage again, however it is spaced or cased, is not a third.
    assert "already cites" in cli(
        "feature", "cite", "Rule", "--document", "s", "--quote", "and  THERE"
    )
    shown = data(cli("feature", "show", "Rule", "--json"))
    assert [row["quote"] for row in shown["cites"]] == ["rule is here", "And there"]
    assert "s +1" in cli("feature", "list", project)
    assert "> And there" in cli("feature", "show", "Rule")
    assert "1 passage removed" in cli(
        "feature", "uncite", "Rule", "--document", "s", "--quote", "And there"
    )
    assert "nothing to remove" in cli(
        "feature", "uncite", "Rule", "--document", "s", "--quote", "And there"
    )
    cli("feature", "uncite", "Rule", "--all")
    assert data(cli("feature", "show", "Rule", "--json"))["cites"] == []
    assert "--all" in cli("feature", "uncite", "Rule", expect=1)


# -- what older builds wrote ----------------------------------------------------------------


def test_a_catalogue_collapses_onto_its_steps_and_stays_collapsed(
    cli, project, workspace, tmp_path
):
    """Format 2 kept a record beside the project and its id beside the step. Format 3 has
    the passages on the step, the catalogue gone, and a second open changing nothing."""
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here."))
    cli("step", "add", project, "Placed")
    directory = next(workspace.glob("*/steps/placed")) / "modules"
    directory.mkdir(exist_ok=True)
    (directory / "feature.json").write_text(json.dumps({"feature": "f1", "format": 2}))
    catalogue = next(workspace.glob("*/modules")) / "feature.json"
    catalogue.write_text(
        json.dumps(
            {
                "format": 2,
                "features": [
                    {
                        "id": "f1",
                        "title": "Rule",
                        "description": "What the rule means.",
                        "sources": [{"document": "s", "quote": "rule is here"}],
                    },
                    {"id": "f2", "title": "On its own", "description": "Its own prose."},
                ],
            }
        )
    )
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert sorted(row["step"]["title"] for row in listed) == ["On its own", "Placed"]
    # The placed record's passage is the step's now, and its differing title is recorded
    # in the prose rather than written over the step's own.
    shown = data(cli("feature", "show", "Placed", "--json"))
    assert [row["quote"] for row in shown["cites"]] == ["rule is here"]
    described = cli("describe", "show", "Placed")
    assert "Catalogued as “Rule”" in described and "What the rule means." in described
    # The unplaced record became the step it always meant to be, titled and described.
    assert "Its own prose." in cli("describe", "show", "On its own")
    assert not catalogue.exists()
    # A second open finds nothing to move.
    before = json.loads((directory / "feature.json").read_text())
    cli("feature", "list", project)
    assert json.loads((directory / "feature.json").read_text()) == before
    assert not catalogue.exists()


def test_a_marker_naming_a_record_that_is_gone_becomes_a_feature_citing_nothing(
    cli, project, workspace
):
    cli("step", "add", project, "Search")
    directory = next(workspace.glob("*/steps/search")) / "modules"
    directory.mkdir(exist_ok=True)
    (directory / "feature.json").write_text(json.dumps({"feature": "f9", "format": 2}))
    assert data(cli("feature", "show", "Search", "--json"))["cites"] == []
    assert json.loads((directory / "feature.json").read_text()) == {"on": True, "format": 3}


def test_a_retired_marker_is_a_whole_feature(cli, project, workspace):
    """``step_feature`` wrote ``{"on": true}``. With no catalogue left to be missing from,
    the takeover's answer is complete: a feature that cites nothing."""
    cli("step", "add", project, "Search")
    modules = next(workspace.glob("*/steps/search")) / "modules"
    modules.mkdir(exist_ok=True)
    (modules / "step_feature.json").write_text(json.dumps({"on": True}))
    assert "Search  — cites nothing" in cli("feature", "list", project)
    assert not (modules / "step_feature.json").exists()
    assert json.loads((modules / "feature.json").read_text()) == {"on": True, "format": 3}
    assert data(cli("scope", "show", "Search", "--json"))["kind"] == "feature"


def test_duplicating_a_feature_step_copies_the_feature_but_not_its_passages(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here."))
    cli("step", "add", project, "Search", "--feature", "--document", "s", "--quote", "rule is here")
    cli("step", "duplicate", "Search")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert len(listed) == 2
    assert [len(row["cites"]) for row in listed] == [1, 0]


# -- lint --------------------------------------------------------------------------------------


def test_a_replaced_document_grades_every_passage_and_reanchor_catches_up(cli, project, tmp_path):
    def doc(name, text):
        return source(tmp_path, name, text)

    spec = (
        "# Auth\n\nThe rule is argon2id, and every hash MUST be salted.\n\n"
        "Logins are logged with the operator's name.\n\n"
        "Sessions expire after an hour of silence.\n\nPasswords rotate every ninety days.\n"
    )
    cli("spec", "import", project, doc("s.md", spec), "--name", "s")
    for title, quote in (
        ("Hashing", "argon2id"),
        ("Logging", "Logins are logged"),
        ("Sessions", "Sessions expire after an hour of silence"),
        ("Rotation", "rotate every ninety days"),
    ):
        cli("step", "add", project, title, "--feature", "--document", "s", "--quote", quote)
    cli("step", "add", project, "Quoteless", "--feature", "--document", "s")
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert not any(check.startswith("feature.") and "quote" in check for check in checks_in(report))

    # argon2id → scrypt (lost); the logging paragraph gains a clause (behind); the session
    # sentence is reworded (drifted); the rotation paragraph is untouched (anchored).
    changed = (
        spec.replace("argon2id", "scrypt")
        .replace("operator's name.", "operator's name and address.")
        .replace(
            "Sessions expire after an hour of silence",
            "Sessions time out after sixty minutes of silence",
        )
    )
    cli("spec", "import", project, doc("s2.md", changed), "--name", "s")
    listed = {
        row["step"]["title"]: row["cites"][0]["anchoring"]
        for row in data(cli("feature", "list", project, "--json"))["features"]
        if row["cites"]
    }
    assert listed == {
        "Hashing": "lost",
        "Logging": "behind",
        "Sessions": "drifted",
        "Rotation": "anchored",
        "Quoteless": "anchored",
    }
    report = data(cli("project", "lint", project, "--json", expect=1))
    by_check = {
        row["check"]: row for row in report["findings"] if row["check"].startswith("feature.")
    }
    assert by_check["feature.quote-unanchored"]["title"].endswith("Hashing")
    assert by_check["feature.spec-changed"]["title"].endswith("Logging")
    assert by_check["feature.quote-drifted"]["title"].endswith("Sessions")
    assert "time out after sixty minutes" in by_check["feature.quote-drifted"]["message"]
    assert "now reads:" in cli("feature", "show", "Sessions")

    # A dry run says what would happen and writes nothing.
    dry = data(cli("feature", "reanchor", project, "--all", "--dry-run", "--json"))
    assert dry["dry_run"]
    assert {row["key"]: row["action"] for row in dry["passages"]} == {
        "F1": "kept",
        "F2": "stamped",
        "F3": "kept",
        "F4": "stamped",
        "F5": "stamped",
    }
    assert data(cli("feature", "show", "Logging", "--json"))["cites"][0]["anchoring"] == "behind"

    out = cli("feature", "reanchor", project, "--all", "--accept-drift")
    assert "1 lost" in out and "--drop-lost" in out
    listed = {
        row["step"]["title"]: row["cites"][0]["anchoring"]
        for row in data(cli("feature", "list", project, "--json"))["features"]
        if row["cites"]
    }
    assert listed == {
        "Hashing": "lost",
        "Logging": "anchored",
        "Sessions": "anchored",
        "Rotation": "anchored",
        "Quoteless": "anchored",
    }
    assert data(cli("feature", "show", "Sessions", "--json"))["cites"][0]["quote"] == (
        "Sessions time out after sixty minutes of silence."
    )
    cli("feature", "reanchor", project, "Hashing", "--drop-lost")
    assert data(cli("feature", "show", "Hashing", "--json"))["cites"] == []
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert not any(
        "quote" in check or check == "feature.spec-changed" for check in checks_in(report)
    )

    # A removed document cannot refute a quote: the passage stays, unchecked.
    cli("spec", "remove", project, "s")
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.quote-unanchored" not in checks_in(report)
    assert data(cli("feature", "show", "Logging", "--json"))["cites"][0]["anchoring"] == "missing"


def test_the_placement_checks_are_gone(cli, project, workspace):
    """Four of the five checks named a half-state a feature can no longer be in."""
    cli("step", "add", project, "Search", "--feature")
    cli("step", "add", project, "Also", "--feature")
    report = data(cli("project", "lint", project, "--json", expect=1))
    retired = {"feature.unplaced", "feature.duplicate", "feature.dangling", "feature.unregistered"}
    assert not retired & set(checks_in(report))


def test_export_and_import_carry_the_features_and_the_topology(cli, cli_stdin, project, tmp_path):
    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.")
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here."))
    cli("step", "add", project, "Bulk import", "--feature", "--document", "s", "--quote", "rule is")
    exported = cli("project", "export", project)
    cli_stdin("project", "import", "--title", "Copy", stdin=exported)
    listed = data(cli("feature", "list", "Copy", "--json"))["features"]
    assert [(row["step"]["title"], len(row["cites"])) for row in listed] == [("Bulk import", 1)]
    assert data(cli("topology", "show", "Copy", "--json"))["topology"] == "Views are features."
