"""Finding a product, opening it, and putting it back.

Every mutating verb needs the same four things around it, and each one is a bug if a verb
has to remember it: run the pending module-data migrations, collect what got dirty, write it
once, and close. So no verb does any of them — this module wraps them all in one context
manager, and ``main.py`` is the only caller.

The migration step is the one that is easy to miss. ``migrate_module_data`` is called in
exactly one other place, ``AppBuilder.build()``. A CLI that skipped it would let a module's
writer stamp the current format onto one node while its siblings stayed at an older one, and
the next GUI open would migrate the untouched ones and leave the stamped one alone — data
loss that shows up months later, in a workspace nobody can reconstruct.
"""

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from dplanner.cli.command import CliContext, CliError
from dplanner.core.module_data import ModuleDataFormat, migrate_module_data
from dplanner.core.storage.locations import StorageLocation, open_storage, parse_location
from dplanner.domain.store import PRODUCT_META, ProductStore, StaleWorkspaceError

WORKSPACE_ENV = "DPLANNER_WORKSPACE"


def find_workspace(explicit: str | None = None, start: Path | None = None) -> StorageLocation:
    """Where the product is, in the order a person would expect.

    ``--workspace``, then ``$DPLANNER_WORKSPACE``, then **upwards from the working
    directory** looking for a ``product.json``. That last one is the whole point: an agent is
    already sitting in the product's checkout, so if the plan lives in the repository the
    CLI needs no configuration at all.

    There is deliberately no "last opened" fallback. That value lives in Qt's settings, and
    this layer does not load Qt — guessing at a workspace the user cannot see named on the
    command line would be worse than asking anyway.
    """
    if explicit:
        return parse_location(explicit)
    from_env = os.environ.get(WORKSPACE_ENV)
    if from_env:
        return parse_location(from_env)
    found = _walk_up(start or Path.cwd())
    if found is None:
        raise CliError(
            "no product found here. Run inside a product directory, or pass "
            f"--workspace PATH (or set {WORKSPACE_ENV})."
        )
    return parse_location(str(found))


def _walk_up(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        if (directory / PRODUCT_META).is_file():
            return directory
    return None


@contextmanager
def open_product(
    location: StorageLocation,
    formats: Sequence[ModuleDataFormat],
    out: TextIO,
    *,
    as_json: bool = False,
) -> Iterator[CliContext]:
    """Open a product, hand it to a verb, and write back exactly what changed.

    Nothing is written if the verb raises: a run that failed halfway is worse than a run that
    did nothing, and version control cannot tell the difference after the fact.
    """
    storage = open_storage(location)
    store = ProductStore(storage)
    if not store.exists():
        raise CliError(f"no product at {storage.label} — open it in DPlanner once to create it")
    product = store.load()

    context = CliContext(out=out, as_json=as_json, opened=product, opened_store=store)
    store.dirty.connect(lambda owner_id, aspect: context.marks.add((owner_id, aspect)))
    migrate_module_data(store, formats)
    try:
        yield context
        try:
            store.flush(context.marks)
        except StaleWorkspaceError as error:
            # Somebody else wrote to this folder while the verb ran — another CLI run, or a
            # window that autosaved. Refusing is what makes a second lock unnecessary: the
            # loser is told, nothing is overwritten, and running again picks up the change.
            raise CliError(f"{error} — nothing was written; run this again") from error
    finally:
        store.close()
