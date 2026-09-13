"""The default shape, and the one door that prints it.

``topology show`` is the verb the graph-editing verbs refuse until, so it is run by every
agent about to shape a graph and by no agent that is not. That is what makes it the place
to print the house default — and what these tests are really pinning: the default reaches
a shaping agent, reaches no briefing, and never moves the digest the gate compares.
"""

import json

import pytest

from dplanner.cli.shaping import guide
from dplanner.cli.skill import SKILL_FILE, generate
from dplanner.modules import aspect_specs


def data(text):
    return json.loads(text)


@pytest.fixture
def skill(registry):
    return generate(registry, aspect_specs())[SKILL_FILE]


@pytest.fixture
def project(cli):
    cli("project", "create", "Search rewrite")
    return "Search rewrite"


# -- what the guide says -------------------------------------------------------------------


def test_the_guide_draws_the_shape_a_graph_should_take():
    """The morphology is the half no registry can render and no project had until now."""
    prose = " ".join(guide().split())
    assert "Project start" in prose
    assert "Milestones in a chain" in prose
    assert "branches out and collects back" in prose
    assert "Sequential milestones, parallel steps" in prose
    # A marker node is still a step, and lint asks a step for these two.
    assert "'Project start' --days 0 --describe-file -" in prose


def test_the_guide_asks_for_the_release_scope_rather_than_inventing_it():
    """What ships when is a decision, so the agent carries a proposal and asks."""
    prose = " ".join(guide().split())
    assert "What ships in each release is a decision, not a derivation" in prose
    assert "carrying a proposal and the reasoning behind it" in prose
    assert "Mock data first" in prose


def test_the_guide_cuts_steps_for_an_agent_to_run():
    """Large and independent, cut along the seams of the thing rather than its verbs."""
    prose = " ".join(guide().split())
    assert "Cluster what is connected, and cut for calendar time" in prose
    assert "designs the data types and the API that changes them" in prose
    assert "A design foundation lands before the views that depend on it" in prose


def test_the_spatial_loop_moved_here_with_the_rest_of_the_shaping(skill):
    """Look, sort, make room or tidy, look again, keep — a shaping act, so it left the
    skill with its neighbours. The skill keeps only the rule that regions are gone."""
    prose = " ".join(guide().split())
    assert "layout show <project> --map" in prose
    assert "layout shift <project> --x 640 --by 300" in prose
    assert "layout tidy <project>" in prose
    assert "2 hours per task" in prose and "--days 0.25" in prose
    assert "when the same sentence appears on several pages" in prose
    assert "unless the project's topology says otherwise" in prose
    assert "lump similar work into one large step" in prose
    assert "region" not in prose.lower()
    assert "## Working from a specification" not in skill


def test_the_guide_tells_the_project_to_write_only_what_differs():
    """The trap it exists to close: a topology reaches every briefing, so a house document
    pasted into one is paid for again on every step anybody ever executes."""
    prose = " ".join(guide().split())
    assert "Never paste this document into it" in prose
    assert "reaches every agent briefing" in prose


# -- the door ------------------------------------------------------------------------------


def test_topology_show_prints_the_project_first_and_the_default_after(cli, cli_stdin, project):
    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.\n")
    out = cli("topology", "show", project)
    assert out.index("Views are features.") < out.index("# How a graph is shaped")
    assert guide().rstrip() in out


def test_brief_prints_the_project_text_alone(cli, cli_stdin, project):
    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.\n")
    out = cli("topology", "show", project, "--brief")
    assert "Views are features." in out
    assert "How a graph is shaped" not in out


def test_a_project_with_no_topology_is_told_the_shape_and_which_verb_writes_one(cli, project):
    """The authoring moment: `topology set` is ungated, so a topology written before the
    default was read is the one that gets the shape wrong."""
    out = cli("topology", "show", project)
    assert "no topology yet" in out and "topology set" in out
    assert "# How a graph is shaped" in out


def test_the_json_carries_the_default_and_brief_empties_it(cli, cli_stdin, project):
    """One call renders both surfaces, so a verb cannot answer one and forget the other."""
    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.\n")
    assert data(cli("topology", "show", project, "--json"))["default"] == guide()
    brief = data(cli("topology", "show", project, "--brief", "--json"))
    assert brief["default"] == "" and brief["topology"] == "Views are features.\n"


def test_the_briefing_carries_the_project_topology_and_not_the_default(cli, cli_stdin, project):
    """The guard this whole design exists for. An executing agent reads its briefing and
    never runs `topology show`; a default stored or briefed would be paid for on every step
    anybody ever executes."""
    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.\n")
    cli_stdin("step", "add", project, "Build it", "--agent", "--describe-file", "-", stdin="Do it.")
    prompt = cli("agent", "prompt", "S1")
    assert "## Topology" in prompt and "Views are features." in prompt
    assert "How a graph is shaped" not in prompt


def test_the_digest_is_the_projects_own_text(cli, cli_stdin, project):
    """What is hashed is what was recorded, never what was printed — or the day
    ``shaping.md`` gained a comma would un-read every project on the machine."""
    from dplanner.cli.gate import digest

    cli_stdin("topology", "set", project, "--file", "-", stdin="Views are features.\n")
    shown = data(cli("topology", "show", project, "--json"))
    assert shown["digest"] == digest("Views are features.\n")
    assert shown["digest"] == data(cli("topology", "show", project, "--brief", "--json"))["digest"]
