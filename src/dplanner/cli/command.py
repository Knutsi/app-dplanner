"""What a command is, what it is handed, and the registry that collects them.

The same shape as every other registry in this application: a dict keyed by id, refusing
duplicates, returning sorted. That similarity is deliberate — a module contributing a verb
should recognise the mechanism from contributing an action.
"""

import json
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

from dplanner.core.repository import DirtyMark
from dplanner.domain.commands import Command
from dplanner.domain.model import Product
from dplanner.domain.store import ProductStore


class CliError(Exception):
    """Something the user can fix: no workspace, no such project, a bad argument.

    Raised by a verb and printed as one line. Anything else that escapes is a bug and keeps
    its traceback, because hiding those makes them impossible to report.
    """


@dataclass
class CliContext:
    """One invocation: the product it opened, and where its output goes.

    The product and the store are optional on the dataclass and required through the
    properties, because a few verbs — ``skill show``, for one — have nothing to do with a
    product. That way a verb that does need one still reads a plain ``Product``, with no
    None-check of its own, and a verb that reaches for one it was not given says so.
    """

    out: TextIO
    as_json: bool = False
    opened: "Product | None" = None
    opened_store: "ProductStore | None" = None
    marks: set[DirtyMark] = field(default_factory=set)

    @property
    def product(self) -> Product:
        if self.opened is None:
            raise CliError("this command needs a product")
        return self.opened

    @property
    def store(self) -> ProductStore:
        if self.opened_store is None:
            raise CliError("this command needs a product")
        return self.opened_store

    def apply(self, command: Command) -> None:
        """Apply a domain command.

        The CLI has no undo stack — a run is a transaction, and version control is the undo
        — so it calls ``redo`` directly. It is the same object the GUI would have pushed,
        which is what makes a CLI edit undoable in a window that is open on the same product.

        The model raises ``ValueError`` for exactly one thing: a change that cannot be true
        — a cycle, an unknown edge kind, a field the node does not have. Those are the
        user's to fix, so they are reported as one line rather than as a traceback. Anything
        else keeps its traceback, because a bug that prints like a usage error never gets
        reported.
        """
        try:
            command.redo(self.product)
        except ValueError as error:
            raise CliError(str(error)) from error

    def report(self, data: object, text: str) -> None:
        """One result, in whichever form the caller asked for.

        Text by default, because a person is reading; ``--json`` for an agent, and the two
        are generated from the same call so a verb cannot answer one of them and forget the
        other.
        """
        if self.as_json:
            print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), file=self.out)
        else:
            print(text, file=self.out)


@dataclass(frozen=True)
class CliCommand:
    """One ``dplanner <noun> <verb>``.

    Always two words. A predictable shape is worth more than brevity here: an agent that has
    seen ``project list`` can guess ``step list`` and be right.
    """

    path: tuple[str, str]
    summary: str  # One line. It reaches --help and the generated skill verbatim.
    run: Callable[[CliContext, Namespace], int]
    # Add this command's own arguments. A callback rather than an argument-spec of our own:
    # argparse already knows how to describe itself, and its help *is* what the skill
    # generator reads — so no argument is ever described in two places.
    configure: Callable[[ArgumentParser], None] = lambda _parser: None
    # False for verbs that make no sense against a product — `skill show`, for instance.
    needs_workspace: bool = True
    examples: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return " ".join(self.path)


class CliRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CliCommand] = {}

    def register(self, command: CliCommand) -> None:
        if command.id in self._commands:
            raise ValueError(f"cli command {command.id!r} already registered")
        self._commands[command.id] = command

    def register_all(self, commands: list[CliCommand]) -> None:
        for command in commands:
            self.register(command)

    def commands(self) -> list[CliCommand]:
        return sorted(self._commands.values(), key=lambda c: c.path)

    def groups(self) -> dict[str, list[CliCommand]]:
        """Commands by their first word, in order — the shape the parser tree takes."""
        grouped: dict[str, list[CliCommand]] = {}
        for command in self.commands():
            grouped.setdefault(command.path[0], []).append(command)
        return grouped
