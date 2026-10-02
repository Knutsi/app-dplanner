"""The location role the reporting module acts on: where DPlanner writes for the people
who read without it.

A ``reporting`` row names a repository and a folder in it: File ▸ Export ▸ Report Site
and ``dplanner report site`` write there, and the tests export defaults to the same place.
Committing what was written is the person's call — Save never does. Worked in, so it needs
a checkout: the person's own, or one DPlanner keeps. Qt-free: the composition root gathers
every module's ``roles.py`` into one registry.
"""

from dplanner.domain.locations import LocationRole

ROLE = LocationRole(
    id="reporting",
    label="Reporting",
    summary="Where DPlanner writes the report site and the tests export, for people who "
    "read without DPlanner.",
    writes=True,
)
