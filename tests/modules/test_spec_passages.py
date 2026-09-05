"""The Specs tab and the passages features cite: the wash, the strip, the two jumps, and
the PDF viewer's boxes — the tab's side of the coverage seam."""

import pytest
from tests.cli.spec_helpers import tiny_pdf
from tests.modules.test_spec import imported

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.catalogue import FeatureRecord, FeatureSource, write_catalogue
from dplanner.modules.spec.activity import SpecsActivity
from dplanner.modules.spec.aspect import MODULE_ID

GUIDE = """# Guide

The first paragraph says little.

Operators MUST be able to import a CSV of readings.

The third paragraph is filler.

Every login is logged with the operator's name.
"""


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    imported(services, project, "guide", GUIDE.encode(), "guide.md")
    records = [
        FeatureRecord("f1", "Import", sources=(FeatureSource("guide", "import a CSV"),)),
        FeatureRecord("f2", "Logging", sources=(FeatureSource("guide", "Every login is logged"),)),
    ]
    SetModuleDataCommand(project.id, FEATURE_ID, write_catalogue(records)).redo(services.document)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("specs", project.id)


def washed(tab):
    return [sel.cursor.selectedText() for sel in tab._editor.extraSelections()]


def test_show_passages_washes_the_quotes_and_lands_on_the_focus(tab):
    tab.show_passages(
        "guide", ["import a CSV", "Every login is logged"], focus="Every login is logged"
    )
    assert washed(tab) == ["import a CSV", "Every login is logged"]
    plain = tab._editor.document().toPlainText()
    assert tab._editor.textCursor().position() == plain.index("Every login")
    assert tab.lit_passages() == ("import a CSV", "Every login is logged")
    assert tab.lit_note.text() == "2 passages lit" and not tab.clear_button.isHidden()
    tab.clear_passages()
    assert washed(tab) == [] and tab.lit_note.text() == "" and tab.clear_button.isHidden()


def test_a_quote_the_document_no_longer_holds_washes_nothing(tab):
    tab.show_passages("guide", ["vanished sentence"])
    assert washed(tab) == [] and tab.lit_passages() == ("vanished sentence",)


def test_the_cited_toggle_washes_every_passage_a_feature_cites(tab):
    assert not tab.cited.isChecked()
    tab.cited.click()
    assert sorted(washed(tab)) == ["Every login is logged", "import a CSV"]
    tab.cited.click()
    assert washed(tab) == []


def test_the_strip_is_off_screen_on_the_topology_row(tab):
    assert not tab._strip.isHidden()
    tab.list.setCurrentRow(0)
    assert tab._strip.isHidden()
    tab.select_document("guide")
    assert not tab._strip.isHidden()


def test_a_jump_from_the_coverage_view_drops_the_wash_when_another_document_is_picked(
    services, project, tab
):
    imported(services, project, "other", b"# Other\n\nNothing cited here.\n", "other.md")
    tab.show_passages("guide", ["import a CSV"])
    tab.select_document("other")
    assert tab.lit_passages() == ()


@pytest.fixture
def bare(services, project):
    """The activity built by hand, with recorders where the composition root wires the
    coverage view and the cite menu in."""
    jumps: list[tuple[str, str, str]] = []
    cites: list[tuple[str, str, str, int | None]] = []
    activity = SpecsActivity(
        services.document,
        services.context,
        services.actions,
        lambda node_id: services.repo.files(node_id, MODULE_ID),
        services.theme,
        services.undo,
        project.id,
        passages_of=lambda _pid, _doc: ["import a CSV"],
        open_coverage=lambda pid, doc, quote: jumps.append((pid, doc, quote)),
        cite=lambda pid, doc, quote, page: cites.append((pid, doc, quote, page)),
    )
    yield activity, jumps, cites
    activity.close()
    activity.widget.deleteLater()


def test_the_caret_inside_a_cited_passage_offers_the_coverage_view(project, bare):
    activity, jumps, _cites = bare
    activity.select_document("guide")
    editor = activity._editor
    assert not activity.to_coverage.isHidden() and not activity.to_coverage.isEnabled()
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().toPlainText().index("a CSV"))
    editor.setTextCursor(cursor)
    assert activity.to_coverage.isEnabled()
    activity.to_coverage.click()
    assert jumps == [(project.id, "guide", "import a CSV")]


def test_a_selection_can_be_cited(project, bare):
    activity, _jumps, cites = bare
    activity.select_document("guide")
    editor = activity._editor
    assert not activity.cite_button.isEnabled()
    plain = editor.document().toPlainText()
    cursor = editor.textCursor()
    cursor.setPosition(plain.index("The third"))
    cursor.setPosition(plain.index("filler.") + 7, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    assert activity.cite_button.isEnabled()
    activity.cite_button.click()
    assert cites == [(project.id, "guide", "The third paragraph is filler.", None)]


def test_a_pdf_marks_the_quotes_boxes_and_lands_on_their_page(services, make_project):
    project = make_project("Papers")
    imported(services, project, "s", tiny_pdf("First page.", "The rule is here."), "s.pdf")
    tab = services.tabs.open("specs", project.id)
    tab.show_passages("s", ["rule is here"], focus="rule is here")
    first, second = tab._pdf._pages
    assert first._boxes == [] and len(second._boxes) >= 1
    assert all(is_focus for _box, is_focus in second._boxes)
    tab.clear_passages()
    assert second._boxes == []


def test_the_build_wires_the_catalogue_and_the_cite_menu_in(services, project, tab):
    """The composition root hands the Specs tab the feature side: the Cited wash reads the
    catalogue, and Cite… is offered (the coverage jump arrives with the coverage module)."""
    tab.cited.click()
    assert len(washed(tab)) == 2
    assert not tab.cite_button.isHidden()
