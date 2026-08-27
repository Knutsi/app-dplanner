"""``dplanner handoff …`` — what a step leaves behind, and what a step inherits.

``handoff show --inherited`` is how an agent starting a step gathers its context: every
ancestor's note, every project-scoped note, and the files they carried — with the workspace
root in the ``--json`` form so paths can be made absolute.
"""

from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step
from dplanner.domain.assets import assets, attach
from dplanner.domain.commands import EditTextCommand, SetModuleDataCommand
from dplanner.domain.model import TextEdit
from dplanner.modules.step_handoff.aspect import (
    MODULE_ID,
    SCOPES,
    read_note,
    read_scope,
    write_scope,
)
from dplanner.modules.step_handoff.handoff import Handoff, inherited, inherited_text, own


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("handoff", "set"),
            summary="Replace a step's handoff note from a file or stdin.",
            configure=_configure_set,
            run=_set,
            examples=(
                "echo 'The API keys live in vault.' | dplanner handoff set 'Set up CI' --file -",
                "dplanner handoff set 'Set up CI' --file notes.md --scope project",
            ),
        ),
        CliCommand(
            path=("handoff", "show"),
            summary="A step's own handoff — or everything it inherits, with --inherited.",
            configure=_configure_show,
            run=_show,
            examples=(
                "dplanner handoff show 'Set up CI'",
                "dplanner handoff show 'Deploy' --inherited --json",
            ),
        ),
        CliCommand(
            path=("handoff", "attach"),
            summary="Add a file to a step's handoff and print the path to reference.",
            configure=_configure_attach,
            run=_attach,
            examples=("dplanner handoff attach 'Set up CI' diagram.png",),
        ),
        CliCommand(
            path=("handoff", "assets"),
            summary="List the files a step's handoff carries.",
            configure=_one_step,
            run=_assets,
            examples=("dplanner handoff assets 'Set up CI'",),
        ),
        CliCommand(
            path=("handoff", "clear"),
            summary="Remove a step's handoff note and scope; attached files stay.",
            configure=_one_step,
            run=_clear,
            examples=("dplanner handoff clear 'Set up CI'",),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("--file", required=True, help="a text file, or - for stdin")
    parser.add_argument(
        "--scope",
        choices=SCOPES,
        help="who it reaches: downstream steps (default) or the whole project",
    )


def _configure_show(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument(
        "--inherited",
        action="store_true",
        help="what this step inherits from its ancestors and the project",
    )


def _configure_attach(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("file", help="the file to copy in beside the step")


def _set(context: CliContext, args: Namespace) -> int:
    import sys

    if args.file == "-":
        body = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            raise CliError(f"no such file: {args.file}")
        body = path.read_text()

    step = find_step(context.product, args.step)
    current = read_note(step)
    edit = TextEdit(step.id, MODULE_ID, 0, current, body)
    context.apply(EditTextCommand(edit, label="Set Handoff"))
    if args.scope is not None:
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write_scope(args.scope)))
    context.report(
        {"step": step.id, "characters": len(body), "scope": args.scope or read_scope(step)},
        f"{step.title}: {len(body)} characters, {args.scope or read_scope(step)}",
    )
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    files = context.store.files
    root = str(context.store.storage.root)
    data: dict[str, Any] = {"step": step.id, "root": root}
    if args.inherited:
        handoffs = inherited(context.product, step, files)
        data["inherited"] = [_row(handoff) for handoff in handoffs]
        context.report(data, inherited_text(handoffs))
        return 0
    handoff = own(context.product, step, files)
    if handoff is None:
        context.report({"step": step.id, "handoff": None}, "(no handoff)")
        return 0
    data["handoff"] = _row(handoff)
    context.report(data, _own_text(handoff))
    return 0


def _attach(context: CliContext, args: Namespace) -> int:
    source = Path(args.file)
    if not source.is_file():
        raise CliError(f"no such file: {args.file}")
    step = find_step(context.product, args.step)
    name = attach(context.store.files(step.id, MODULE_ID), source.read_bytes(), source.name)
    context.report({"step": step.id, "asset": name}, name)
    return 0


def _assets(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    names = assets(context.store.files(step.id, MODULE_ID))
    context.report({"step": step.id, "assets": names}, "\n".join(names) or "(none)")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    current = read_note(step)
    if current:
        edit = TextEdit(step.id, MODULE_ID, 0, current, "")
        context.apply(EditTextCommand(edit, label="Clear Handoff"))
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id}, f"{step.title}: handoff cleared")
    return 0


def _row(handoff: Handoff) -> dict[str, Any]:
    return {
        "step": handoff.step_id,
        "title": handoff.title,
        "note": handoff.note,
        "scope": handoff.scope,
        "assets": list(handoff.assets),
    }


def _own_text(handoff: Handoff) -> str:
    lines = [handoff.note] if handoff.note else []
    if handoff.scope == "project":
        lines.append("(shared with the whole project)")
    lines.extend(handoff.assets)
    return "\n".join(lines)
