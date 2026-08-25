"""The module contract: two attributes, and nothing else.

A module is a feature package. It receives its dependencies at construction — from the
composition root, :func:`dplanner.modules.default_modules` — and installs itself in
``register()``. That is the entire contract.

It is a ``Protocol``, not a base class, so a module class inherits nothing, can be
constructed in a test on its own, and cannot accidentally acquire behaviour from a
framework superclass that changes under it.

**Why construction and registration are separate.** Construction is cheap and free of side
effects, so the composition root may build modules in whatever order the wiring needs —
including passing one module's method to another. ``register()`` is where every Qt object,
registry entry and signal connection happens, so the *framework* decides when installation
occurs: after the workspace is loaded and after older module data has been migrated. A
module may therefore do anything in ``register()`` — open its own tab, read its stored
data — without checking whether the world is ready yet.
"""

from typing import Protocol, runtime_checkable

from dplanner.core.module_data import ModuleDataFormat


@runtime_checkable
class Module(Protocol):
    id: str

    def register(self) -> None:
        """Install this module: register activity factories, actions and surfaces."""
        ...


@runtime_checkable
class PersistsModuleData(Protocol):
    """A module that stores data in the workspace declares its format here.

    Declared as data on the class rather than behind a method, because the builder has to
    know a module's storage format *before* that module has done anything — it migrates
    older data before any ``register()`` runs and reads it. Modules that store nothing
    declare nothing, and the builder's ``isinstance`` check skips them.
    """

    data_format: ModuleDataFormat
