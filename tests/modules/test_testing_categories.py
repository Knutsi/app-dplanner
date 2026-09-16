"""The category catalogue and the export, Qt-free.

The window's half — the grouping, the folding, the editor — is in ``test_testing.py``, and
the verbs are in ``test_testing.py``'s CLI half. What is here is the record shapes and the
two documents, which are the pieces every surface reads.
"""

import pytest

from dplanner.cli.command import CliError
from dplanner.domain.model import Project, Step
from dplanner.modules.testing import categories, export, runs
from dplanner.modules.testing.aspect import MODULE_ID, Test, write
from dplanner.theme.icons import GLYPH_DIR


def project_with(*steps, catalog=()):
    project = Project(title="Widget")
    for step in steps:
        project.steps.append(step)
    if catalog:
        project.module_data[MODULE_ID] = categories.write_catalog(project, catalog)
    return project


def step_with(title, *tests):
    step = Step(title=title)
    step.module_data[MODULE_ID] = write(tests)
    return step


# -- the record ---------------------------------------------------------------------------


def test_every_offered_icon_is_a_glyph_this_build_has():
    """The tuple is curated by hand and lives Qt-free, so nothing else would notice a typo."""
    missing = [name for name in categories.ICONS if not GLYPH_DIR.joinpath(f"{name}.svg").is_file()]
    assert missing == []


def test_a_category_round_trips_with_its_icon():
    project = project_with(catalog=[categories.Category("Import", "layers")])
    assert categories.read_catalog(project) == [categories.Category("Import", "layers")]


def test_an_icon_this_build_does_not_know_reads_as_none():
    project = Project(title="Widget")
    project.module_data[MODULE_ID] = {"categories": [{"name": "Import", "icon": "spaceship"}]}
    assert categories.read_catalog(project) == [categories.Category("Import")]


def test_an_empty_catalogue_leaves_no_key_and_keeps_the_runs():
    project = Project(title="Widget")
    project.module_data[MODULE_ID] = runs.write(project, [runs.Run(id="R100", label="P3")])
    entry = categories.write_catalog(project, [])
    assert "categories" not in entry
    kept = Project(title="W")
    kept.module_data[MODULE_ID] = entry
    assert [run.id for run in runs.read(kept)] == ["R100"]


def test_the_runs_and_the_categories_share_one_entry_without_losing_each_other():
    """One module id, two shapes: neither writer may compose the entry from its own half."""
    project = Project(title="Widget")
    project.module_data[MODULE_ID] = categories.write_catalog(
        project, [categories.Category("Import")]
    )
    project.module_data[MODULE_ID] = runs.write(project, [runs.Run(id="R100")])

    assert [c.name for c in categories.read_catalog(project)] == ["Import"]
    assert [run.id for run in runs.read(project)] == ["R100"]


def test_a_key_that_is_not_the_projects_is_refused_rather_than_written():
    with pytest.raises(ValueError, match="not a project-level testing key"):
        from dplanner.modules.testing.aspect import project_entry

        project_entry(Project(title="Widget"), tests=[])


# -- what a project has -------------------------------------------------------------------


def test_a_category_only_a_test_names_is_still_a_category_and_sorts_last():
    project = project_with(
        step_with("Login", Test("T100", "One", category="Zebra"), Test("T101", "Two")),
        catalog=[categories.Category("Import", "layers")],
    )
    assert [c.name for c in categories.catalog(project)] == ["Import", "Zebra"]
    # Unglyphed: nobody wrote it down, so nobody picked a picture for it either.
    assert categories.catalog(project)[1].icon == ""


def test_counts_are_derived_and_name_every_catalogued_group_even_at_nought():
    project = project_with(
        step_with("Login", Test("T100", "One", category="Import"), Test("T101", "Two")),
        catalog=[categories.Category("Import"), categories.Category("Smoke")],
    )
    assert categories.counts(project) == {"Import": 1, "Smoke": 0, "Uncategorised": 1}


def test_an_archived_test_keeps_its_category_alive_but_is_out_of_the_roster_count():
    project = project_with(
        step_with("Login", Test("T100", "One", archived=True, category="Smoke")),
    )
    assert [c.name for c in categories.catalog(project)] == ["Smoke"]
    assert categories.counts(project)["Smoke"] == 0
    assert categories.counts(project, archived=True)["Smoke"] == 1


def test_a_test_that_names_nothing_reads_as_uncategorised():
    assert categories.category_of(Test("T100", "One")) == categories.UNCATEGORISED
    assert categories.category_of(Test("T100", "One", category="Smoke")) == "Smoke"


# -- refusals -----------------------------------------------------------------------------


def test_an_unknown_icon_is_refused_naming_the_whole_set():
    with pytest.raises(CliError) as raised:
        categories.check_icon("spaceship")
    assert "beaker" in str(raised.value) and "shield" in str(raised.value)
    assert categories.check_icon("") == ""  # No icon is a fine answer.


def test_a_category_cannot_be_blank_or_be_called_uncategorised():
    with pytest.raises(CliError, match="needs a name"):
        categories.check_name("  ")
    with pytest.raises(CliError, match="reads as"):
        categories.check_name("uncategorised")
    assert categories.check_name("  Import ") == "Import"


# -- the refactor -------------------------------------------------------------------------


def test_renaming_moves_every_test_carrying_the_old_words_whatever_their_case():
    tests = [
        Test("T100", "One", category="Import"),
        Test("T101", "Two", category="import"),
        Test("T102", "Three", category="Smoke"),
    ]
    moved = categories.renamed(tests, "Import", "Import and export")
    assert [test.category for test in moved] == ["Import and export", "Import and export", "Smoke"]


def test_rewrite_names_only_the_steps_a_change_actually_touches():
    project = project_with(
        step_with("Login", Test("T100", "One", category="Import")),
        step_with("Export", Test("T101", "Two", category="Smoke")),
        step_with("Quiet", Test("T102", "Three")),
    )
    touched = categories.rewrite(project, lambda tests: categories.renamed(tests, "Import", "In"))
    assert [project.steps[0].id] == list(touched)


def test_refiling_takes_the_named_tests_and_leaves_the_rest():
    tests = [Test("T100", "One"), Test("T101", "Two", category="Smoke")]
    assert [t.category for t in categories.refiled(tests, ["T100"], "Import")] == [
        "Import",
        "Smoke",
    ]


# -- the export ---------------------------------------------------------------------------


def exported(**changed):
    project = project_with(
        step_with(
            "Login",
            Test("T100", "Signs in", body="1. Open it.\n2. It must work.", category="Smoke"),
            Test("T101", "Signs out", audiences=("qa",)),
        ),
        catalog=[categories.Category("Smoke", "spark")],
    )
    return export.Exported(
        project=project,
        pairs=[(step, test) for step in project.steps for test in [*_tests(step)]],
        outcomes={},
        **changed,
    )


def _tests(step):
    from dplanner.modules.testing.aspect import read

    return read(step)


def test_markdown_files_the_tests_under_their_categories_bodies_and_all():
    text = export.render(exported(), "md")
    assert "# Widget — Tests" in text
    assert text.index("## Smoke") < text.index("## Uncategorised")
    assert "### T100 — Signs in" in text
    assert "2. It must work." in text
    assert "Result: not run" in text


def test_the_document_says_what_it_was_narrowed_to():
    text = export.render(exported(audiences=["QA"], scope="Pre-release check"), "md")
    assert "Scope: Pre-release check" in text
    assert "Audience: QA" in text
    assert "2 tests" in text
    assert "Audience: all" in export.render(exported(), "md")


def test_html_makes_every_test_a_details_that_opens_on_its_body():
    page = export.render(exported(), "html")
    assert page.startswith("<!doctype html>")
    assert page.count("<details>") == 2
    assert "<h2>Smoke" in page
    assert "It must work." in page


def test_html_escapes_what_a_person_typed():
    project = project_with(step_with("Login", Test("T100", "<script>alert(1)</script>")))
    page = export.render(
        export.Exported(
            project=project, pairs=[(project.steps[0], _tests(project.steps[0])[0])], outcomes={}
        ),
        "html",
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_an_empty_list_says_so_rather_than_printing_a_headline_over_nothing():
    project = Project(title="Widget")
    empty = export.Exported(project=project, pairs=[], outcomes={})
    assert export.NOTHING in export.render(empty, "md")
    assert export.NOTHING in export.render(empty, "html")
