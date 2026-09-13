"""``dplanner docs …`` and ``dplanner compiled …`` — the fragments a step contributes, and
the document a collector makes of them.

**This is where the compiling happens, whoever asked for it.** There is no ``docs compile``
verb and none is wanted: an agent driving this CLI *is* the compiler, and the window's
*Compile with Agent…* launches one with a briefing that ends in these very verbs. The loop is
three of them:

    dplanner docs status --json               what needs compiling, and why
    dplanner docs collect 'Auth'              the fragments to work from
    dplanner compiled set 'Auth' --file out.md   lands it, stamped current

``compiled set`` stamping the digest is what closes it: the document it just wrote reads as
up to date, and stays that way until somebody edits a fragment behind it.

The collector kinds arrive as an argument from the composition root — the same hand-over
``progression_cli.commands(status_for=…)`` uses — so nothing here learns what a feature is.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import time
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.assets import step_asset_commands
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_project, find_step, step_arg
from dplanner.domain.assets import assets, image_references
from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    EditTextCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Node, Project, Step, TextEdit
from dplanner.domain.scope import ScopeKind
from dplanner.domain.shelf import turn_off
from dplanner.domain.store import FilesFor
from dplanner.modules.docs.aspect import (
    COMPILED_ID,
    MODULE_ID,
    enabled,
    read,
    read_compiled,
    write_stamp,
    write_state,
)
from dplanner.modules.docs.collect import (
    as_markdown,
    collectors,
    compiled_state,
    digest,
    sources_for,
    state_of,
)

# What each state means for somebody reading `docs status`, and the verb that answers it.
_ADVICE = {
    "never": "not compiled yet — `dplanner docs collect {title!r}`, write it, "
    "then `dplanner compiled set {title!r} --file <out>`",
    "stale": "out of date — a fragment behind it changed; recompile with "
    "`dplanner docs collect {title!r}` then `dplanner compiled set {title!r} --file <out>`",
    "current": "up to date",
}


def lint_checks(*, kinds: Sequence[ScopeKind] = ()) -> list[LintCheck]:
    def compiled_stale(product: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A document its own fragments have outgrown. Never-compiled is not reported: a
        collector nobody has written up yet is a decision, not a gap."""
        return [
            LintFinding(
                check="docs.compiled-stale",
                subject_id=step.id,
                subject=step.title,
                message="its compiled documentation is older than the fragments behind it — "
                f"`dplanner docs collect '{step.title}'`, then `dplanner compiled set "
                f"'{step.title}' --file <out>`",
            )
            for step in collectors(kinds, project)
            if state_of(kinds, product, project, step.id) == "stale"
        ]

    def missing_images(_product: Library, project: Project, files: FilesFor) -> list[LintFinding]:
        """Documentation embedding ![](assets/…) that names no file beside the step."""
        findings = []
        for step in project.steps:
            references = image_references(read(step))
            if not references:
                continue
            try:
                known = set(assets(files(step.id, MODULE_ID)))
            except KeyError:
                known = set()  # A never-flushed step has no files yet.
            findings += [
                LintFinding(
                    check="docs.image-missing",
                    subject_id=step.id,
                    subject=step.title,
                    message=f"its documentation references ![]({reference}) but no such "
                    f"file is beside the step — `dplanner docs attach "
                    f"'{step.title}' <file>` and use the printed path",
                )
                for reference in references
                if reference not in known
            ]
        return findings

    return [compiled_stale, missing_images]


def commands(*, kinds: Sequence[ScopeKind] = ()) -> list[CliCommand]:
    def collect(context: CliContext, args: Namespace) -> int:
        return _collect(context, args, kinds)

    def status(context: CliContext, args: Namespace) -> int:
        return _status(context, args, kinds)

    def compiled_set(context: CliContext, args: Namespace) -> int:
        return _compiled_set(context, args, kinds)

    return [
        CliCommand(
            path=("docs", "set"),
            summary="Replace this step's documentation fragment, from a file or stdin.",
            configure=_configure_fragment_set,
            run=_set,
            examples=(
                "dplanner docs set 'Write the parser' --file notes.md",
                "echo '## Query syntax' | dplanner docs set 'Write the parser' --file -",
                "dplanner docs set --for-project --file house-style.md",
            ),
        ),
        CliCommand(
            path=("docs", "clear"),
            summary="This step documents nothing. Drops its fragment and its mark together.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner docs clear 'Write the parser'",),
        ),
        CliCommand(
            path=("docs", "show"),
            summary="Print one step's documentation fragment.",
            configure=_project_target,
            run=_show,
            examples=(
                "dplanner docs show 'Write the parser'",
                "dplanner docs show --for-project",
            ),
        ),
        CliCommand(
            path=("docs", "collect"),
            summary="Every fragment a feature or milestone gathers, as one markdown document.",
            configure=step_arg,
            run=collect,
            examples=(
                "dplanner docs collect Auth",
                "dplanner docs collect 'Ship the beta' --json",
            ),
        ),
        CliCommand(
            path=("docs", "status"),
            summary="Every feature and milestone: whether its documentation needs compiling.",
            configure=_configure_status,
            run=status,
            examples=("dplanner docs status", "dplanner docs status search --json"),
        ),
        # A second noun for the *document*, the way `test` and `test-run` are two. `docs set`
        # is already the fragment, and one verb writing either would be a flag nobody could
        # read at a glance.
        CliCommand(
            path=("compiled", "set"),
            summary="Store a collector's documentation and stamp it as up to date.",
            configure=_configure_set,
            run=compiled_set,
            examples=(
                "dplanner compiled set Auth --file signing-in.md",
                "dplanner docs collect Auth | your-model | dplanner compiled set Auth --file -",
            ),
        ),
        CliCommand(
            path=("compiled", "show"),
            summary="Print a collector's documentation.",
            configure=step_arg,
            run=_compiled_show,
            examples=("dplanner compiled show Auth",),
        ),
        CliCommand(
            path=("compiled", "clear"),
            summary="Drop a collector's documentation and its stamp together.",
            configure=step_arg,
            run=_compiled_clear,
            examples=("dplanner compiled clear Auth",),
        ),
        *step_asset_commands(
            "docs",
            MODULE_ID,
            file_help="the image to copy in beside the step",
            attach_summary="Add an image beside a step's documentation fragment and print"
            " the path.",
            assets_summary="List the images a step's documentation fragment keeps.",
            example_step="'Write the parser'",
            attached_text=lambda name: f"{name}\nReference it from the markdown as ![]({name})",
        ),
    ]


def _configure_status(parser: ArgumentParser) -> None:
    parser.add_argument(
        "project",
        nargs="?",
        help="project id, folder name, or part of its title; omitted covers the current one",
    )


def _project_target(parser: ArgumentParser) -> None:
    """A step, or the project instead. The compilation instructions live beside the project
    (``FORMAT.md``), and a briefing carries them, so an agent compiling without a window must
    be able to read and write them too — ``dplanner agent set --for-project``'s shape."""
    parser.add_argument("step", nargs="?", help="step id, folder name, or part of its title")
    parser.add_argument(
        "--for-project",
        dest="for_project",
        nargs="?",
        const="",
        default=None,
        metavar="PROJECT",
        help="the project instead: its compilation instructions, which open every compile"
        " briefing (defaults to the current project)",
    )


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _configure_fragment_set(parser: ArgumentParser) -> None:
    _project_target(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _step(context: CliContext, needle: str) -> Step:
    return find_step(context.library, needle)


def _target(context: CliContext, args: Namespace) -> Node:
    """The step or the project the verb addresses — exactly one of the two."""
    if (args.step is None) == (args.for_project is None):
        raise CliError("name a step, or --for-project, but not both")
    if args.for_project is not None:
        if args.for_project:
            return find_project(context.library, args.for_project)
        return context.project
    return find_step(context.library, args.step, context.current)


# -- the fragments -----------------------------------------------------------------------------


def _set(context: CliContext, args: Namespace) -> int:
    """Write the prose and the mark together, so a step written to by an agent shows its
    tab in a window without anybody also having to toggle the aspect on.

    With ``--for-project`` it writes the project's compilation instructions instead, which
    carry no mark: a project has no Type toggle, and nothing gathers a project.
    """
    body = body_from(args.file)
    node = _target(context, args)
    label = "Set Compilation Instructions" if isinstance(node, Project) else "Set Docs"
    # One positioned edit over the whole document, labelled so a burst of GUI typing and a
    # whole-file replacement never coalesce into one undo step.
    written: list[Command] = [
        EditTextCommand(TextEdit(node.id, MODULE_ID, 0, read(node), body), label=label)
    ]
    if isinstance(node, Step) and not node.module_data.get(MODULE_ID):
        written.append(SetModuleDataCommand(node.id, MODULE_ID, write_state(True), label=label))
    context.apply(written[0] if len(written) == 1 else CompositeCommand(label, written))
    named = getattr(node, "title", "") or "the project"
    context.report({"step": node.id, "characters": len(body)}, f"{named}: {len(body)} characters")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    """The CLI half of the GUI's Type ▸ Docs toggle: the fragment goes to the shelf."""
    step = _step(context, args.step)
    message = f"{step.title}: documents nothing"
    if not enabled(step):
        # Already clear is success, and writes nothing.
        context.report({"step": step.id}, message)
        return 0
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Docs"))
    context.report({"step": step.id}, message)
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    node = _target(context, args)
    body = read(node)
    empty = "(no compilation instructions)" if isinstance(node, Project) else "(documents nothing)"
    context.report({"step": node.id, "markdown": body}, body or empty)
    return 0


def _collect(context: CliContext, args: Namespace, kinds: Sequence[ScopeKind]) -> int:
    """What this step would compile from — the agent's input, and the tab's Fragments pane."""
    step = _step(context, args.step)
    # The step names its project, so this reads the same with or without a current one.
    project = context.library.project_of(step.id)
    found = sources_for(kinds, context.library, project, step.id)
    body = as_markdown(found)
    context.report(
        {
            "step": step.id,
            "digest": digest(found),
            "steps": [
                {"id": source.step.id, "title": source.step.title, "compiled": source.compiled}
                for source in found
            ],
            "markdown": body,
        },
        body or f"{step.title}: nothing behind it carries a documentation fragment",
    )
    return 0


# -- the compiled documents --------------------------------------------------------------------


def _status(context: CliContext, args: Namespace, kinds: Sequence[ScopeKind]) -> int:
    """Where every collector's documentation stands, and the verb that moves it on."""
    library = context.library
    if args.project:
        projects = [find_project(library, args.project)]
    elif context.current is not None:
        projects = [context.current]
    else:
        projects = list(library.projects)
    rows = []
    for project in projects:
        for step in collectors(kinds, project):
            found = sources_for(kinds, library, project, step.id)
            state = compiled_state(step, found)
            rows.append(
                {
                    "project": project.id,
                    "step": step.id,
                    "title": step.title,
                    "state": state,
                    "sources": len(found),
                    "message": _ADVICE[state].format(title=step.title),
                }
            )
    width = max((len(str(row["title"])) for row in rows), default=0)
    text = "\n".join(f"{row['title']:<{width}}  {row['state']:<9}{row['message']}" for row in rows)
    context.report({"collectors": rows}, text or "(no features or milestones to document)")
    return 0


def _compiled_set(context: CliContext, args: Namespace, kinds: Sequence[ScopeKind]) -> int:
    """Land a document and stamp what it was made of, so it reads as up to date.

    The stamp is the whole point of the verb: without it the next ``docs status`` would call
    a document somebody just wrote out of date.
    """
    body = body_from(args.file)
    step = _step(context, args.step)
    project = context.library.project_of(step.id)
    found = sources_for(kinds, context.library, project, step.id)
    context.apply(
        CompositeCommand(
            "Set Compiled Docs",
            [
                EditTextCommand(
                    TextEdit(step.id, COMPILED_ID, 0, read_compiled(step), body),
                    label="Set Compiled Docs",
                ),
                SetModuleDataCommand(
                    step.id,
                    COMPILED_ID,
                    write_stamp(digest(found), time.time(), len(found)),
                    label="Set Compiled Docs",
                ),
            ],
        )
    )
    context.report(
        {"step": step.id, "characters": len(body), "sources": len(found)},
        f"{step.title}: {len(body)} characters, compiled from {len(found)} sources",
    )
    return 0


def _compiled_show(context: CliContext, args: Namespace) -> int:
    step = _step(context, args.step)
    body = read_compiled(step)
    context.report({"step": step.id, "markdown": body}, body or "(nothing compiled yet)")
    return 0


def _compiled_clear(context: CliContext, args: Namespace) -> int:
    step = _step(context, args.step)
    message = f"{step.title}: nothing compiled"
    if not read_compiled(step) and not step.module_data.get(COMPILED_ID):
        context.report({"step": step.id}, message)
        return 0
    context.apply(_drop(step, COMPILED_ID, read_compiled(step), "Clear Compiled Docs"))
    context.report({"step": step.id}, message)
    return 0


def _drop(step: Step, module_id: str, prose: str, label: str) -> Command:
    """Prose and entry in one command, so one undo restores both."""
    cleared: list[Command] = [SetModuleDataCommand(step.id, module_id, {}, label=label)]
    if prose:
        cleared.insert(0, EditTextCommand(TextEdit(step.id, module_id, 0, prose, ""), label=label))
    return cleared[0] if len(cleared) == 1 else CompositeCommand(label, cleared)
