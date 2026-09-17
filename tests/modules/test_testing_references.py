"""A test body that points at another test, and the preview a reader follows it into.

The Qt-free half — what counts as a reference and what the linking does to rendered HTML —
is asserted straight against ``references.py``; the rest is the Test panel, the preview
modal and where *Show in Tests* lands.
"""

import pytest

from dplanner.core.markdown import render as markdown
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.testing.aspect import MODULE_ID, Test, write
from dplanner.modules.testing.references import (
    LINK_SCHEME,
    link_tests,
    linked_test,
    mentions,
)

# -- what a reference is ------------------------------------------------------------------


def test_a_reference_is_a_bare_id_the_project_actually_has():
    html = markdown("Run after T100, unlike T999 and XT100 and T100a.")
    linked = link_tests(html, ["T100", "T101"])
    assert f'<a href="{LINK_SCHEME}:T100">T100</a>' in linked
    # An id nobody minted stays words: a dead link is a worse answer than no link.
    assert "T999</a>" not in linked
    # And these are words of their own, not references with something stuck to them.
    assert "XT100</a>" not in linked and "T100a</a>" not in linked


def test_an_id_in_code_or_in_a_link_is_left_alone():
    """Code quotes the shape of an id; a link already points somewhere."""
    body = "See `T100` and [T100](https://example.com/T100) but also T100."
    linked = link_tests(markdown(body), ["T100"])
    assert linked.count(f'href="{LINK_SCHEME}:T100"') == 1
    assert "<code>T100</code>" in linked
    assert '<a href="https://example.com/T100"' in linked


def test_nothing_is_linked_when_the_project_has_minted_nothing():
    html = markdown("Run after T100.")
    assert link_tests(html, []) == html


def test_the_cheap_question_is_asked_before_the_expensive_one():
    """`mentions` is what keeps a walk of the project off every body that needs none."""
    assert mentions("Run after T100.") and not mentions("Run it twice.")


def test_a_link_says_which_test_it_names_and_an_ordinary_one_says_nothing():
    assert linked_test(f"{LINK_SCHEME}:T100") == "T100"
    assert linked_test("https://example.com/T100") == ""
    assert linked_test(f"{LINK_SCHEME}:nonsense") == ""


# -- the panel and the preview -------------------------------------------------------------


@pytest.fixture
def widget(services, make_project):
    """A project whose T100 points at T101, on two steps."""
    project = make_project("Widget")
    first, second = Step(title="Fix list flicker"), Step(title="Rotate")
    for step in (first, second):
        AddNodeCommand(project.id, step).redo(services.document)
    services.document.set_module_data(
        first.id, MODULE_ID, write([Test("T100", "Signs in", body="Run this after T101 passes.")])
    )
    services.document.set_module_data(
        second.id, MODULE_ID, write([Test("T101", "Rotates", body="Turn it.")])
    )
    return project, first, second


def pick(services, step, test_id):
    """A test picked the way every view picks one: with the step it hangs off."""
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION,
        (
            ContextNode(selection_uri("step", step.id)),
            ContextNode(selection_uri("test", test_id)),
        ),
    )


def panel_showing(services, step, test_id):
    from dplanner.modules.testing.panel import PANEL_ID

    panel = services.window.dock.widget_for(PANEL_ID)
    pick(services, step, test_id)
    panel.show_context(services.context.current())
    return panel


def test_the_panel_links_a_reference_in_the_body_it_renders(services, widget):
    _project, first, _second = widget
    panel = panel_showing(services, first, "T100")
    assert f'href="{LINK_SCHEME}:T101"' in panel.body.toHtml()


def test_a_reference_opens_the_preview_and_show_in_tests_picks_that_test(
    services, widget, monkeypatch
):
    from dplanner.modules.testing import panel as panel_module
    from dplanner.modules.testing.activity import TestsActivity

    _project, first, second = widget
    panel = panel_showing(services, first, "T100")

    shown = []

    def fake_preview(library, project_id, test_id, parent, *, files=None):
        shown.append(test_id)
        return (second.id, test_id)  # As if the reader pressed Show in Tests.

    monkeypatch.setattr(panel_module, "preview", fake_preview)
    panel.body.reference.emit("T101")

    assert shown == ["T101"]
    # The Tests tab is opened for it, and the *table* is what picks the row — a panel
    # publishes no selection of its own.
    activity = next(
        found for found in services.tabs.activities() if isinstance(found, TestsActivity)
    )
    assert activity.page.table.selected_tests() == ["T101"]


def test_the_preview_walks_a_chain_of_references_and_back_out(services, widget, qtbot):
    from dplanner.modules.testing.preview_dialog import TestPreview

    project, _first, _second = widget
    dialog = TestPreview(services.document, project.id, "T100", None)
    try:
        assert dialog.head.identity.text() == "T100"
        assert not dialog.back.isEnabled()  # Nothing to go back to yet.

        dialog.prose.reference.emit("T101")
        assert dialog.head.identity.text() == "T101"
        assert dialog.back.isEnabled()

        dialog.back.click()
        assert dialog.head.identity.text() == "T100"
        assert not dialog.back.isEnabled()
    finally:
        dialog.deleteLater()


def test_show_in_tests_answers_with_the_test_that_is_on_screen(services, widget):
    from dplanner.modules.testing.preview_dialog import TestPreview

    project, _first, second = widget
    dialog = TestPreview(services.document, project.id, "T100", None)
    try:
        dialog.prose.reference.emit("T101")
        dialog.open_verb.click()
        assert dialog.picked == (second.id, "T101")
    finally:
        dialog.deleteLater()


def test_a_body_never_links_its_own_id(services, make_project):
    from dplanner.modules.testing.preview_dialog import TestPreview

    project = make_project("Widget")
    step = Step(title="Fix list flicker")
    AddNodeCommand(project.id, step).redo(services.document)
    services.document.set_module_data(
        step.id, MODULE_ID, write([Test("T100", "Signs in", body="T100 is this one.")])
    )

    dialog = TestPreview(services.document, project.id, "T100", None)
    try:
        assert f"{LINK_SCHEME}:T100" not in dialog.prose.toHtml()
    finally:
        dialog.deleteLater()


def test_show_in_tests_widens_a_tab_that_was_hiding_the_test(services, widget):
    """The narrowing is taken off rather than the request answered with nothing."""
    from dplanner.modules.testing.activity import TESTS_KIND

    project, _first, second = widget
    services.document.set_module_data(
        second.id, MODULE_ID, write([Test("T101", "Rotates", body="Turn it.", archived=True)])
    )
    activity = services.tabs.open(TESTS_KIND, project.id)
    assert "T101" not in activity.ordered_tests()  # Off the roster, so off the page.

    assert activity.reveal("T101")
    assert activity.archived.isChecked()
    assert activity.page.table.selected_tests() == ["T101"]


def test_a_tab_already_showing_the_test_keeps_the_readers_filter(services, widget):
    """A visible change nobody asked for is made only when nothing else would work."""
    from dplanner.modules.testing.activity import TESTS_KIND

    project, _first, _second = widget
    activity = services.tabs.open(TESTS_KIND, project.id)
    activity.page.audience.set_active({"other"})  # What a test nobody classified reads as.
    assert "T100" in activity.ordered_tests()

    assert activity.reveal("T100")
    assert activity.page.audience.active() == ["other"]


def test_revealing_a_test_opens_the_category_it_is_folded_under(services, widget):
    from dplanner.modules.testing.activity import TESTS_KIND
    from dplanner.modules.testing.filing import Category, write_catalog

    project, first, second = widget
    found = services.document.project(project.id)
    services.document.set_module_data(
        project.id, MODULE_ID, write_catalog(found, [Category("Import"), Category("Smoke")])
    )
    for step, test_id, category in ((first, "T100", "Import"), (second, "T101", "Smoke")):
        services.document.set_module_data(
            step.id, MODULE_ID, write([Test(test_id, test_id, category=category)])
        )

    activity = services.tabs.open(TESTS_KIND, project.id)
    table = activity.page.table
    table.toggle_group("Smoke")
    row = next(index for index in range(table.rowCount()) if table.test_at(index) == "T101")
    assert table.isRowHidden(row)

    activity.reveal("T101")
    assert not table.isRowHidden(row)
