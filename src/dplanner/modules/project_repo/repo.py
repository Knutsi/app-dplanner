"""A project's repository association, and the one place its resolution is written down.

A product names one codebase, but a project can work against its own — a satellite repo,
a fork, a different clone of the same one. The association is module data on the project
node (``projects/<p>/modules/project_repo.json``), not model fields: the model stays
fact-free, and a build without this module round-trips the file untouched. It is
deliberately not an :class:`AspectSpec` — an aspect is a fact about a *step*.

``checkout_for`` is **the** resolution rule — the project's checkout, else the product's —
with exactly two readers: the composition root wires Run Agent through it, and ``repo
show`` prints it. Nothing else may re-derive the answer.

Like ``Product.checkout``, the per-project checkout is a per-machine path stored in the
shared workspace anyway — the same deliberate trade FORMAT.md records for the product's:
the CLI must resolve it, and the per-user config store is Qt.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Product, Project

MODULE_ID = "project_repo"

REPOSITORY_KEY = "repository"
CHECKOUT_KEY = "checkout"

DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def _read(project: Project, key: str) -> str:
    entry = project.module_data.get(MODULE_ID)
    value = entry.get(key) if entry else None
    return value if isinstance(value, str) else ""


def read_repository(project: Project) -> str:
    """The project's own repository URL, or "" when it rides the product's."""
    return _read(project, REPOSITORY_KEY)


def read_checkout(project: Project) -> str:
    """The project's own checkout path, or "" when it rides the product's."""
    return _read(project, CHECKOUT_KEY)


def write_association(repository: str, checkout: str) -> dict[str, Any]:
    """The entry to store. Both empty gives ``{}``, which removes the file."""
    entry: dict[str, Any] = {}
    if repository.strip():
        entry[REPOSITORY_KEY] = repository.strip()
    if checkout.strip():
        entry[CHECKOUT_KEY] = checkout.strip()
    return stamped(entry, DATA_FORMAT.version) if entry else {}


def checkout_for(product: Product, project: Project) -> str:
    """Where this project's work runs: its own checkout, else the product's."""
    return read_checkout(project) or product.checkout


def repository_for(product: Product, project: Project) -> str:
    """The repository this project's work belongs to: its own, else the product's."""
    return read_repository(project) or product.repository
