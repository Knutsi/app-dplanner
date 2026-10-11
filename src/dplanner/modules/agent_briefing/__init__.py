"""Agent briefing: what an agent is told when it is launched on a step.

The preflight, the step's and the project's facts, the instructions, the notes that reach
it and the report-back protocol — each read from the module that owns the fact, through its
``aspect.py`` — assembled into one prompt (``compose.brief``) for Run Agent, its dialogs, the
Agent tab and ``dplanner agent prompt``. Also what a playbook's stage adds to it
(``stages.py``), the coordinator's briefing over a selection (``coordinator.py``, ``dplanner
agent coordinate``), and where a run works (``worktree.py``): the name its worktree and
branch carry, under which checkout.

The package has no ``module.py``: it registers nothing and is headless all through, so any
module may import it (``tests/test_architecture.py``'s rule 4).
"""
