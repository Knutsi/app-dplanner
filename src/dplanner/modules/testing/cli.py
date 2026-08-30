"""``dplanner test …`` and ``dplanner test-run …`` — the tests, and the runs over them.

Two nouns because they are two things: ``test`` writes what a step must keep passing,
``test-run`` records one occasion of executing them. The hyphenated noun follows
``agent-state``; the CLI's grammar is always exactly ``dplanner <noun> <verb>``.

An agent is expected to be the one *executing* tests and reporting back, so ``test-run
mark`` is the verb this file is really shaped around: terse, idempotent, and safe to run in
a batch where some of the marks are already what they should be.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.assets import step_asset_commands
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_project, find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    MODULE_ID,
    Test,
    covered,
    next_test_id,
    project_tests,
    read,
    replace,
    write,
)

_STATUS_GLYPH = {"ok": "✓", "failed": "✗", "skipped": "-", "pending": " "}


# -- finding a test -------------------------------------------------------------------


def test_arg(parser: ArgumentParser) -> None:
    """The positional a test verb takes, resolved by :func:`find_test`."""
    parser.add_argument("test", help="test id (T100), or part of its title")


def find_test(
    library: Library, needle: str, within: Project | None = None
) -> tuple[Project, Step, Test]:
    """A test by id, or by a unique part of its title, and the project it belongs to.

    ``find_step``'s rule one level down: a needle the current project can answer is answered
    there, and only one it cannot falls back to the whole library. Ambiguity is refused
    rather than resolved to the first match — acting on one of two things somebody might
    have meant is the failure they cannot see.
    """
    if within is not None and _matches_a_test(within, needle):
        return _find_test_in([within], needle)
    return _find_test_in(library.projects, needle)


def _matches_a_test(project: Project, needle: str) -> bool:
    lowered = needle.lower()
    return any(
        test.id.lower() == lowered or lowered in test.title.lower()
        for _step, test in project_tests(project, archived=True)
    )


def _find_test_in(projects: Sequence[Project], needle: str) -> tuple[Project, Step, Test]:
    pairs = [
        (project, step, test)
        for project in projects
        for step, test in project_tests(project, archived=True)
    ]
    exact = [found for found in pairs if found[2].id.lower() == needle.lower()]
    if exact:
        return exact[0]
    lowered = needle.lower()
    partial = [found for found in pairs if lowered in found[2].title.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise CliError(f"no test matching {needle!r}")
    names = ", ".join(sorted(f"{test.title} ({test.id})" for _p, _s, test in partial))
    raise CliError(f"{needle!r} matches several tests — use an id: {names}")


def _scoped(context: CliContext, named: str | None) -> Project:
    """The project a project-wide verb acts on: the one named, else the current one."""
    return find_project(context.library, named) if named else context.project


def _save(context: CliContext, step: Step, tests: list[Test]) -> None:
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(tests)))


def _save_runs(context: CliContext, project: Project, records: list[runs.Run]) -> None:
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, runs.write(records)))


# -- the verbs ------------------------------------------------------------------------


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("test", "add"),
            summary="Add a test to a step: what must keep being true once the work is done.",
            configure=_configure_add,
            run=_add,
            examples=(
                "dplanner test add 'Fix list flicker' 'No flicker on render' "
                "--text '1. Open the list. 2. It must not flicker.'",
                "dplanner test add 'Fix list flicker' 'Rotation' --file steps.md",
            ),
        ),
        CliCommand(
            path=("test", "set"),
            summary="Change a test's title or its body.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner test set T100 --file rewritten.md",
                "dplanner test set T100 --title 'No flicker on data update'",
            ),
        ),
        CliCommand(
            path=("test", "show"),
            summary="Print a test, and how it last did.",
            configure=test_arg,
            run=_show,
            examples=("dplanner test show T100", "dplanner test show T100 --json"),
        ),
        CliCommand(
            path=("test", "list"),
            summary="A project's tests and their latest results, optionally within a scope.",
            configure=_configure_list,
            run=_list,
            examples=(
                "dplanner test list",
                "dplanner test list widget --scope 'Pre-release check'",
                "dplanner test list --archived --json",
            ),
        ),
        CliCommand(
            path=("test", "archive"),
            summary="Take a test off the roster; it stays on the step and keeps its history.",
            configure=test_arg,
            run=_archive,
            examples=("dplanner test archive T100",),
        ),
        CliCommand(
            path=("test", "unarchive"),
            summary="Put an archived test back on the roster.",
            configure=test_arg,
            run=_unarchive,
            examples=("dplanner test unarchive T100",),
        ),
        CliCommand(
            path=("test", "remove"),
            summary="Delete a test from its step. Its results stay in the runs that recorded them.",
            configure=test_arg,
            run=_remove,
            examples=("dplanner test remove T100",),
        ),
        *step_asset_commands(
            "test",
            MODULE_ID,
            file_help="the image to copy in beside the step",
            attach_summary="Add an image beside a step's tests and print the path to link to.",
            assets_summary="List the images a step's tests keep.",
            example_step="'Fix list flicker'",
            attached_text=lambda name: f"{name}\nReference it from a test body as ![]({name})",
        ),
        CliCommand(
            path=("test-run", "start"),
            summary="Open a test run over a scope. Closes whatever run was open.",
            configure=_configure_start,
            run=_start,
            examples=(
                "dplanner test-run start --label 'Pre-release 3'",
                "dplanner test-run start --scope 'Pre-release check' --label Nightly",
            ),
        ),
        CliCommand(
            path=("test-run", "mark"),
            summary="Record what a test did in the open run: ok, failed, skipped or pending.",
            configure=_configure_mark,
            run=_mark,
            examples=(
                "dplanner test-run mark T100 ok",
                "dplanner test-run mark T100 failed --note 'still flickers on data update'",
            ),
        ),
        CliCommand(
            path=("test-run", "show"),
            summary="A run and every test in it. Defaults to the open one.",
            configure=_configure_run_arg,
            run=_run_show,
            examples=("dplanner test-run show", "dplanner test-run show --run R101 --json"),
        ),
        CliCommand(
            path=("test-run", "list"),
            summary="A project's test runs, oldest first, with what each one found.",
            configure=_project_arg,
            run=_run_list,
            examples=("dplanner test-run list", "dplanner test-run list --json"),
        ),
        CliCommand(
            path=("test-run", "close"),
            summary="Close the open run; anything unmarked stays pending in the record.",
            configure=_configure_run_arg,
            run=_run_close,
            examples=("dplanner test-run close",),
        ),
    ]


# -- test add / set -------------------------------------------------------------------


def _body_arguments(parser: ArgumentParser) -> None:
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--file", help="a markdown file holding the test, or - for stdin")
    body.add_argument("--text", help="the test itself, inline")


def _configure_add(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("title", help="what the test is called, in the roster and in a run")
    _body_arguments(parser)


def _body(args: Namespace) -> str:
    if args.file is not None:
        return body_from(args.file)
    return args.text or ""


def _add(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    project = context.library.project_of(step.id)
    added = Test(id=next_test_id(project), title=args.title, body=_body(args))
    _save(context, step, [*read(step), added])
    context.report(
        {"step": step.id, "id": added.id, "title": added.title, "body": added.body},
        f"{added.id}  {added.title}  ({step.title})",
    )
    return 0


def _configure_set(parser: ArgumentParser) -> None:
    test_arg(parser)
    parser.add_argument("--title", help="rename the test")
    _body_arguments(parser)


def _set(context: CliContext, args: Namespace) -> int:
    _project, step, test = find_test(context.library, args.test, context.current)
    if args.title is None and args.file is None and args.text is None:
        raise CliError("nothing to change — pass --title, --file or --text")
    body = test.body if (args.file is None and args.text is None) else _body(args)
    changed = Test(test.id, args.title or test.title, body, test.archived)
    _save(context, step, replace(read(step), changed))
    context.report(
        {"step": step.id, "id": changed.id, "title": changed.title, "body": changed.body},
        f"{changed.id}  {changed.title}",
    )
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    project, step, test = find_test(context.library, args.test, context.current)
    outcome = runs.latest(runs.read(project), test.id)
    data = {
        "id": test.id,
        "title": test.title,
        "body": test.body,
        "archived": test.archived,
        "step": step.id,
        "step_title": step.title,
        "latest": _outcome_data(outcome),
    }
    lines = [f"{test.id}  {test.title}", f"  on {step.title}", f"  {_outcome_text(outcome)}"]
    if test.archived:
        lines.insert(1, "  archived")
    if test.body:
        lines += ["", test.body]
    context.report(data, "\n".join(lines))
    return 0


def _outcome_data(outcome: runs.Outcome | None) -> dict[str, str] | None:
    if outcome is None:
        return None
    return {
        "status": outcome.result.status,
        "note": outcome.result.note,
        "run": outcome.run.id,
        "run_label": outcome.run.label,
    }


def _outcome_text(outcome: runs.Outcome | None) -> str:
    if outcome is None:
        return "never run"
    where = outcome.run.label or outcome.run.id
    note = f" — {outcome.result.note}" if outcome.result.note else ""
    return f"{outcome.result.status} in {where}{note}"


# -- test list ------------------------------------------------------------------------


def _project_arg(parser: ArgumentParser) -> None:
    """The optional positional a project-wide verb takes — ``project lint``'s shape."""
    parser.add_argument(
        "project",
        nargs="?",
        help="project id, folder name, or part of its title (default: the current one)",
    )


def _configure_list(parser: ArgumentParser) -> None:
    _project_arg(parser)
    parser.add_argument(
        "--scope",
        metavar="STEP",
        help="only the tests behind this step — a check, a release, or any step at all",
    )
    parser.add_argument(
        "--archived", action="store_true", help="include tests taken off the roster"
    )


def _list(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    if args.scope is None:
        pairs = project_tests(project, archived=args.archived)
    else:
        scope = find_step(context.library, args.scope, project)
        pairs = covered(context.library, project, scope.id, archived=args.archived)
    outcomes = runs.latest_results(runs.read(project))
    data = {
        "project": project.id,
        "tests": [
            {
                "id": test.id,
                "title": test.title,
                "archived": test.archived,
                "step": step.id,
                "step_title": step.title,
                "latest": _outcome_data(outcomes.get(test.id)),
            }
            for step, test in pairs
        ],
    }
    width = max((len(test.title) for _step, test in pairs), default=0)
    lines = [
        f"{_STATUS_GLYPH[_status(outcomes, test)]} {test.id:<4} {test.title:<{width}}  "
        f"{step.title}" + ("  (archived)" if test.archived else "")
        for step, test in pairs
    ]
    context.report(data, "\n".join(lines) if lines else "No tests yet.")
    return 0


def _status(outcomes: dict[str, runs.Outcome], test: Test) -> str:
    outcome = outcomes.get(test.id)
    return outcome.result.status if outcome else "pending"


# -- archive / unarchive / remove -----------------------------------------------------


def _set_archived(context: CliContext, needle: str, archived: bool) -> int:
    _project, step, test = find_test(context.library, needle, context.current)
    word = "archived" if archived else "on the roster"
    if test.archived == archived:
        # Already there is success — state-setting verbs must survive batches.
        context.report({"id": test.id, "archived": archived}, f"{test.id}: already {word}")
        return 0
    changed = Test(test.id, test.title, test.body, archived)
    _save(context, step, replace(read(step), changed))
    context.report({"id": test.id, "archived": archived}, f"{test.id}: {word}")
    return 0


def _archive(context: CliContext, args: Namespace) -> int:
    return _set_archived(context, args.test, True)


def _unarchive(context: CliContext, args: Namespace) -> int:
    return _set_archived(context, args.test, False)


def _remove(context: CliContext, args: Namespace) -> int:
    _project, step, test = find_test(context.library, args.test, context.current)
    _save(context, step, [kept for kept in read(step) if kept.id != test.id])
    context.report({"id": test.id, "step": step.id}, f"{test.id}: removed from {step.title}")
    return 0


# -- runs -----------------------------------------------------------------------------


def _configure_start(parser: ArgumentParser) -> None:
    _project_arg(parser)
    parser.add_argument(
        "--scope",
        metavar="STEP",
        help="run only the tests behind this step — a check, a release, or any step",
    )
    parser.add_argument("--label", default="", help="what to call this run: 'Pre-release 3'")


def _start(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    scope_id = ""
    if args.scope is None:
        pairs = project_tests(project)
    else:
        scope = find_step(context.library, args.scope, project)
        scope_id = scope.id
        pairs = covered(context.library, project, scope.id)
    if not pairs:
        raise CliError("that scope holds no tests — `dplanner test add <step> '<title>'` first")
    records = runs.started(
        runs.read(project), [test.id for _step, test in pairs], label=args.label, scope=scope_id
    )
    _save_runs(context, project, records)
    opened = records[-1]
    context.report(
        {"run": opened.id, "label": opened.label, "tests": list(opened.tests)},
        f"{opened.id}  {opened.label or 'unlabelled'}  {len(opened.tests)} tests, all pending",
    )
    return 0


def _configure_mark(parser: ArgumentParser) -> None:
    test_arg(parser)
    parser.add_argument("status", choices=runs.STATUSES, help="what the test did")
    parser.add_argument("--note", default="", help="what happened — read on a failed test")


def _open_run(project: Project) -> runs.Run:
    records = runs.read(project)
    found = runs.open_run(records)
    if found is None:
        raise CliError("no test run is open — `dplanner test-run start` first")
    return found


def _mark(context: CliContext, args: Namespace) -> int:
    project, _step, test = find_test(context.library, args.test, context.current)
    records = runs.read(project)
    run = _open_run(project)
    if test.id not in run.tests:
        raise CliError(
            f"{test.id} is not in run {run.id} — a run holds the tests it was opened over"
        )
    marked = runs.marked(run, test.id, args.status, args.note)
    _save_runs(context, project, runs.replaced(records, marked))
    note = f" — {args.note}" if args.note else ""
    context.report(
        {"run": run.id, "id": test.id, "status": args.status, "note": args.note},
        f"{test.id}  {args.status}{note}  ({run.label or run.id})",
    )
    return 0


def _configure_run_arg(parser: ArgumentParser) -> None:
    _project_arg(parser)
    parser.add_argument("--run", metavar="ID", help="a run id (default: the open one)")


def _run(project: Project, run_id: str | None) -> runs.Run:
    if run_id is None:
        return _open_run(project)
    found = runs.find(runs.read(project), run_id)
    if found is None:
        raise CliError(f"no run {run_id!r} in this project")
    return found


def _run_show(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    run = _run(project, args.run)
    by_id = {test.id: (step, test) for step, test in project_tests(project, archived=True)}
    counts = runs.tally([run.result(test_id).status for test_id in run.tests])
    rows = []
    lines = []
    for test_id in run.tests:
        result = run.result(test_id)
        title = by_id[test_id][1].title if test_id in by_id else "(deleted test)"
        rows.append({"id": test_id, "title": title, "status": result.status, "note": result.note})
        note = f"  — {result.note}" if result.note else ""
        lines.append(f"{_STATUS_GLYPH[result.status]} {test_id:<4} {title}{note}")
    context.report(
        {
            "run": run.id,
            "label": run.label,
            "opened": run.opened,
            "closed": run.closed,
            "open": run.is_open,
            "counts": counts,
            "results": rows,
        },
        "\n".join([_run_headline(run, counts), *lines]),
    )
    return 0


def _run_headline(run: runs.Run, counts: dict[str, int]) -> str:
    state = "open" if run.is_open else "closed"
    tally = ", ".join(f"{count} {status}" for status, count in counts.items() if count)
    return f"{run.id}  {run.label or 'unlabelled'}  ({state})  {tally or 'nothing recorded'}"


def _run_list(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    records = runs.read(project)
    data = {
        "project": project.id,
        "runs": [
            {
                "id": run.id,
                "label": run.label,
                "opened": run.opened,
                "closed": run.closed,
                "open": run.is_open,
                "tests": len(run.tests),
                "counts": runs.tally([run.result(t).status for t in run.tests]),
            }
            for run in records
        ],
    }
    lines = [
        _run_headline(run, runs.tally([run.result(t).status for t in run.tests])) for run in records
    ]
    context.report(data, "\n".join(lines) if lines else "No test runs yet.")
    return 0


def _run_close(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    records = runs.read(project)
    run = _run(project, args.run)
    if not run.is_open:
        # Already closed is success — state-setting verbs must survive batches.
        context.report({"run": run.id, "open": False}, f"{run.id}: already closed")
        return 0
    _save_runs(context, project, runs.replaced(records, runs.closed(run)))
    counts = runs.tally([run.result(test_id).status for test_id in run.tests])
    tally = ", ".join(f"{count} {status}" for status, count in counts.items() if count)
    context.report({"run": run.id, "open": False, "counts": counts}, f"{run.id}: closed — {tally}")
    return 0


# -- what this module contributes to other people's verbs -----------------------------


def step_author() -> StepAuthor:
    """`step add`'s test flag: the new step arrives already carrying its first test."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--test",
            metavar="TITLE",
            help="a first test for the new step — what must keep being true",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if args.test is None:
            return None
        # The step names its project — `step add` may run with no current project.
        added = Test(id=next_test_id(context.library.project_of(step.id)), title=args.test)
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write([added])))
        return StepAuthored({"test": added.id}, f"test: {added.id} {added.title}")

    return StepAuthor(configure, author)


def lint_checks() -> list[LintCheck]:
    """One check: a test with a title and no body is one nobody can execute."""

    def empty_tests(_library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        return [
            LintFinding(
                check="test.empty",
                subject_id=step.id,
                subject=step.title,
                message=f"test {test.id} ({test.title}) has no body — nobody can execute it: "
                f"`dplanner test set {test.id} --file -`",
            )
            for step, test in project_tests(project)
            if not test.body.strip()
        ]

    return [empty_tests]
