"""The location role the spec module acts on: where a project's specs come from.

A ``spec`` row names a repository and a folder in it; the Specs tab's *Add Spec ▸ From
Repository…* adds one and makes it a git document source in one gesture, *From Location…*
does the same for a row added in Project ▸ Settings, and the row is read-only — fetched on
demand into a managed clone, never a checkout anybody has to pick. Qt-free: the
composition root gathers every module's ``roles.py`` into one registry.
"""

from dplanner.domain.locations import LocationRole

ROLE = LocationRole(
    id="spec",
    label="Spec",
    summary="Where the specifications come from — fetched into the plan's spec documents.",
    writes=False,
    several=True,
)
