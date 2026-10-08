"""The agent-instruction aspect: what a coding agent should know before doing this step.

Its ``agent`` verbs print what an agent is told, too: ``agent prompt`` a step's briefing, and
``agent coordinate`` a coordinator's over a selection (``agent_briefing`` writes both).

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
