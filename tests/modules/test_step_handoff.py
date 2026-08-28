"""The handoff aspect: what a step leaves, who inherits it, and the one derivation.

The derivation half runs with no Qt and no store — a `files` function that raises KeyError
stands in for a store that has never flushed the node, which is also the real edge case.
"""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.domain.model import Product, Project, Step
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.step_handoff.aspect import (
    MODULE_ID,
    read_scope,
    write_scope,
)
from dplanner.modules.step_handoff.handoff import inherited, inherited_text, own


def _no_files(_step_id, _module_id):
    raise KeyError(_step_id)


def build(edges):
    """A product with one project whose steps and requires-edges are given as a dict."""
    product = Product(name="Widget")
    project = Project(title="Discovery")
    product.add_child(product.id, project)
    steps = {}
    for name in edges:
        steps[name] = Step(title=name)
        product.add_child(project.id, steps[name])
    for name, sources in edges.items():
        if sources:
            product.set_edges(steps[name].id, "requires", [steps[s].id for s in sources])
    return product, steps


def note(product, step, text, scope="downstream"):
    product.set_text(step.id, MODULE_ID, text)
    product.set_module_data(step.id, MODULE_ID, write_scope(scope))


# -- the derivation ----------------------------------------------------------------------------


def test_a_chain_inherits_every_ancestor_in_order():
    product, steps = build({"A": [], "B": ["A"], "C": ["B"]})
    note(product, steps["A"], "From A.")
    note(product, steps["B"], "From B.")
    titles = [h.title for h in inherited(product, steps["C"], _no_files)]
    assert titles == ["A", "B"]


def test_a_diamond_lists_the_shared_ancestor_once():
    product, steps = build({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]})
    note(product, steps["A"], "From A.")
    titles = [h.title for h in inherited(product, steps["D"], _no_files)]
    assert titles == ["A"]


def test_a_project_scoped_handoff_reaches_a_non_descendant():
    product, steps = build({"A": [], "B": []})
    note(product, steps["A"], "Everyone should know.", scope="project")
    titles = [h.title for h in inherited(product, steps["B"], _no_files)]
    assert titles == ["A"]


def test_a_downstream_handoff_does_not_reach_a_sibling():
    product, steps = build({"A": [], "B": []})
    note(product, steps["A"], "Only for my dependents.")
    assert inherited(product, steps["B"], _no_files) == []


def test_a_step_never_inherits_its_own_handoff():
    product, steps = build({"A": []})
    note(product, steps["A"], "Mine.", scope="project")
    assert inherited(product, steps["A"], _no_files) == []


def test_an_ancestor_with_nothing_to_say_is_omitted():
    product, steps = build({"A": [], "B": ["A"]})
    assert inherited(product, steps["B"], _no_files) == []


def test_an_unflushed_node_answers_no_assets_rather_than_crashing():
    product, steps = build({"A": [], "B": ["A"]})
    note(product, steps["A"], "From A.")
    (handoff,) = inherited(product, steps["B"], _no_files)
    assert handoff.assets == ()


def test_the_text_rendering_names_the_source_step():
    product, steps = build({"A": [], "B": ["A"]})
    note(product, steps["A"], "Keys are in the vault.")
    text = inherited_text(inherited(product, steps["B"], _no_files))
    assert 'From A:' in text and "Keys are in the vault." in text
    assert inherited_text([]) == "Nothing handed forward yet."


def test_own_is_none_when_there_is_nothing():
    product, steps = build({"A": []})
    assert own(product, steps["A"], _no_files) is None


def test_an_unknown_scope_reads_as_downstream():
    product, steps = build({"A": []})
    product.set_module_data(steps["A"].id, MODULE_ID, {"scope": "galaxy", "format": 1})
    assert read_scope(steps["A"]) == "downstream"


# -- the CLI -----------------------------------------------------------------------------------


@pytest.fixture
def cli(workspace):
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def invoke(*argv, expect=0, stdin=""):
        import sys

        out, err = StringIO(), StringIO()
        if stdin:
            real = sys.stdin
            sys.stdin = StringIO(stdin)
        try:
            code = run(
                registry,
                default_module_formats(),
                ["--workspace", str(workspace), *argv],
                out,
                err,
            )
        finally:
            if stdin:
                sys.stdin = real
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    invoke("project", "create", "Discovery")
    invoke("step", "add", "Discovery", "Set up CI")
    invoke("step", "add", "Discovery", "Deploy", "--after", "Set up CI")
    return invoke


def test_set_show_and_inherit_through_the_cli(cli, workspace):
    cli("handoff", "set", "Set up CI", "--file", "-", stdin="The keys live in the vault.")
    shown = json.loads(cli("handoff", "show", "Deploy", "--inherited", "--json"))
    assert shown["root"] == str(workspace)
    (row,) = shown["inherited"]
    assert row["title"] == "Set up CI"
    assert row["note"] == "The keys live in the vault."


def test_attach_makes_the_file_part_of_the_inheritance(cli, workspace, tmp_path):
    diagram = tmp_path / "diagram.png"
    diagram.write_bytes(b"png-bytes")
    cli("handoff", "set", "Set up CI", "--file", "-", stdin="See the diagram.")
    name = cli("handoff", "attach", "Set up CI", str(diagram)).strip()
    assert name.startswith("assets/")
    shown = json.loads(cli("handoff", "show", "Deploy", "--inherited", "--json"))
    (row,) = shown["inherited"]
    assert len(row["assets"]) == 1
    assert (workspace / row["assets"][0]).is_file()


def test_scope_project_reaches_everyone_and_clear_removes_it(cli, workspace):
    cli("step", "add", "Discovery", "Write docs")
    cli(
        "handoff",
        "set",
        "Set up CI",
        "--file",
        "-",
        "--scope",
        "project",
        stdin="Global note.",
    )
    shown = json.loads(cli("handoff", "show", "Write docs", "--inherited", "--json"))
    assert [row["title"] for row in shown["inherited"]] == ["Set up CI"]
    cli("handoff", "clear", "Set up CI")
    step_dir = workspace / "projects" / "discovery" / "steps" / "set-up-ci"
    assert not (step_dir / "modules" / "step_handoff.md").exists()
    assert not (step_dir / "modules" / "step_handoff.json").exists()
