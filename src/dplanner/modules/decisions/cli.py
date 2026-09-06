"""``dplanner decision …`` — record what was decided, and why, as the project goes.

``decision add`` is what an agent runs when it settles something the plan should
remember — a trade-off, a convention, an option rejected — and it is **safe to run twice**:
a title already in the log is that decision, reported and not duplicated, so a retry after
a stale-workspace refusal never leaves two. ``set`` revises one, ``remove`` drops one,
``list`` prints the log (the standing decisions; ``--all`` for the superseded too) and
``show`` prints one in full. A decision that reverses an earlier one is a new record
``--supersedes`` the old: the history stays, and the briefing carries only what stands.

Which step a decision was made on is recorded by id and printed by key; the key rule is
the composition root's, handed in as ``key_of`` — the same hand-over every row-printing
verb takes. Qt-free by rule — ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from datetime import date

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import body_from, find_project, find_step, project_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.domain.schedule import format_date
from dplanner.modules.decisions.log import (
    MODULE_ID,
    Decision,
    find_decision,
    next_decision_id,
    read_log,
    same_title,
    standing,
    with_decision,
    without_decision,
    write_log,
)


def commands(*, key_of: Callable[[Step], str]) -> list[CliCommand]:
    def _row(project: Project, record: Decision, superseded_by: str) -> dict[str, object]:
        step = project.step(record.step) if record.step else None
        return {
            "decision": record.id,
            "title": record.title,
            "body": record.body,
            "made": record.made,
            "step": record.step or None,
            "key": key_of(step) if step is not None else "",
            "supersedes": record.supersedes or None,
            "superseded_by": superseded_by or None,
        }

    def _by(records: list[Decision]) -> dict[str, str]:
        return {record.supersedes: record.id for record in records if record.supersedes}

    def _line(project: Project, record: Decision, superseded_by: str) -> str:
        step = project.step(record.step) if record.step else None
        where = f"  on {key_of(step) or step.title}" if step is not None else ""
        when = f"  {_day(record.made)}" if record.made else ""
        note = f"  — superseded by {superseded_by}" if superseded_by else ""
        return f"{record.id:<4} {record.title}{when}{where}{note}"

    def _add(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_log(project)
        existing = same_title(records, args.title)
        if existing is not None:
            context.report(
                _row(project, existing, _by(records).get(existing.id, ""))
                | {"outcome": "unchanged"},
                f"{existing.id}: already recorded — `dplanner decision set {project.title!r} "
                f"{existing.id}` to revise it",
            )
            return 0
        record = Decision(
            id=next_decision_id(records),
            title=args.title.strip(),
            body=_body(args),
            made=(args.made or date.today().isoformat()),
            step=_step_id(context, args.step),
            supersedes=_superseded(records, args.supersedes) if args.supersedes else "",
        )
        _check_day(record.made)
        context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_log([*records, record])))
        context.report(
            _row(project, record, "") | {"outcome": "added"},
            f"{record.id}: {record.title} — recorded",
        )
        return 0

    def _set(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_decision(project, args.decision)
        records = read_log(project)
        if args.title:
            other = same_title(records, args.title)
            if other is not None and other.id != record.id:
                raise CliError(f"{other.id} is already called {other.title!r}")
            record = replace(record, title=args.title.strip())
        if args.text is not None or args.file:
            record = replace(record, body=_body(args))
        if args.made:
            _check_day(args.made)
            record = replace(record, made=args.made)
        if args.step:
            record = replace(record, step=_step_id(context, args.step))
        elif args.no_step:
            record = replace(record, step="")
        if args.supersedes:
            if args.supersedes.strip().lower() == record.id.lower():
                raise CliError(f"{record.id} cannot supersede itself")
            record = replace(record, supersedes=_superseded(records, args.supersedes))
        elif args.clear_supersedes:
            record = replace(record, supersedes="")
        context.apply(
            SetModuleDataCommand(project.id, MODULE_ID, write_log(with_decision(records, record)))
        )
        context.report(
            _row(project, record, _by(records).get(record.id, "")) | {"outcome": "updated"},
            f"{record.id}: {record.title} — updated",
        )
        return 0

    def _remove(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_log(project)
        wanted = args.decision.strip().lower()
        gone = next((record for record in records if record.id.lower() == wanted), None)
        if gone is None:
            # Already gone is success — a removal must survive a batch run twice.
            context.report({"decision": args.decision, "outcome": "unchanged"}, "nothing to remove")
            return 0
        kept = [
            replace(record, supersedes="") if record.supersedes == gone.id else record
            for record in without_decision(records, gone.id)
        ]
        context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_log(kept)))
        context.report(
            {"decision": gone.id, "outcome": "removed"}, f"{gone.id}: {gone.title} — removed"
        )
        return 0

    def _list(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_log(project)
        by = _by(records)
        shown = records if args.all else standing(records)
        rows = [_row(project, record, by.get(record.id, "")) for record in shown]
        lines = [_line(project, record, by.get(record.id, "")) for record in shown]
        hidden = len(records) - len(shown)
        if hidden:
            lines.append(f"({hidden} superseded — `--all` to list them)")
        context.report(
            {"project": project.id, "decisions": rows},
            "\n".join(lines) if lines else "No decisions recorded yet.",
        )
        return 0

    def _show(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_decision(project, args.decision)
        records = read_log(project)
        superseded_by = _by(records).get(record.id, "")
        lines = [_line(project, record, superseded_by)]
        if record.supersedes:
            lines.append(f"supersedes {record.supersedes}")
        if record.body.strip():
            lines += ["", record.body.rstrip()]
        context.report(_row(project, record, superseded_by), "\n".join(lines))
        return 0

    return [
        CliCommand(
            path=("decision", "add"),
            summary="Record a decision the project made — what, why, on which step. "
            "A title already in the log is that decision; safe to run twice.",
            configure=_configure_add,
            run=_add,
            examples=(
                "dplanner decision add discovery 'Keep the index in SQLite' --step S7 "
                "--text 'Postgres would need an operator; the index is read-mostly.'",
                "dplanner decision add discovery 'Move the index to Postgres' --supersedes D3 "
                "--file -",
            ),
        ),
        CliCommand(
            path=("decision", "set"),
            summary="Revise a decision's title, reasoning, day, step or what it supersedes.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner decision set discovery D3 --file reasoning.md",),
        ),
        CliCommand(
            path=("decision", "remove"),
            summary="Drop a decision from the log; already gone is success.",
            configure=_configure_named,
            run=_remove,
            examples=("dplanner decision remove discovery D3",),
        ),
        CliCommand(
            path=("decision", "list"),
            summary="The decisions in force, oldest first; --all includes the superseded.",
            configure=_configure_list,
            run=_list,
            examples=("dplanner decision list discovery", "dplanner decision list discovery --all"),
        ),
        CliCommand(
            path=("decision", "show"),
            summary="One decision in full: its reasoning, when and where it was made.",
            configure=_configure_named,
            run=_show,
            examples=("dplanner decision show discovery D3",),
        ),
    ]


def _configure_body(parser: ArgumentParser) -> None:
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--text", help="the reasoning, inline")
    body.add_argument("--file", help="a markdown file holding the reasoning, or - for stdin")


def _configure_add(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="what was decided, in one line")
    _configure_body(parser)
    parser.add_argument("--step", help="the step it was decided on (S7, id, or title)")
    parser.add_argument("--supersedes", metavar="D", help="the earlier decision this replaces")
    parser.add_argument("--made", metavar="YYYY-MM-DD", help="the day it was taken (default today)")


def _configure_set(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("decision", help="the decision's id (D3) or part of its title")
    parser.add_argument("--title", help="what was decided, in one line")
    _configure_body(parser)
    parser.add_argument("--made", metavar="YYYY-MM-DD", help="the day it was taken")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--step", help="the step it was decided on")
    which.add_argument("--no-step", action="store_true", help="a project-wide decision")
    link = parser.add_mutually_exclusive_group()
    link.add_argument("--supersedes", metavar="D", help="the earlier decision this replaces")
    link.add_argument("--clear-supersedes", action="store_true", help="it replaces nothing")


def _configure_named(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("decision", help="the decision's id (D3) or part of its title")


def _configure_list(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--all", action="store_true", help="include superseded decisions")


def _body(args: Namespace) -> str:
    if args.file:
        return body_from(args.file)
    return args.text or ""


def _step_id(context: CliContext, needle: str | None) -> str:
    if not needle:
        return ""
    return find_step(context.library, needle, context.current).id


def _superseded(records: list[Decision], needle: str) -> str:
    wanted = needle.strip().lower()
    found = next((record for record in records if record.id.lower() == wanted), None)
    if found is None:
        raise CliError(f"no decision {needle!r} to supersede — see `dplanner decision list --all`")
    return found.id


def _check_day(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise CliError(f"--made is a date, YYYY-MM-DD: {value!r}") from error


def _day(made: str) -> str:
    try:
        return format_date(date.fromisoformat(made))
    except ValueError:
        return made
