"""Where clones land on this machine: asked once, then remembered.

A plan repository cloned from Open Project and a code repository cloned from the Project
dialog go to the same folder, because that is how people keep checkouts — one directory
of repositories under a name that varies by habit (``~/Code``, ``~/src``, ``~/repos``).
The first clone asks, with the likely folders found on disk as rows and the first of them
picked; *Settings ▸ Repositories* changes it later. Per user, per machine: ``user_config``.

The **clone policy** is the second fact here, and it decides where a repository a *verb*
needs — Run Agent on code nobody checked out, a report published to a repository this
machine lacks — lands: kept by DPlanner under its configuration directory (the default,
for the person who never wants to manage a folder), or in the repositories folder above
(for a developer who wants every clone where their others are). It decides the
destination only, never whether the verb runs.
"""

from pathlib import Path

from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.projects.repos import (
    MODULE_ID,
)

FOLDER_KEY = "repositories_folder"
POLICY_KEY = "clone_policy"
KEPT = "kept"  # DPlanner keeps the clone under config_dir()/checkouts/.
FOLDER = "folder"  # Into the repositories folder, asked once.
POLICIES = ((KEPT, "Let DPlanner keep them"), (FOLDER, "Clone into my repositories folder"))


def repositories_folder() -> Path | None:
    raw = get_global(MODULE_ID, FOLDER_KEY, "")
    return Path(str(raw)).expanduser() if raw else None


def set_repositories_folder(folder: Path) -> None:
    set_global(MODULE_ID, FOLDER_KEY, str(folder))


def clone_policy() -> str:
    """Where a repository a verb needs lands: :data:`KEPT` unless the person chose."""
    raw = str(get_global(MODULE_ID, POLICY_KEY, KEPT))
    return raw if raw in (KEPT, FOLDER) else KEPT


def set_clone_policy(policy: str) -> None:
    set_global(MODULE_ID, POLICY_KEY, policy if policy in (KEPT, FOLDER) else KEPT)
