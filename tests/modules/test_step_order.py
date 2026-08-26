"""The order view: waves on screen, and the two seams it reaches other features through."""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION
from dplanner.modules import default_cli_commands, default_module_formats


@pytest.fixture
def project(services):
    """A → B, A → C, and D waiting on both B and C: three waves, one with two steps."""
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    for title in ("A", "B", "C", "D"):
        AddNodeCommand(project.id, Step(title=title)).redo(product)
    a, b, c, d = project.steps
    for waiter, sources in ((b, [a]), (c, [a]), (d, [b, c])):
        SetEdgesCommand(waiter.id, "requires", [s.id for s in sources]).redo(product)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("order", project.id)


def waves_on_screen(tab):
    tree = tab.tree
    found = []
    for i in range(tree.topLevelItemCount()):
        header = tree.topLevelItem(i)
        found.append(
            (header.text(0), [header.child(j).text(0) for j in range(header.childCount())])
        )
    return found


# -- what it shows ---------------------------------------------------------------------------


def test_the_waves_are_shown_first_one_named_for_what_it_means(services, project, tab):
    assert waves_on_screen(tab) == [
        ("Ready to start — 1 step", ["A"]),
        ("Wave 2 — 2 steps", ["B", "C"]),
        ("Wave 3 — 1 step", ["D"]),
    ]


def test_the_waves_follow_the_graph(services, project, tab):
    """Nothing is stored, so a new edge changes the view with no recompute to remember."""
    _a, b, _c, _d = project.steps
    services.undo.push(SetEdgesCommand(b.id, "requires", []))
    assert waves_on_screen(tab)[0] == ("Ready to start — 2 steps", ["A", "B"])

    services.undo.undo()
    assert waves_on_screen(tab)[0] == ("Ready to start — 1 step", ["A"])


def test_a_step_row_carries_what_the_aspects_say(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand

    a = project.steps[0]
    services.undo.push(SetModuleDataCommand(a.id, "step_estimation", {"days": 3.0, "format": 1}))
    header = tab.tree.topLevelItem(0)
    assert "3d" in header.child(0).text(1)


def test_the_tab_is_titled_for_its_project_and_follows_a_rename(services, project, tab):
    from dplanner.domain.commands import SetFieldCommand

    assert tab.title == "Discovery — Order"
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert "Discovery Phase — Order" in [a.title for a in services.tabs.activities()]


def test_a_deleted_project_takes_its_order_tab_with_it(services, project, tab):
    from dplanner.domain.commands import RemoveNodeCommand

    services.undo.push(RemoveNodeCommand(project.id))
    assert services.tabs.activities() == []


# -- the two seams ---------------------------------------------------------------------------


def test_selecting_a_step_publishes_it_so_the_step_verbs_target_it(services, project, tab):
    """This view never learns the Step menu exists; it publishes and the verbs follow."""
    row = tab.tree.topLevelItem(0).child(0)
    tab.tree.setCurrentItem(row)

    context = services.context.current()
    assert context.selected_entities("step") == [project.steps[0].id]
    assert services.actions.spec("steps.rename").state(context).enabled


def test_activating_a_step_reveals_it_in_the_graph(services, project, tab):
    """The other seam: a callback from the composition root, so neither module imports the
    other."""
    row = tab.tree.topLevelItem(0).child(0)
    tab.tree.itemActivated.emit(row, 0)

    graph = next(
        a for a in services.tabs.activities() if a.uri.startswith("app://activity/project")
    )
    assert graph._scene.selected_step() == project.steps[0].id


def test_activating_a_wave_heading_does_nothing(services, project, tab):
    tab.tree.itemActivated.emit(tab.tree.topLevelItem(0), 0)
    assert [a.uri for a in services.tabs.activities()] == [tab.uri]


def test_the_action_opens_it_for_the_focused_project(services, project):
    from dplanner.framework.context import ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.actions.run("order.open", services.context.current())
    assert [a.uri for a in services.tabs.activities()] == [f"app://activity/order/{project.id}"]


# -- the CLI, with no window at all --------------------------------------------------------------


def test_the_cli_gives_the_same_answer(tmp_path):
    """No `qapp` fixture: what an agent asks is derived on the spot and cannot be stale."""
    from dplanner.core.storage.local import LocalStorage
    from dplanner.domain.seed import create_product

    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def cli(*argv):
        out = StringIO()
        code = run(registry, default_module_formats(), ["--workspace", str(root), *argv], out)
        assert code == 0, out.getvalue()
        return out.getvalue()

    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    found = json.loads(cli("order", "show", "Discovery", "--json"))["waves"]
    assert [[s["title"] for s in wave] for wave in found] == [["A"], ["B"]]
    assert json.loads(cli("order", "show", "Discovery", "--ready", "--json"))["waves"] == [found[0]]
