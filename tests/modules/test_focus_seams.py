"""A jump lands on the thing it named: the details dialog on a test or a feature, the
Docs tab on a step's group — the seams the coverage view's double-click rides."""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Step, TextEdit
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.docs.aspect import MODULE_ID as DOCS_ID
from dplanner.modules.docs.aspect import write_state
from dplanner.modules.docs.module import NO_DOCS_REASON, OPEN_STEP_ACTION
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.catalogue import FeatureRecord, read_catalogue, write_catalogue
from dplanner.modules.feature.module import FeatureModule
from dplanner.modules.step_properties.dialog import StepDetailsDialog
from dplanner.modules.testing.aspect import MODULE_ID as TESTING_ID
from dplanner.modules.testing.aspect import Test, write


@pytest.fixture
def project(services, make_project):
    """work → Import (feature f1); work carries two tests and a docs note."""
    project = make_project("Discovery")
    work, imp = Step(title="work"), Step(title="Import")
    for step in (work, imp):
        AddNodeCommand(project.id, step).redo(services.document)
    SetEdgesCommand(imp.id, "requires", [work.id]).redo(services.document)
    library = services.document
    tests = write([Test("T100", "one"), Test("T101", "two")])
    library.set_module_data(work.id, TESTING_ID, tests)
    library.set_module_data(
        project.id, FEATURE_ID, write_catalogue([FeatureRecord("f1", "Import")])
    )
    library.set_module_data(imp.id, FEATURE_ID, {"feature": "f1", "format": 2})
    library.set_module_data(work.id, DOCS_ID, write_state(True))
    library.apply_text_edit(TextEdit(work.id, DOCS_ID, 0, "", "What work adds."))
    return project


def selection(*nodes: tuple[str, str]) -> Context:
    return Context(
        {SCOPE_SELECTION: tuple(ContextNode(selection_uri(kind, key)) for kind, key in nodes)}
    )


def test_the_details_dialog_lands_on_a_named_test(services, project, monkeypatch):
    work, _imp = project.steps
    seen: list[tuple[str, str]] = []

    def fake_exec(dialog: StepDetailsDialog) -> int:
        panel = dialog.panel
        section = panel._extensions[panel.tab_bar.currentIndex()]
        picked = getattr(section, "_selected", "")
        seen.append((panel.tab_bar.tabText(panel.tab_bar.currentIndex()), picked))
        return 0

    monkeypatch.setattr(StepDetailsDialog, "exec", fake_exec)
    services.actions.run("steps.details", selection(("step", work.id), ("test", "T101")))
    assert seen == [("Tests", "T101")]


def test_the_details_dialog_lands_on_the_feature_tab(services, project, monkeypatch):
    _work, imp = project.steps
    seen: list[str] = []

    def fake_exec(dialog: StepDetailsDialog) -> int:
        panel = dialog.panel
        seen.append(panel.tab_bar.tabText(panel.tab_bar.currentIndex()))
        return 0

    monkeypatch.setattr(StepDetailsDialog, "exec", fake_exec)
    services.actions.run("steps.details", selection(("step", imp.id), ("feature", "f1")))
    assert seen == ["Feature"]
    # A thing the step does not hold is nobody's: the dialog opens as it always does.
    services.actions.run("steps.details", selection(("step", imp.id), ("test", "T999")))
    assert seen[-1] != "Tests"


def test_show_docs_opens_the_docs_tab_on_the_steps_group(services, project):
    work, imp = project.steps
    spec = services.actions.spec(OPEN_STEP_ACTION)
    assert spec.state(selection(("step", imp.id))).enabled  # A feature gathering a note.
    assert spec.state(selection(("step", work.id))).enabled  # The note itself.
    plain = Step(title="plain")
    AddNodeCommand(project.id, plain).redo(services.document)
    greyed = spec.state(selection(("step", plain.id)))
    assert greyed.enabled is False and greyed.label == NO_DOCS_REASON

    services.actions.run(OPEN_STEP_ACTION, selection(("step", work.id)))
    [tab] = [a for a in services.tabs.activities() if a.title.endswith("Docs")]
    assert tab._selected == imp.id  # The note is read under the feature that gathers it.
    services.actions.run(OPEN_STEP_ACTION, selection(("step", imp.id)))
    assert tab._selected == imp.id


def test_the_cite_menu_appends_a_stamped_passage(services, project):
    module = next(m for m in services.modules if isinstance(m, FeatureModule))
    menu = module.cite_menu(project.id, "spec", "Operators MUST import", 3)
    assert [a.text() for a in menu.actions() if a.text()] == ["f1  Import", "New feature…"]
    menu.actions()[0].trigger()
    [record] = read_catalogue(project)
    [source] = record.sources
    assert (source.document, source.quote, source.page) == ("spec", "Operators MUST import", 3)
    assert services.undo.undo_text() == "Cite Passage"
    # The same passage again, spaced and cased differently, is not a second.
    module.cite_menu(project.id, "spec", "operators must IMPORT", 3).actions()[0].trigger()
    assert len(read_catalogue(project)[0].sources) == 1


def test_the_cite_menu_can_mint_a_feature(services, project, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    module = next(m for m in services.modules if isinstance(m, FeatureModule))
    monkeypatch.setattr(QInputDialog, "getText", lambda *_a, **_k: ("Export", True))
    module.cite_menu(project.id, "spec", "MAY export", None).actions()[-1].trigger()
    records = read_catalogue(project)
    assert [(r.id, r.title) for r in records] == [("f1", "Import"), ("f2", "Export")]
    assert records[1].sources[0].quote == "MAY export"
