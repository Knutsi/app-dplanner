"""``dplanner note …`` — record what was decided, handed on, deferred or found to differ
from the spec, as the project goes.

``note add`` is what an agent runs when it settles something the plan should remember, or
finishes a step with something the next worker must know — and it is **safe to run
twice**: a title already in the log on the same step is that note, reported and not
duplicated, so a retry after a stale-workspace refusal never leaves two. ``set`` revises
one, ``remove`` drops one, ``list`` prints the log (the standing notes; ``--all`` for the
superseded too), ``show`` prints one in full, ``attach`` puts a file beside it and links it
from the body, and ``index`` prints what a step's briefing carries — the notes addressed to
it in full, and the index of everything else that reaches it. A note that reverses an
earlier one is a new record ``--supersedes`` the old: the history stays, and the index
carries only what stands.

Which step a note was made on is recorded by id and printed by key; the key rule is the
composition root's, handed in as ``key_of`` — the same hand-over every row-printing verb
takes. Qt-free by rule — ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import mimetypes
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path, PurePosixPath

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import body_from, find_project, find_step, project_arg, step_arg
from dplanner.domain.assets import attach
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.modules.notes.log import (
    LABEL_IDS,
    LABELS,
    MODULE_ID,
    REACHES,
    Note,
    check_label,
    find_note,
    next_note_id,
    read_log,
    same_note,
    standing,
    with_note,
    without_note,
    write_log,
)
from dplanner.modules.notes.reach import (
    briefing_blocks,
    full_lines,
    reaching,
    when_where,
)


def commands(*, key_of: Callable[[Step], str]) -> list[CliCommand]:
    def _row(project: Project, record: Note, superseded_by: str) -> dict[str, object]:
        step = project.step(record.step) if record.step else None
        return {
            "note": record.id,
            "label": record.label,
            "title": record.title,
            "body": record.body,
            "made": record.made,
            "step": record.step or None,
            "key": key_of(step) if step is not None else "",
            "for": [_key_or_id(project, step_id) for step_id in record.for_steps],
            "reach": record.reach or None,
            "supersedes": record.supersedes or None,
            "superseded_by": superseded_by or None,
        }

    def _key_or_id(project: Project, step_id: str) -> str:
        step = project.step(step_id)
        return (key_of(step) or step.title) if step is not None else step_id

    def _by(records: list[Note]) -> dict[str, str]:
        return {record.supersedes: record.id for record in records if record.supersedes}

    def _line(project: Project, record: Note, superseded_by: str) -> str:
        facts = when_where(project, record, key_of)
        addressed = ", ".join(_key_or_id(project, s) for s in record.for_steps)
        tail = f"  {facts}" if facts else ""
        tail += f"  for {addressed}" if addressed else ""
        tail += f"  — superseded by {superseded_by}" if superseded_by else ""
        return f"{record.id:<4} {record.label:<12} {record.title}{tail}"

    def _add(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_log(project)
        step_id = _step_id(context, project, args.step)
        existing = same_note(records, args.title, step_id)
        if existing is not None:
            context.report(
                _row(project, existing, _by(records).get(existing.id, ""))
                | {"outcome": "unchanged"},
                f"{existing.id}: already recorded — `dplanner note set {project.title!r} "
                f"{existing.id}` to revise it",
            )
            return 0
        record = Note(
            id=next_note_id(records),
            label=check_label(args.label),
            title=args.title.strip(),
            body=_body(args),
            made=(args.made or date.today().isoformat()),
            step=step_id,
            supersedes=_superseded(records, args.supersedes) if args.supersedes else "",
            reach=args.reach or "",
            for_steps=_for_steps(context, project, args.for_steps),
        )
        _check_day(record.made)
        context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_log([*records, record])))
        context.report(
            _row(project, record, "") | {"outcome": "added"},
            f"{record.id}: {record.label} — {record.title} — recorded",
        )
        return 0

    def _set(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_note(project, args.note)
        records = read_log(project)
        if args.label:
            record = replace(record, label=check_label(args.label))
        if args.title:
            record = replace(record, title=args.title.strip())
        if args.text is not None or args.file:
            record = replace(record, body=_body(args))
        if args.made:
            _check_day(args.made)
            record = replace(record, made=args.made)
        if args.step:
            record = replace(record, step=_step_id(context, project, args.step))
        elif args.no_step:
            record = replace(record, step="")
        if args.for_steps:
            record = replace(record, for_steps=_for_steps(context, project, args.for_steps))
        elif args.for_nobody:
            record = replace(record, for_steps=())
        if args.reach:
            record = replace(record, reach=args.reach)
        if args.supersedes:
            if args.supersedes.strip().lower() == record.id.lower():
                raise CliError(f"{record.id} cannot supersede itself")
            record = replace(record, supersedes=_superseded(records, args.supersedes))
        elif args.clear_supersedes:
            record = replace(record, supersedes="")
        other = same_note(records, record.title, record.step)
        if other is not None and other.id != record.id:
            raise CliError(f"{other.id} is already called {other.title!r} on that step")
        context.apply(
            SetModuleDataCommand(project.id, MODULE_ID, write_log(with_note(records, record)))
        )
        context.report(
            _row(project, record, _by(records).get(record.id, "")) | {"outcome": "updated"},
            f"{record.id}: {record.title} — updated",
        )
        return 0

    def _remove(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_log(project)
        wanted = args.note.strip().lower()
        gone = next((record for record in records if record.id.lower() == wanted), None)
        if gone is None:
            # Already gone is success — a removal must survive a batch run twice.
            context.report({"note": args.note, "outcome": "unchanged"}, "nothing to remove")
            return 0
        context.apply(
            SetModuleDataCommand(project.id, MODULE_ID, write_log(without_note(records, gone.id)))
        )
        context.report(
            {"note": gone.id, "outcome": "removed"}, f"{gone.id}: {gone.title} — removed"
        )
        return 0

    def _list(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_log(project)
        by = _by(records)
        shown = records if args.all else standing(records)
        if args.label:
            shown = [record for record in shown if record.label == check_label(args.label)]
        rows = [_row(project, record, by.get(record.id, "")) for record in shown]
        lines = [_line(project, record, by.get(record.id, "")) for record in shown]
        hidden = len(records) - len(shown) if not args.label else 0
        if hidden:
            lines.append(f"({hidden} superseded — `--all` to list them)")
        context.report(
            {"project": project.id, "notes": rows},
            "\n".join(lines) if lines else "No notes recorded yet.",
        )
        return 0

    def _show(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_note(project, args.note)
        records = read_log(project)
        superseded_by = _by(records).get(record.id, "")
        lines = full_lines(project, record, key_of)
        if record.for_steps:
            lines.append(f"  for {', '.join(_key_or_id(project, s) for s in record.for_steps)}")
        if record.supersedes:
            lines.append(f"  supersedes {record.supersedes}")
        if superseded_by:
            lines.append(f"  superseded by {superseded_by}")
        context.report(_row(project, record, superseded_by), "\n".join(lines))
        return 0

    def _attach(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_note(project, args.note)
        source = Path(args.file)
        if not source.is_file():
            raise CliError(f"no such file: {args.file}")
        area = context.store.files(project.id, MODULE_ID)
        name = attach(area, source.read_bytes(), source.name)
        link = _link(source.name, name)
        if name not in record.body:
            record = replace(record, body=(record.body.rstrip() + "\n\n" + link).strip())
            records = read_log(project)
            context.apply(
                SetModuleDataCommand(project.id, MODULE_ID, write_log(with_note(records, record)))
            )
        context.report(
            {"note": record.id, "asset": name, "path": str(area.absolute(name))},
            f"{record.id}: {link}",
        )
        return 0

    def _index(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        project = context.library.project_of(step.id)
        index = reaching(context.library, step)
        by = _by(read_log(project))
        blocks = briefing_blocks(project, index, key_of)
        text = "\n\n".join(f"## {block.heading}\n\n{block.body}" for block in blocks)
        context.report(
            {
                "step": step.id,
                "for_this_step": [_row(project, n, by.get(n.id, "")) for n in index.addressed],
                "index": [_row(project, n, by.get(n.id, "")) for n in index.listed],
            },
            text or "No notes reach this step yet.",
        )
        return 0

    labels = "; ".join(f"{label.id}: {label.meaning}" for label in LABELS)
    return [
        CliCommand(
            path=("note", "add"),
            summary="Record a note — a decision, a handoff, a spec change, something deferred "
            "— with its label, on which step, and for whom. A title already on that step "
            "is that note; safe to run twice.",
            configure=lambda parser: _configure_add(parser, labels),
            run=_add,
            examples=(
                "dplanner note add discovery decision 'Keep the index in SQLite' --step S7 "
                "--text 'Postgres would need an operator; the index is read-mostly.'",
                "dplanner note add discovery handoff 'Auth middleware is stubbed' --step S7 "
                "--for S9 --file -",
                "dplanner note add discovery decision 'Move the index to Postgres' "
                "--supersedes N3 --file -",
            ),
        ),
        CliCommand(
            path=("note", "set"),
            summary="Revise a note's label, title, body, day, step, addressees, reach or what "
            "it supersedes.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner note set discovery N3 --file reasoning.md --for S9 S12",),
        ),
        CliCommand(
            path=("note", "remove"),
            summary="Drop a note from the log; already gone is success.",
            configure=_configure_named,
            run=_remove,
            examples=("dplanner note remove discovery N3",),
        ),
        CliCommand(
            path=("note", "list"),
            summary="The notes in force, oldest first; --label filters, --all includes the "
            "superseded.",
            configure=_configure_list,
            run=_list,
            examples=(
                "dplanner note list discovery",
                "dplanner note list discovery --label decision --all",
            ),
        ),
        CliCommand(
            path=("note", "show"),
            summary="One note in full: its body, when and where it was made, who it is for.",
            configure=_configure_named,
            run=_show,
            examples=("dplanner note show discovery N3",),
        ),
        CliCommand(
            path=("note", "attach"),
            summary="Copy a file in beside the project's notes and link it from the note.",
            configure=_configure_attach,
            run=_attach,
            examples=("dplanner note attach discovery N3 diagram.png",),
        ),
        CliCommand(
            path=("note", "index"),
            summary="What a step's briefing carries: the notes addressed to it in full, and "
            "the index of everything else that reaches it.",
            configure=step_arg,
            run=_index,
            examples=("dplanner note index S9",),
        ),
    ]


def _configure_body(parser: ArgumentParser) -> None:
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--text", help="the body, inline")
    body.add_argument("--file", help="a markdown file holding the body, or - for stdin")


def _configure_add(parser: ArgumentParser, labels: str) -> None:
    project_arg(parser)
    parser.add_argument("label", help=f"what the note is — {labels}")
    parser.add_argument("title", help="the note in one line")
    _configure_body(parser)
    parser.add_argument("--step", help="the step it was made on (S7, id, or title)")
    parser.add_argument(
        "--for",
        dest="for_steps",
        nargs="+",
        metavar="STEP",
        help="steps whose briefing should carry this note in full",
    )
    parser.add_argument("--supersedes", metavar="N", help="the earlier note this replaces")
    parser.add_argument(
        "--reach",
        choices=REACHES,
        help="who sees it in their index: every step, or only the steps after --step "
        "(the default for a handoff)",
    )
    parser.add_argument("--made", metavar="YYYY-MM-DD", help="the day it was made (default today)")


def _configure_set(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("note", help="the note's id (N3) or part of its title")
    parser.add_argument("--label", choices=LABEL_IDS, help="what the note is")
    parser.add_argument("--title", help="the note in one line")
    _configure_body(parser)
    parser.add_argument("--made", metavar="YYYY-MM-DD", help="the day it was made")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--step", help="the step it was made on")
    which.add_argument("--no-step", action="store_true", help="a project-wide note")
    whom = parser.add_mutually_exclusive_group()
    whom.add_argument(
        "--for", dest="for_steps", nargs="+", metavar="STEP", help="the steps it is for"
    )
    whom.add_argument("--for-nobody", action="store_true", help="addressed to no step")
    parser.add_argument("--reach", choices=REACHES, help="who sees it in their index")
    link = parser.add_mutually_exclusive_group()
    link.add_argument("--supersedes", metavar="N", help="the earlier note this replaces")
    link.add_argument("--clear-supersedes", action="store_true", help="it replaces nothing")


def _configure_named(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("note", help="the note's id (N3) or part of its title")


def _configure_list(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--label", choices=LABEL_IDS, help="only notes wearing this label")
    parser.add_argument("--all", action="store_true", help="include superseded notes")


def _configure_attach(parser: ArgumentParser) -> None:
    _configure_named(parser)
    parser.add_argument("file", help="the file to copy in beside the project's notes")


def _body(args: Namespace) -> str:
    if args.file:
        return body_from(args.file)
    return args.text or ""


def _step_id(context: CliContext, project: Project, needle: str | None) -> str:
    if not needle:
        return ""
    step = find_step(context.library, needle, project)
    if context.library.project_of(step.id).id != project.id:
        raise CliError(f"{needle!r} is a step of another project")
    return step.id


def _for_steps(context: CliContext, project: Project, needles: list[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_step_id(context, project, needle) for needle in needles or []))


def _superseded(records: list[Note], needle: str) -> str:
    wanted = needle.strip().lower()
    found = next((record for record in records if record.id.lower() == wanted), None)
    if found is None:
        raise CliError(f"no note {needle!r} to supersede — see `dplanner note list --all`")
    return found.id


def _check_day(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise CliError(f"--made is a date, YYYY-MM-DD: {value!r}") from error


def _link(filename: str, name: str) -> str:
    """The markdown that references an attachment: an image shows, anything else is a
    link — the same two forms the prose editor types on a paste."""
    mime = mimetypes.guess_type(filename)[0] or ""
    if mime.startswith("image/"):
        return f"![{PurePosixPath(filename).stem}]({name})"
    return f"[{filename}]({name})"
