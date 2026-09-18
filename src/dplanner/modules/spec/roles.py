"""The location role the spec module acts on: where a project's specs come from.

A ``specs`` row names a repository and a folder in it; the Specs tab's *Add Spec ▸ From
Location…* turns one into a git document source, and the row is read-only — fetched on
demand into a managed clone, never a checkout anybody has to pick. Qt-free: the
composition root gathers every module's ``roles.py`` into one registry.
"""

from dplanner.domain.locations import LocationRole

ROLE = LocationRole(
    id="specs",
    label="Specs",
    summary="Where the specifications come from — fetched into the plan's spec documents.",
    writes=False,
    several=True,
)
