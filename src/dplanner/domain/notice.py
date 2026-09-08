"""What a notice is: the Qt-free shape a module hands the notices inbox.

A notice is a **standing condition**, never a stored event: a module is asked what is
true now and answers with the notices that stand, so one that has been dealt with is
simply absent from the next answer. Written here, beside :mod:`dplanner.domain.document_source`
and for the same reason — the module that raises one and the module that lists them may
not import each other, so what crosses between them lives in ``domain/``.
"""

from dataclasses import dataclass

# Where a notice's Open goes — three address spaces the window already has:
#   ("step", step_id)                the step, revealed in its project
#   ("tab", kind, target)            a tab, ``target`` a project id or "" for a singleton
#   ("action", action_id)            a verb, run against the current context
type Target = tuple[str, ...]


@dataclass(frozen=True)
class Notice:
    key: str  # Stable within its source — "stale", or "<project>:<source>" — the mute's name.
    title: str  # Line one: what stands. "Agent skill is out of date"
    detail: str  # Line two: what resolves it. "Installed from another build; Update rewrites it."
    target: Target  # What Open does.
    where: str = ""  # A note at the right: the project's name, the source's.
