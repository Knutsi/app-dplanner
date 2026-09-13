"""What Run Agent needs of this machine: an agent CLI, and somewhere to open it.

Three rows, all advice: a plan is worth keeping on a machine that can do none of this, and
approach item 6 of the step that added the checklist says so outright — an agent CLI and a
multiplexer are recommended, never blocking.

**One row for the agent CLI, not one per harness.** A fourth agent must be a fourth module
and no new file anywhere else (`.claude/rules/agents.md`), so the row is built from the
harness tuple the composition root hands over and reads each one's ``binary`` — the field
the contract has carried unread since it was added. The row's words name which were found.

A terminal is judged by the launcher's own ``is_installed``, the same rule Run Agent obeys,
so the checklist never claims a terminal the launcher would refuse — tmux is usable from
inside a tmux session and not otherwise, and the row says which ones are usable now.
"""

import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.domain.agents import AgentHarness
from dplanner.modules.step_agent_instruction.launcher import is_installed, terminals_for

Which = Callable[[str], str | None]


def _agents(harnesses: Sequence[AgentHarness], which: Which) -> Reading:
    found = [harness.label for harness in harnesses if harness.binary and which(harness.binary)]
    missing = [harness.label for harness in harnesses if harness.label not in found]
    if found:
        detail = ", ".join(found)
        return Reading(ok=True, detail=f"{detail} on PATH")
    return Reading(ok=False, detail=f"none of {', '.join(missing)} is on PATH")


def _terminals(platform: str, which: Which, env: Mapping[str, str], multiplexers: bool) -> Reading:
    usable = [
        preset.label
        for preset in terminals_for(platform)
        if preset.multiplexer is multiplexers and is_installed(preset, which, env)
    ]
    if usable:
        return Reading(ok=True, detail=", ".join(dict.fromkeys(usable)))
    return Reading(ok=False, detail="none of the ones this platform knows")


def checks(
    *,
    harnesses: Sequence[AgentHarness],
    which: Which = shutil.which,
    env: Mapping[str, str] | None = None,
    platform: str = sys.platform,
) -> list[MachineCheck]:
    environment = os.environ if env is None else env
    return [
        MachineCheck(
            id="agents.cli",
            group="Agents",
            label="An agent CLI",
            probe=lambda: _agents(harnesses, which),
            remedy=Remedy(
                words="Run Agent needs one of them installed to open an agent in.",
                command="see the agent's own install instructions",
            ),
        ),
        MachineCheck(
            id="agents.terminal",
            group="Agents",
            label="A terminal to launch in",
            probe=lambda: _terminals(platform, which, environment, multiplexers=False),
            remedy=Remedy(
                words="Without one, Run Agent can only hand you the briefing to run yourself.",
            ),
        ),
        MachineCheck(
            id="agents.multiplexer",
            group="Agents",
            label="A multiplexer",
            probe=lambda: _terminals(platform, which, environment, multiplexers=True),
            remedy=Remedy(
                words="herdr or zellij puts several agents side by side in one window; "
                "tmux does too, from inside a tmux session.",
            ),
        ),
    ]
