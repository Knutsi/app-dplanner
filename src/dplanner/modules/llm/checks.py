"""Whether an AI provider is configured on this machine.

One row, not one per provider: the question a person has is "can DPlanner use AI here",
and the answer names whichever providers hold a key. The provider ids arrive from the
composition root — a module never imports another — and the key itself is read straight
out of the keychain, which is the only place any provider keeps one.

It advises, and nothing in this build needs it: compiling documentation was the one feature
that called the service, and it launches an agent now (*Documentation is fragments*). The row
stays because the service and its providers do — dormant on purpose, ready for whatever calls
next — and because a person who has configured a key wants to see that it took.
"""

from collections.abc import Sequence

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.core.secrets import get_secret

# What every provider module calls its key under its own id — the one convention they share.
KEY = "api_key"


def _configured(providers: Sequence[tuple[str, str]]) -> Reading:
    found = [label for module_id, label in providers if get_secret(module_id, KEY)]
    if found:
        return Reading(ok=True, detail=f"{', '.join(found)} configured")
    named = ", ".join(label for _module_id, label in providers)
    return Reading(ok=False, detail=f"no key stored for {named}" if named else "no providers")


def checks(*, providers: Sequence[tuple[str, str]]) -> list[MachineCheck]:
    """``providers`` is ``(module id, label)`` per provider module, in the root's order."""
    return [
        MachineCheck(
            id="llm.key",
            group="Services",
            label="An AI provider key",
            probe=lambda: _configured(providers),
            remedy=Remedy(
                words="Add one under Settings ▸ LLM. No feature needs one today — the"
                " service is here for whatever asks next."
            ),
        )
    ]
