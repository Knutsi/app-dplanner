"""Whether this machine can keep a credential at all.

A Confluence token lives only in the OS keychain — there is no plaintext fallback, by
design — so a machine with no usable backend cannot connect a source however right the
address is. The row advises rather than blocks: a plan without an external spec source
never asks for one, and the Connect dialog already refuses with this very sentence.

The answer is :func:`~dplanner.core.secrets.backend_problem`, which inspects the backend
keyring chose rather than storing a probe value — a write is what raises a keychain prompt,
and a checklist asking whether it *may* store must not.
"""

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.core.secrets import backend_problem


def _keychain() -> Reading:
    problem = backend_problem()
    return Reading(ok=problem is None, detail=problem or "usable")


def checks() -> list[MachineCheck]:
    return [
        MachineCheck(
            id="secrets.keychain",
            group="Services",
            label="OS keychain",
            probe=_keychain,
            remedy=Remedy(
                words="Confluence sources and AI provider keys are kept here and nowhere else.",
            ),
        )
    ]
