"""The location role the reporting module acts on: where DPlanner writes for the people
who read without it.

A ``reporting`` row names a repository and a folder in it, and Save publishes the report
site there — committed scoped to that folder and pushed — with the tests export defaulting
to the same place. Worked in, so it needs a checkout: the person's own, or one DPlanner
keeps. Qt-free: the composition root gathers every module's ``roles.py`` into one registry.
"""

from dplanner.domain.locations import LocationRole

ROLE = LocationRole(
    id="reporting",
    label="Reporting",
    summary="Where DPlanner writes the report site and the tests export, for people who "
    "read without DPlanner.",
    writes=True,
)
