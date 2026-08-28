"""The agent-run aspect, in the running application: a format declaration, no surface.

The aspect is written by Run Agent (through the composition root's ``record_launch``
callback) and by the CLI from inside the agent's shell; the canvas reads it through the
composition root's accent translation. Nothing registers here — the module exists so
GUI-side migration sees the format.
"""

from dplanner.modules.step_agent_run.aspect import DATA_FORMAT, MODULE_ID


class StepAgentRunModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def register(self) -> None:
        """Nothing to install: see the module docstring."""
