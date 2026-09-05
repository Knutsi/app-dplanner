"""``dplanner feature``: the catalogue, its instances on the graph, and lint — over a real
library. No ``qapp`` fixture: this is an agent's workflow.
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


# -- the catalogue -----------------------------------------------------------------------------


def test_add_mints_ids_and_list_says_what_is_placed(cli, project, workspace):
    cli("feature", "add", project, "Bulk import")
    cli("feature", "add", project, "Dark mode")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [(row["feature"], row["title"], row["step"]) for row in listed] == [
        ("f1", "Bulk import", None),
        ("f2", "Dark mode", None),
    ]
    entry = json.loads(next(workspace.glob("*/modules/feature.json")).read_text())
    assert entry["format"] == 2 and [row["id"] for row in entry["features"]] == ["f1", "f2"]
    text = cli("feature", "list", project)
    assert "f1   Bulk import  — not placed" in text


def test_a_removed_id_is_not_minted_again_while_a_higher_one_exists(cli, project):
    cli("feature", "add", project, "One")
    cli("feature", "add", project, "Two")
    cli("feature", "remove", project, "f1")
    cli("feature", "add", project, "Three")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [row["feature"] for row in listed] == ["f2", "f3"]


def test_add_with_a_taken_id_is_refused(cli, project):
    cli("feature", "add", project, "One", "--id", "f7")
    out = cli("feature", "add", project, "Again", "--id", "f7", expect=1)
    assert "feature edit" in out


def test_a_feature_is_found_by_id_or_a_unique_part_of_its_title(cli, project):
    cli("feature", "add", project, "Bulk import")
    cli("feature", "add", project, "Bulk export")
    assert data(cli("feature", "show", project, "f2", "--json"))["title"] == "Bulk export"
    assert data(cli("feature", "show", project, "export", "--json"))["feature"] == "f2"
    out = cli("feature", "show", project, "Bulk", expect=1)
    assert "several features" in out and "f1" in out and "f2" in out
    assert "feature list" in cli("feature", "show", project, "ghost", expect=1)


def test_edit_changes_title_and_description(cli, cli_stdin, project):
    cli("feature", "add", project, "Bulk import")
    cli_stdin(
        "feature",
        "edit",
        project,
        "f1",
        "--title",
        "CSV import",
        "--describe-file",
        "-",
        stdin="Operators upload a CSV.",
    )
    shown = data(cli("feature", "show", project, "f1", "--json"))
    assert shown["title"] == "CSV import" and shown["description"] == "Operators upload a CSV."
    assert "Operators upload a CSV." in cli("feature", "show", project, "f1")


def test_remove_clears_the_instance(cli, project):
    cli("feature", "add", project, "Bulk import")
    cli("step", "add", project, "Bulk import", "--feature", "f1")
    report = data(cli("feature", "remove", project, "f1", "--json"))
    assert len(report["cleared"]) == 1
    assert "feature" not in data(cli("step", "show", "Bulk import", "--json"))["aspects"]
    assert data(cli("feature", "list", project, "--json"))["features"] == []


# -- the source: where in the spec it came from -------------------------------------------------


def test_add_finds_the_quote_and_records_its_page(cli, project, tmp_path):
    pdf = tiny_pdf("Nothing here.", "All credentials MUST be hashed.")
    cli("spec", "import", project, source(tmp_path, "s.pdf", pdf))
    report = data(
        cli(
            "feature",
            "add",
            project,
            "Hashing",
            "--document",
            "s",
            "--quote",
            "MUST be hashed",
            "--json",
        )
    )
    [passage] = report["sources"]
    assert (passage["document"], passage["quote"], passage["page"]) == ("s", "MUST be hashed", 2)
    assert passage["anchoring"] == "anchored" and len(passage["digest"]) == 16
    assert "s p.2" in cli("feature", "list", project)


def test_an_absent_quote_warns_but_still_adds(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing here.")))
    out = cli("feature", "add", project, "Ghost", "--document", "s", "--quote", "does not appear")
    assert "warning" in out and "not found" in out
    assert data(cli("feature", "list", project, "--json"))["features"]


def test_a_page_that_disagrees_with_the_quote_warns_but_is_kept(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing.", "The rule.")))
    out = cli(
        "feature", "add", project, "Rule", "--document", "s", "--quote", "The rule", "--page", "1"
    )
    assert "not found on page 1 — it anchors on 2" in out
    assert data(cli("feature", "show", project, "f1", "--json"))["sources"][0]["page"] == 1


def test_a_quote_on_several_pages_accepts_any_of_them_as_page(cli, project, tmp_path):
    # The same sentence on pages 1 and 2: --page is disambiguation, not a mismatch.
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("The rule.", "The rule.")))
    out = cli(
        "feature", "add", project, "Rule", "--document", "s", "--quote", "The rule", "--page", "2"
    )
    assert "warning" not in out
    assert data(cli("feature", "show", project, "f1", "--json"))["sources"][0]["page"] == 2
    # Unnamed, the first occurrence is recorded.
    cli("feature", "add", project, "Again", "--document", "s", "--quote", "The rule")
    assert data(cli("feature", "show", project, "f2", "--json"))["sources"][0]["page"] == 1


def test_strict_refuses_a_quote_that_does_not_anchor(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.pdf", tiny_pdf("Nothing here.")))
    out = cli(
        "feature",
        "add",
        project,
        "Ghost",
        "--document",
        "s",
        "--quote",
        "does not appear",
        "--strict",
        expect=1,
    )
    assert "--strict" in out
    assert data(cli("feature", "list", project, "--json"))["features"] == []
    # An anchoring quote passes strict; no quote at all passes too (nothing to refute).
    cli("feature", "add", project, "Real", "--document", "s", "--quote", "Nothing here", "--strict")
    cli("feature", "add", project, "Quoteless", "--document", "s", "--strict")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [row["title"] for row in listed] == ["Real", "Quoteless"]


def test_quotes_are_validated_against_prose_documents_too(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule\nis here."))
    report = data(
        cli(
            "feature",
            "add",
            project,
            "Rule",
            "--document",
            "s",
            "--quote",
            "rule is here",
            "--json",
        )
    )
    assert report["sources"][0]["page"] is None and "warning" not in report


def test_a_quote_needs_a_document(cli, project):
    out = cli("feature", "add", project, "Rule", "--quote", "orphan", expect=1)
    assert "--document" in out


def test_list_filters_by_document(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "# S"))
    cli("spec", "import", project, source(tmp_path, "t.md", "# T"))
    cli("feature", "add", project, "From S", "--document", "s")
    cli("feature", "add", project, "From T", "--document", "t")
    cli("feature", "add", project, "By hand")
    listed = data(cli("feature", "list", project, "--document", "t", "--json"))["features"]
    assert [row["title"] for row in listed] == ["From T"]


def test_cite_adds_passages_and_uncite_takes_them_away(cli, project, tmp_path):
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here.\n\nAnd there."))
    cli("feature", "add", project, "Rule", "--document", "s", "--quote", "rule is here")
    out = cli("feature", "cite", project, "f1", "--document", "s", "--quote", "And there")
    assert "cites 2 passages" in out
    # The same passage again, however it is spaced or cased, is not a third.
    assert "already cites" in cli(
        "feature", "cite", project, "f1", "--document", "s", "--quote", "and  THERE"
    )
    shown = data(cli("feature", "show", project, "f1", "--json"))
    assert [row["quote"] for row in shown["sources"]] == ["rule is here", "And there"]
    assert "s +1" in cli("feature", "list", project)
    assert "> And there" in cli("feature", "show", project, "f1")
    assert "1 passage removed" in cli(
        "feature", "uncite", project, "f1", "--document", "s", "--quote", "And there"
    )
    assert "nothing to remove" in cli(
        "feature", "uncite", project, "f1", "--document", "s", "--quote", "And there"
    )
    cli("feature", "uncite", project, "f1", "--all")
    assert data(cli("feature", "show", project, "f1", "--json"))["sources"] == []
    assert "--all" in cli("feature", "uncite", project, "f1", expect=1)


def test_a_migrated_catalogue_keeps_its_one_passage_unstamped(cli, project, workspace, tmp_path):
    """Format 1 stored one ``source`` per record; it becomes a one-element ``sources``
    with no digest, judged by its match alone — an old project opens into no warnings."""
    cli("spec", "import", project, source(tmp_path, "s.md", "The rule is here."))
    catalogue = next(workspace.glob("*/modules")) / "feature.json"
    catalogue.write_text(
        json.dumps(
            {
                "format": 1,
                "features": [
                    {
                        "id": "f1",
                        "title": "Rule",
                        "source": {"document": "s", "quote": "rule is here"},
                    },
                    {"id": "f2", "title": "By hand"},
                ],
            }
        )
    )
    shown = data(cli("feature", "show", project, "f1", "--json"))
    assert shown["sources"] == [
        {
            "document": "s",
            "quote": "rule is here",
            "page": None,
            "digest": "",
            "anchoring": "anchored",
        }
    ]
    assert data(cli("feature", "show", project, "f2", "--json"))["sources"] == []
    assert json.loads(catalogue.read_text())["format"] == 2
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert not any(check.startswith("feature.quote") for check in checks_in(report))
    assert "feature.spec-changed" not in checks_in(report)


# -- images ------------------------------------------------------------------------------------


def test_attach_and_add_image_land_in_the_projects_feature_area(cli, project, tmp_path, workspace):
    cli("feature", "add", project, "Bulk import")
    figure = tmp_path / "mock.png"
    figure.write_bytes(b"png bytes")
    report = data(cli("feature", "attach", project, "f1", str(figure), "--json"))
    assert report["asset"].startswith("assets/") and report["path"].endswith(".png")
    copies = list(workspace.glob("*/modules/feature/assets/*.png"))
    assert len(copies) == 1
    shown = data(cli("feature", "show", project, "f1", "--json"))
    assert shown["images"] == [report["path"]]
    # The same bytes twice is one file and one entry.
    cli("feature", "attach", project, "f1", str(figure))
    assert len(data(cli("feature", "show", project, "f1", "--json"))["images"]) == 1

    other = tmp_path / "other.png"
    other.write_bytes(b"other png")
    cli("feature", "add", project, "Dark mode", "--image", str(other))
    assert len(data(cli("feature", "show", project, "f2", "--json"))["images"]) == 1


def test_a_features_image_is_used_while_its_record_names_it(cli, project, tmp_path):
    cli("feature", "add", project, "Bulk import")
    figure = tmp_path / "mock.png"
    figure.write_bytes(b"png bytes")
    cli("feature", "attach", project, "f1", str(figure))
    listed = data(cli("asset", "list", project, "--json"))["assets"]
    mine = [row for row in listed if any(c["module"] == "feature" for c in row["locations"])]
    assert len(mine) == 1
    uses = [use for copy in mine[0]["locations"] for use in copy["uses"]]
    assert any("feature f1" in use["where"] for use in uses)


# -- instances on the graph --------------------------------------------------------------------


def test_step_add_with_a_feature_is_born_placed(cli, project):
    cli("feature", "add", project, "Bulk import")
    cli("step", "add", project, "Build the importer")
    out = cli(
        "step", "add", project, "Bulk import", "--feature", "f1", "--after", "Build the importer"
    )
    assert "feature f1 (Bulk import)" in out
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert listed[0]["step"]["title"] == "Bulk import"
    assert "placed: 'Bulk import'" in cli("feature", "list", project)


def test_a_bare_feature_flag_catalogues_the_step_as_a_new_feature(cli, project):
    cli("step", "add", project, "Search", "--feature")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [(row["feature"], row["title"], row["step"]["title"]) for row in listed] == [
        ("f1", "Search", "Search")
    ]


def test_set_refuses_a_second_instance(cli, project):
    cli("feature", "add", project, "Bulk import")
    cli("step", "add", project, "One", "--feature", "f1")
    cli("step", "add", project, "Two")
    out = cli("feature", "set", "Two", "--feature", "f1", expect=1)
    assert "already realised by 'One'" in out and "feature clear 'One'" in out
    cli("step", "add", project, "Three", "--feature", "f1", expect=1)
    assert data(cli("step", "list", project, "--json"))["steps"][-1]["title"] == "Two"


def test_set_without_an_id_mints_and_is_idempotent(cli, project):
    cli("step", "add", project, "Search")
    assert "realises f1 (Search)" in cli("feature", "set", "Search")
    assert "already realises f1" in cli("feature", "set", "Search")
    assert "already realises f1" in cli("feature", "set", "Search", "--feature", "f1")


def test_clear_keeps_the_record_and_is_idempotent(cli, project):
    cli("step", "add", project, "Search", "--feature")
    assert "stays in the catalogue" in cli("feature", "clear", "Search")
    assert "not a feature" in cli("feature", "clear", "Search")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert listed[0]["step"] is None
    # …and the record can be placed again, on another step.
    cli("step", "add", project, "Search v2", "--feature", "f1")
    assert data(cli("feature", "list", project, "--json"))["features"][0]["step"]["title"] == (
        "Search v2"
    )


def test_removing_the_instance_step_leaves_the_record_unplaced(cli, project):
    cli("step", "add", project, "Search", "--feature")
    cli("step", "remove", "Search")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [(row["feature"], row["step"]) for row in listed] == [("f1", None)]


def test_a_retired_marker_reads_as_an_unregistered_feature(cli, project, workspace):
    """``step_feature`` wrote ``{"on": true}``; the takeover keeps it as a feature step
    naming no record, listed as such until ``feature set`` registers it."""
    cli("step", "add", project, "Search")
    modules = next(workspace.glob("*/steps/search")) / "modules"
    modules.mkdir(exist_ok=True)
    (modules / "step_feature.json").write_text(json.dumps({"on": True}))
    out = cli("feature", "list", project)
    assert "Search  — feature step with no record" in out
    assert not (modules / "step_feature.json").exists()
    assert json.loads((modules / "feature.json").read_text())["on"] is True
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.unregistered" in checks_in(report)
    assert data(cli("scope", "show", "Search", "--json"))["kind"] == "feature"
    cli("feature", "set", "Search")
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert [(row["feature"], row["title"]) for row in listed] == [("f1", "Search")]
    assert json.loads((modules / "feature.json").read_text())["feature"] == "f1"


def test_duplicating_a_feature_step_makes_a_plain_copy(cli, project):
    cli("step", "add", project, "Search", "--feature")
    cli("step", "duplicate", "Search")
    steps = data(cli("step", "list", project, "--json"))["steps"]
    assert len(steps) == 2
    listed = data(cli("feature", "list", project, "--json"))["features"]
    assert listed[0]["step"]["title"] == "Search"
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.duplicate" not in checks_in(report)


# -- lint --------------------------------------------------------------------------------------


def test_lint_tracks_the_placement_lifecycle(cli, project, workspace):
    cli("feature", "add", project, "Bulk import")
    report = data(cli("project", "lint", project, "--json", expect=1))
    flagged = [row for row in report["findings"] if row["check"] == "feature.unplaced"]
    assert len(flagged) == 1 and "--feature f1" in flagged[0]["message"]

    cli("step", "add", project, "Bulk import", "--feature", "f1")
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.unplaced" not in checks_in(report)

    # A second instance can only arrive by hand; lint names it.
    cli("step", "add", project, "Again")
    modules = next(workspace.glob("*/steps/again")) / "modules"
    modules.mkdir(exist_ok=True)
    (modules / "feature.json").write_text(json.dumps({"feature": "f1", "format": 1}))
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.duplicate" in checks_in(report)

    (modules / "feature.json").write_text(json.dumps({"feature": "f9", "format": 1}))
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.dangling" in checks_in(report)


def test_a_replaced_document_grades_every_passage_and_reanchor_catches_up(cli, project, tmp_path):
    def doc(name, text):
        return source(tmp_path, name, text)

    spec = (
        "# Auth\n\nThe rule is argon2id, and every hash MUST be salted.\n\n"
        "Logins are logged with the operator's name.\n\n"
        "Sessions expire after an hour of silence.\n\nPasswords rotate every ninety days.\n"
    )
    cli("spec", "import", project, doc("s.md", spec), "--name", "s")
    cli("feature", "add", project, "Hashing", "--document", "s", "--quote", "argon2id")
    cli("feature", "add", project, "Logging", "--document", "s", "--quote", "Logins are logged")
    cli(
        "feature",
        "add",
        project,
        "Sessions",
        "--document",
        "s",
        "--quote",
        "Sessions expire after an hour of silence",
    )
    cli(
        "feature",
        "add",
        project,
        "Rotation",
        "--document",
        "s",
        "--quote",
        "rotate every ninety days",
    )
    cli("feature", "add", project, "Quoteless", "--document", "s")
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
        row["feature"]: row["sources"][0]["anchoring"]
        for row in data(cli("feature", "list", project, "--json"))["features"]
    }
    assert listed == {
        "f1": "lost",
        "f2": "behind",
        "f3": "drifted",
        "f4": "anchored",
        "f5": "anchored",
    }
    report = data(cli("project", "lint", project, "--json", expect=1))
    by_check = {
        row["check"]: row for row in report["findings"] if row["check"].startswith("feature.")
    }
    assert by_check["feature.quote-unanchored"]["subject"] == "f1"
    assert by_check["feature.spec-changed"]["subject"] == "f2"
    assert by_check["feature.quote-drifted"]["subject"] == "f3"
    assert "time out after sixty minutes" in by_check["feature.quote-drifted"]["message"]
    assert "now reads:" in cli("feature", "show", project, "f3")

    # A dry run says what would happen and writes nothing.
    dry = data(cli("feature", "reanchor", project, "--all", "--dry-run", "--json"))
    assert dry["dry_run"] and {row["feature"]: row["action"] for row in dry["passages"]} == {
        "f1": "kept",
        "f2": "stamped",
        "f3": "kept",
        "f4": "stamped",
        "f5": "stamped",
    }
    assert (
        data(cli("feature", "show", project, "f2", "--json"))["sources"][0]["anchoring"] == "behind"
    )

    out = cli("feature", "reanchor", project, "--all", "--accept-drift")
    assert "1 lost" in out and "--drop-lost" in out
    listed = {
        row["feature"]: row["sources"][0]["anchoring"]
        for row in data(cli("feature", "list", project, "--json"))["features"]
    }
    assert listed == {
        "f1": "lost",
        "f2": "anchored",
        "f3": "anchored",
        "f4": "anchored",
        "f5": "anchored",
    }
    assert data(cli("feature", "show", project, "f3", "--json"))["sources"][0]["quote"] == (
        "Sessions time out after sixty minutes of silence."
    )
    cli("feature", "reanchor", project, "f1", "--drop-lost")
    assert data(cli("feature", "show", project, "f1", "--json"))["sources"] == []
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert not any(
        "quote" in check or check == "feature.spec-changed" for check in checks_in(report)
    )

    # A removed document cannot refute a quote: the source stays, unchecked.
    cli("spec", "remove", project, "s")
    report = data(cli("project", "lint", project, "--json", expect=1))
    assert "feature.quote-unanchored" not in checks_in(report)
    assert (
        data(cli("feature", "show", project, "f2", "--json"))["sources"][0]["anchoring"]
        == "missing"
    )


def test_export_and_import_carry_the_catalogue_and_the_topology(cli, cli_stdin, project):
    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.")
    cli("feature", "add", project, "Bulk import")
    cli("step", "add", project, "Bulk import", "--feature", "f1")
    exported = cli("project", "export", project)
    cli_stdin("project", "import", "--title", "Copy", stdin=exported)
    listed = data(cli("feature", "list", "Copy", "--json"))["features"]
    assert [(row["feature"], row["step"]["title"]) for row in listed] == [("f1", "Bulk import")]
    assert data(cli("topology", "show", "Copy", "--json"))["topology"] == "Views are features."
