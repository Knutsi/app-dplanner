"""The getting-started guide: what Home walks a newcomer through, as plain data.

A step names a verb by its action id rather than describing one, so the button beside it
*is* that verb — the File menu's New Project…, the Tools menu's Install DPlanner… — greyed
with the verb's own words when it cannot run here, and still right if the verb is ever
refiled. The words are README's *What a plan is* and *Working with an agent*, cut to what a
person needs before their first click. ``tests/modules/home/test_home.py`` holds every id to the
registry, since a step naming a verb nobody registered would be a button that does nothing.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GuideStep:
    title: str
    words: str
    action: str  # The ActionSpec id the step's button runs.


GUIDE = (
    GuideStep(
        "Start a project",
        "A project is a unit of work with a beginning and an end. Its plan is kept in a git"
        " repository — beside the code it plans, or in a plan repository of its own.",
        "projects.new",
    ),
    GuideStep(
        "Or join one somebody shared",
        "A shared project arrives as a link. Paste it, or browse a plan repository you"
        " already have.",
        "projects.add",
    ),
    GuideStep(
        "Talk the steps out",
        "Steps are a graph, not a list: a step waits on the steps before it. Before there"
        " are any, open an agent in the project's code and talk them out of the spec.",
        "agent.open",
    ),
    GuideStep(
        "Let an agent drive the plan",
        "Install the skill once, and Claude Code, Codex or OpenCode can read and change the"
        " plan from its terminal.",
        "install.dplanner",
    ),
    GuideStep(
        "Choose how agents open",
        "Run Agent opens a terminal on a step with its briefing, through a launch profile:"
        " an agent paired with a terminal.",
        "agent.profiles",
    ),
)
