"""How ``step add`` authors a step in one call — many modules' flags on one verb.

A fully authored step needs a description, an instruction, an estimate and its
requirement links, and each of those belongs to a different module. Five commands per
step is what that costs when every module keeps to its own verb — most of a real plan's
invocations, measured. So ``step add`` takes contributions: each module's Qt-free
``cli.py`` exports a :class:`StepAuthor` — the flags it registers and what it does with
them — and the composition root hands the list to ``projects_cli.commands()``, exactly
as it hands lint its checks. The shape lives here, like :class:`~dplanner.cli.lint.LintCheck`,
because the contributing modules may not import each other and ``cli/`` sits below them all.

There is deliberately no rollback in an author: a run is a transaction, and an author
that raises aborts the whole ``step add`` with nothing written — the step included.
``ARCHITECTURE.md``'s *Authoring a step is one verb, many modules* holds that reasoning,
and holds it against any future refactor that would flush eagerly.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dplanner.cli.command import CliContext
from dplanner.domain.model import Step


def _never_stdin(_args: Namespace) -> bool:
    return False


@dataclass(frozen=True)
class StepAuthored:
    """One module's contribution to a just-added step: JSON keys, and a report line."""

    data: dict[str, Any]
    note: str


@dataclass(frozen=True)
class StepAuthor:
    """A module's hands on ``step add``.

    ``configure`` registers the module's flags on the verb's parser; ``author`` applies
    them to the fresh step, returning what it did — or ``None`` when its flags were not
    used. ``reads_stdin`` says whether the parsed arguments would consume stdin (a
    ``--…-file -``), so the verb can refuse two claims on one pipe before either reads.
    """

    configure: Callable[[ArgumentParser], None]
    author: Callable[[CliContext, Step, Namespace], StepAuthored | None]
    reads_stdin: Callable[[Namespace], bool] = _never_stdin
