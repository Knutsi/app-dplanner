"""Whether an AI provider is configured on this machine.

One row, not one per provider: the question a person has is "can DPlanner use AI here",
and the answer names whichever providers hold a key. The provider ids arrive from the
composition root — a module never imports another — and the key itself is read straight
out of the keychain, which is the only place any provider keeps one.

It advises. Every AI-gated control in the application is already disabled with its reason
(``AI_DISABLED_TIP``), so a machine without a key is a machine with fewer buttons, not a
broken one.
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
                words="Add one under Settings ▸ LLM to turn the AI-assisted features on."
            ),
        )
    ]
