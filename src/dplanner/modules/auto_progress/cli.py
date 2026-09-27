"""``dplanner auto-progress …`` — the links a step collects its sources' work across.

``set`` turns one link on or off, and turning on a link that does not exist yet makes it:
one command, behind the topology gate, because saying "this step starts when those are
ready for review" is a decision about how the graph flows. ``list`` names every step that
collects something. ``step add --after A B --auto-progress`` flags the links it just made.

Nothing here refuses a flag on a step that is not an agent step: ``auto-progress.waiter``
lint names it, so a plan reshaped in several calls is never in the way halfway.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step, project_arg, project_of_step
from dplanner.domain.commands import CompositeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.progression import phrase
from dplanner.domain.store import FilesFor
from dplanner.modules.auto_progress.aspect import (
    MODULE_ID,
    progresses,
    sources,
    with_sources,
    write,
)


def commands(
    *,
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    key_of: Callable[[Step], str],
) -> list[CliCommand]:
    """``is_agent`` and ``status_for`` are other modules' readers and ``key_of`` the root's
    rule, handed over so this file imports none of them."""

    def run_set(context: CliContext, args: Namespace) -> int:
        return _set(context, args, is_agent, key_of)

    def run_list(context: CliContext, args: Namespace) -> int:
        return _list(context, args, status_for, key_of)

    return [
        CliCommand(
            path=("auto-progress", "set"),
            summary="Let a step start once a step it waits on is ready for review, and "
            "land that work itself; `on` makes the link when it is missing.",
            configure=_configure_set,
            run=run_set,
            examples=(
                "dplanner auto-progress set 'Merge round 1' S25 on",
                "dplanner auto-progress set 'Merge round 1' S25 off",
            ),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("auto-progress", "list"),
            summary="Every step that collects other steps' work, and what it collects.",
            configure=project_arg,
            run=run_list,
            examples=("dplanner auto-progress list 'My project'",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="the step that waits and collects")
    parser.add_argument("source", help="the step it collects — a step it waits on")
    parser.add_argument("state", choices=("on", "off"), help="on auto-progresses; off is plain")


def _set(
    context: CliContext,
    args: Namespace,
    is_agent: Callable[[Step], bool],
    key_of: Callable[[Step], str],
) -> int:
    library = context.library
    waiter = find_step(library, args.step, context.current)
    source = find_step(library, args.source, library.project_of(waiter.id))
    on = args.state == "on"
    name, of = _named(waiter, key_of), _named(source, key_of)
    data = {"step": waiter.id, "source": source.id, "auto_progress": on}
    if progresses(waiter, source) == on:
        # Already so is success — state-setting verbs must survive batches.
        context.report(data, f"{name} ← {of}: already {'auto-progress' if on else 'plain'}")
        return 0
    entry = with_sources(waiter, [source.id], on)
    linked = source.id in waiter.edges.get("requires", [])
    if on and not linked:
        refusal = library.link_refusal(waiter.id, "requires", source.id)
        if refusal:
            raise CliError(f"cannot link {name} to {of}: {refusal}")
        targets = [*waiter.edges.get("requires", []), source.id]
        context.apply(
            CompositeCommand(
                "Auto-progress",
                [
                    SetEdgesCommand(waiter.id, "requires", targets),
                    SetModuleDataCommand(waiter.id, MODULE_ID, entry),
                ],
            )
        )
    else:
        context.apply(SetModuleDataCommand(waiter.id, MODULE_ID, entry))
    if not on:
        context.report(data, f"{name} ← {of}: plain — {name} starts once {of} is done")
        return 0
    text = f"{name} ← {of}: auto-progress — {name} may start once {of} is ready for review"
    if not is_agent(waiter):
        text += "\n  " + _not_an_agent(waiter, key_of)
    context.report(data, text)
    return 0


def _list(
    context: CliContext,
    args: Namespace,
    status_for: Callable[[Step], str],
    key_of: Callable[[Step], str],
) -> int:
    library = context.library
    project = find_project(library, args.project)
    rows, lines = [], []
    for waiter in project.steps:
        collected = sources(library, waiter)
        if not collected:
            continue
        rows.append(
            {
                "step": waiter.id,
                "key": key_of(waiter),
                "title": waiter.title,
                "collects": [
                    {
                        "step": source.id,
                        "key": key_of(source),
                        "title": source.title,
                        "status": status_for(source),
                    }
                    for source in collected
                ],
            }
        )
        lines.append(_named(waiter, key_of) + " collects:")
        lines += [
            f"  {_named(source, key_of)} — {phrase(status_for(source))}" for source in collected
        ]
    context.report({"collectors": rows}, "\n".join(lines) or "No step collects another's work.")
    return 0


def step_author() -> StepAuthor:
    """``step add``'s ``--auto-progress``: every ``--after`` link collects its source.

    The links exist by the time the authors run, so this only flags them; without an
    ``--after`` there is nothing to flag, and the whole ``step add`` is refused.
    """

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--auto-progress",
            action="store_true",
            help="the step may start once every --after step is ready for review, and lands "
            "their work itself",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if not args.auto_progress:
            return None
        after = context.library.requires(step.id)
        if not after:
            raise CliError("--auto-progress flags the --after links — name at least one")
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(s.id for s in after)))
        return StepAuthored(
            {"auto_progress": [s.id for s in after]},
            f"auto-progress from {len(after)} step{'' if len(after) == 1 else 's'}",
        )

    return StepAuthor(configure, author)


def lint_checks(
    *, is_agent: Callable[[Step], bool], key_of: Callable[[Step], str]
) -> list[LintCheck]:
    def waiter(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A step collects work only if an agent picks it up: nobody else reads its
        briefing, and a person starting it early is what a plain link is for."""
        found = []
        for step in project.steps:
            collected = sources(library, step)
            if collected and not is_agent(step):
                first = key_of(collected[0]) or repr(collected[0].title)
                found.append(
                    LintFinding(
                        check="auto-progress.waiter",
                        subject_id=step.id,
                        subject=step.title,
                        message=f"collects {_keys(collected, key_of)} over auto-progress "
                        "links, but is not an agent step, so no agent will pick it up — "
                        f"`dplanner agent on {_ref(step, key_of)}`, or `dplanner "
                        f"auto-progress set {_ref(step, key_of)} {first} off`",
                    )
                )
        return found

    return [waiter]


def _not_an_agent(step: Step, key_of: Callable[[Step], str]) -> str:
    return (
        f"{_named(step, key_of)} is not an agent step, so no agent will pick it up: "
        f"`dplanner agent on {_ref(step, key_of)}`"
    )


def _named(step: Step, key_of: Callable[[Step], str]) -> str:
    return f"{key_of(step)} {step.title}".strip()


def _ref(step: Step, key_of: Callable[[Step], str]) -> str:
    key = key_of(step)
    return key if key else repr(step.title)


def _keys(steps: list[Step], key_of: Callable[[Step], str]) -> str:
    return ", ".join(key_of(step) or repr(step.title) for step in steps)
