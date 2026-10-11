"""What Run Agent needs of this machine: an agent CLI, and somewhere to open it.

The rows are all advice: a plan is worth keeping on a machine that can do none of this, and
approach item 6 of the step that added the checklist says so outright — an agent CLI and a
multiplexer are recommended, never blocking.

**A row says whether some agent can run, and a row per harness says how far that one got**
— on PATH, a version, signed in (``availability.py``). Both are built from the harness tuple
the composition root hands over, so a fourth agent is still a fourth module and no new file
anywhere else (`.claude/rules/agents.md`). An agent that is simply not installed is *fine*:
nobody needs all three, so its row is well and says it is optional. Only an agent that is
there and cannot run — broken, or signed out — is a row to act on, and its remedy is the
harness's own sign-in command. The summary row comes first and asks every CLI afresh; the
rows under it read what it just found rather than running each CLI twice in one sweep.

A terminal is judged by the launcher's own ``is_installed``, the same rule Run Agent obeys,
so the checklist never claims a terminal the launcher would refuse — tmux is usable from
inside a tmux session and not otherwise, and the row says which ones are usable now.
"""

import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.domain.agents import AgentHarness, AgentLevel, AgentStatus
from dplanner.modules.agent_launch.availability import Availability
from dplanner.modules.agent_launch.launcher import is_installed, terminals_for

Which = Callable[[str], str | None]


def _words(status: AgentStatus) -> str:
    if status.level is AgentLevel.MISSING:
        return "not installed — optional"
    return ", ".join(part for part in (status.version, status.detail) if part)


def _agent(availability: Availability, harness: AgentHarness) -> Reading:
    status = availability.cached(harness.id) or availability.check(harness.id)
    return Reading(
        ok=status.level in (AgentLevel.MISSING, AgentLevel.USABLE), detail=_words(status)
    )


def _agents(availability: Availability, harnesses: Sequence[AgentHarness]) -> Reading:
    read = [availability.check(harness.id) for harness in harnesses]
    usable = [status.label for status in read if status.usable]
    if usable:
        return Reading(ok=True, detail=f"{', '.join(usable)} can run here")
    stuck = [status.reason for status in read if status.level is not AgentLevel.MISSING]
    names = ", ".join(harness.label for harness in harnesses)
    return Reading(ok=False, detail="; ".join(stuck) or f"none of {names} is on PATH")


def _agent_row(availability: Availability, harness: AgentHarness) -> MachineCheck:
    command = harness.sign_in.command if harness.sign_in is not None else ""
    return MachineCheck(
        id=f"agents.{harness.id}",
        group="Agents",
        label=harness.label,
        probe=lambda: _agent(availability, harness),
        remedy=Remedy(
            words="A playbook can run it headless once it works here and is signed in.",
            command=command,
        ),
    )


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
    availability: Availability | None = None,
) -> list[MachineCheck]:
    environment = os.environ if env is None else env
    known = Availability(harnesses, which=which) if availability is None else availability
    return [
        MachineCheck(
            id="agents.cli",
            group="Agents",
            label="An agent CLI",
            probe=lambda: _agents(known, harnesses),
            remedy=Remedy(
                words="Run Agent needs one of them installed, and a playbook one signed in.",
                command="see the agent's own install instructions",
            ),
        ),
        *(_agent_row(known, harness) for harness in harnesses),
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
