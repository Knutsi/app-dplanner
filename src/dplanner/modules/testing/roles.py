"""The location role the testing module acts on: where a project's tests are written.

A ``tests`` row names a repository and a folder in it — usually inside the code — and is
worked in, so it needs a checkout the person owns. Qt-free: the composition root gathers
every module's ``roles.py`` into one registry.
"""

from dplanner.domain.locations import LocationRole

ROLE = LocationRole(
    id="tests",
    label="Tests",
    summary="Where the project's tests are written — a folder in a repository.",
    writes=True,
    default_path="tests",
)
