"""The house default for how a project's graph is shaped.

A project's topology says how *its* graph is shaped; this is what applies wherever that
text is silent — one start, milestones in a chain, work that branches out of one and
collects into the next. Two rules decide where it lives and how it is delivered.

**It is printed, never stored.** Seeding it into a project's topology would be the obvious
move and it is the trap: ``module_text["spec"]`` reaches every agent briefing, so a house
document written there would be paid for again on every step anybody ever executes. The
project's own text stays the project's own, and the default is read beside it.

**One door, and the gate already built it.** ``topology show`` is the verb the graph-editing
verbs refuse until — so it is run by every agent that is about to shape a graph and by no
agent that is not. Printing the default there reaches Codex and OpenCode as readily as
Claude, which a file bundled with the skill would not.

``ARCHITECTURE.md``'s *The topology is read before the graph is edited* has the reasoning.
"""

from pathlib import Path


def guide() -> str:
    return (Path(__file__).parent / "shaping.md").read_text(encoding="utf-8")
