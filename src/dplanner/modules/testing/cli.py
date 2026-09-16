"""``dplanner test …``, ``test-run …`` and ``test-category …`` — the tests, the occasions
of running them, and what they are filed under.

Three nouns because they are three things: ``test`` writes what a step must keep passing,
``test-run`` records one occasion of executing them, and ``test-category`` keeps the
project's list of what kinds of test there are. The hyphenated nouns follow ``agent-state``;
the CLI's grammar is always exactly ``dplanner <noun> <verb>``.

An agent is expected to be the one *executing* tests and reporting back, so ``test-run
mark`` is the verb this file is really shaped around: terse, idempotent, and safe to run in
a batch where some of the marks are already what they should be.

It is also expected to be the one *filing* them, which is what ``test-category`` is shaped
around: lay the categories out from the spec before the tests exist (``test-category add``),
then file each test as it is written (``test add --category``) — and when the roster has
outgrown its filing, reorganise it wholesale with ``test-category assign``, which moves a
batch in one call rather than one invocation per test.
"""

import dataclasses
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.assets import step_asset_commands
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_project, find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.modules.testing import export, runs
from dplanner.modules.testing.aspect import (
    AUDIENCE_IDS,
    AUDIENCES,
    DEFAULT_AUDIENCE,
    MODULE_ID,
    Test,
    audience_words,
    audiences_of,
    check_audience,
    covered,
    for_audiences,
    next_test_id,
    project_tests,
    read,
    replace,
    write,
)
from dplanner.modules.testing.categories import (
    ICONS,
    UNCATEGORISED,
    Category,
    category_of,
    check_icon,
    check_name,
    counts,
    read_catalog,
    refiled,
    renamed,
    rewrite,
    write_catalog,
)

# The stored list plus whatever a test names by itself — what a refusal reads, where
# `read_catalog` is the stored half and is what gets written back.
from dplanner.modules.testing.categories import catalog as all_categories

_STATUS_GLYPH = {"ok": "✓", "failed": "✗", "skipped": "-", "pending": " "}

# What `--audience` takes to mean "back to unclassified". An aspect whose default is not
# "off" needs a word for returning to it — `estimate clear` and `describe clear` are the
# same idea as verbs; here one repeatable flag covers both directions.
NO_AUDIENCE = "none"
# And the same word for `--category`, for the same reason and spelled the same way: a flag
# that can only ever set is a mistake a terminal cannot undo.
NO_CATEGORY = "none"

# -- what `test review` is handed ------------------------------------------------------

# A note, as much of one as this verb reads: its id, its label, its title and the day it
# was made. The composition root adapts the notes module's records to it, so neither
# module imports the other and testing learns nothing about what else a note carries —
# `cli/scopes.py`'s `CoveredTest` is the same hand-over one layer down.
type StepNote = tuple[str, str, str, str]

# Which notes unsettle a test is the root's to say: it is the one place that may know
# every aspect, and `_scope_kinds()` names its predicates literally for the same reason.
type NotesFor = Callable[[Project], Mapping[StepId, Sequence[StepNote]]]

DONE = "done"
DAY = 10  # An ISO stamp's date — the grain a note is written at, so the grain to compare.

REVIEW_CLEAR = "every test on a done step has been run since the last note on it"
REVIEW_ADVICE = (
    "run it again — `dplanner test-run start --scope {step}` then `test-run mark {test} "
    "<result>` — or `dplanner test set {test} --file -` if the note changed what it proves"
)


def _audience_argument(parser: ArgumentParser, *, purpose: str) -> None:
    """The ``--audience`` a test verb takes. Repeat it to name more than one."""
    parser.add_argument(
        "--audience",
        action="append",
        metavar="WHO",
        help=f"{purpose} — one of: {', '.join(AUDIENCE_IDS)}. Repeat for several.",
    )


def _wanted_audiences(args: Namespace) -> tuple[str, ...]:
    """The audiences named on the command line, checked and in canonical order."""
    return tuple(check_audience(value) for value in (args.audience or ()))


def _category_argument(parser: ArgumentParser, *, purpose: str) -> None:
    """The ``--category`` a test verb takes. Free text — the catalogue is open."""
    parser.add_argument(
        "--category",
        metavar="NAME",
        help=f"{purpose}. `dplanner test-category list` names the ones this project has.",
    )


def _wanted_category(args: Namespace, was: str = "") -> str:
    """What ``--category`` leaves behind: the name given, nothing, or what was there.

    ``--category none`` is how a test goes back to unfiled, which is the same word and the
    same reason as ``--audience none``: a flag that can only ever set is unfixable from a
    terminal.
    """
    named = getattr(args, "category", None)
    if named is None:
        return was
    return "" if named.strip().casefold() == NO_CATEGORY else check_name(named)


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
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, runs.write(project, records)))


# -- the verbs ------------------------------------------------------------------------


def commands(*, status_for: Callable[[Step], str], notes_for: NotesFor) -> list[CliCommand]:
    def review(context: CliContext, args: Namespace) -> int:
        return _review(context, args, status_for, notes_for)

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
            path=("test", "export"),
            summary="Write a project's tests out as Markdown or an HTML page, filed by "
            "category — what a QA team reads without DPlanner.",
            configure=_configure_export,
            run=_export,
            examples=(
                "dplanner test export --format html -o tests.html",
                "dplanner test export --audience qa --scope 'Pre-release check' -o qa.md",
            ),
        ),
        CliCommand(
            path=("test", "review"),
            summary="Tests that have gone stale: on a done step, not run since a decision "
            "or spec-change note landed on it.",
            configure=_project_arg,
            run=review,
            examples=("dplanner test review", "dplanner test review widget --json"),
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
        CliCommand(
            path=("test-category", "list"),
            summary="What this project files its tests under, and how many are in each.",
            configure=_project_arg,
            run=_category_list,
            examples=("dplanner test-category list", "dplanner test-category list --json"),
        ),
        CliCommand(
            path=("test-category", "add"),
            summary="Add a category. Lay them out from the spec before the tests exist.",
            configure=_configure_category_add,
            run=_category_add,
            examples=(
                "dplanner test-category add 'Import' --icon layers",
                "dplanner test-category add 'Smoke'",
            ),
        ),
        CliCommand(
            path=("test-category", "set"),
            summary="Rename a category or change its icon. A rename moves every test "
            "filed under it.",
            configure=_configure_category_set,
            run=_category_set,
            examples=(
                "dplanner test-category set Import --rename 'Import and export'",
                "dplanner test-category set Smoke --icon spark",
            ),
        ),
        CliCommand(
            path=("test-category", "remove"),
            summary="Take a category off the list; its tests stay, filed under nothing.",
            configure=_configure_category_name,
            run=_category_remove,
            examples=("dplanner test-category remove Smoke",),
        ),
        CliCommand(
            path=("test-category", "assign"),
            summary="File tests under a category — several at once, which is what "
            "reorganising a roster is made of.",
            configure=_configure_category_assign,
            run=_category_assign,
            examples=(
                "dplanner test-category assign Import T100 T101 T104",
                "dplanner test-category assign none T100",
            ),
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
    _audience_argument(parser, purpose="who the test is for")
    _category_argument(parser, purpose="what to file the test under")
    _body_arguments(parser)


def _body(args: Namespace) -> str:
    if args.file is not None:
        return body_from(args.file)
    return args.text or ""


def _add(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    project = context.library.project_of(step.id)
    added = Test(
        id=next_test_id(project),
        title=args.title,
        body=_body(args),
        audiences=_wanted_audiences(args),
        category=_wanted_category(args),
    )
    _save(context, step, [*read(step), added])
    context.report(
        {
            "step": step.id,
            "id": added.id,
            "title": added.title,
            "body": added.body,
            "audiences": list(added.audiences),
            "category": added.category,
        },
        f"{added.id}  {added.title}  ({step.title})",
    )
    return 0


def _configure_set(parser: ArgumentParser) -> None:
    test_arg(parser)
    parser.add_argument("--title", help="rename the test")
    _audience_argument(
        parser, purpose=f"replace who the test is for; {NO_AUDIENCE!r} leaves it unclassified"
    )
    _category_argument(
        parser, purpose=f"file the test under this; {NO_CATEGORY!r} leaves it unfiled"
    )
    _body_arguments(parser)


def _set(context: CliContext, args: Namespace) -> int:
    _project, step, test = find_test(context.library, args.test, context.current)
    nothing = (
        args.title is None
        and args.file is None
        and args.text is None
        and not args.audience
        and args.category is None
    )
    if nothing:
        raise CliError("nothing to change — pass --title, --file, --text, --audience or --category")
    body = test.body if (args.file is None and args.text is None) else _body(args)
    changed = dataclasses.replace(
        test,
        title=args.title or test.title,
        body=body,
        audiences=_replacement_audiences(args, test),
        category=_wanted_category(args, test.category),
    )
    _save(context, step, replace(read(step), changed))
    context.report(
        {
            "step": step.id,
            "id": changed.id,
            "title": changed.title,
            "body": changed.body,
            "audiences": list(changed.audiences),
            "category": changed.category,
        },
        f"{changed.id}  {changed.title}",
    )
    return 0


def _replacement_audiences(args: Namespace, test: Test) -> tuple[str, ...]:
    """What ``test set --audience`` leaves behind: the named set, nothing, or what was there.

    ``--audience none`` is how a test goes back to unclassified; without it the flag can only
    ever add, and a mistake would be unfixable from the terminal.
    """
    named = args.audience or []
    if not named:
        return test.audiences
    if NO_AUDIENCE in named:
        if len(named) > 1:
            raise CliError(f"--audience {NO_AUDIENCE} cannot be combined with an audience")
        return ()
    return _wanted_audiences(args)


def _show(context: CliContext, args: Namespace) -> int:
    project, step, test = find_test(context.library, args.test, context.current)
    outcome = runs.latest(runs.read(project), test.id)
    data = {
        "id": test.id,
        "title": test.title,
        "body": test.body,
        "archived": test.archived,
        "audiences": list(test.audiences),
        # What it *stored*, so a caller can tell a test nobody filed from one deliberately
        # left unfiled — `category_of` is what says what it reads as.
        "category": test.category,
        "step": step.id,
        "step_title": step.title,
        "latest": _outcome_data(outcome),
    }
    lines = [
        f"{test.id}  {test.title}",
        f"  in {category_of(test)}",
        f"  for {audience_words(test)}",
        f"  on {step.title}",
        f"  {_outcome_text(outcome)}",
    ]
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
    _audience_argument(parser, purpose="only the tests written for these")
    parser.add_argument(
        "--category",
        metavar="NAME",
        help=f"only the tests filed under this; {UNCATEGORISED!r} for the ones filed nowhere",
    )


def _list(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    if args.scope is None:
        pairs = project_tests(project, archived=args.archived)
    else:
        scope = find_step(context.library, args.scope, project)
        pairs = covered(context.library, project, scope.id, archived=args.archived)
    pairs = for_audiences(pairs, _wanted_audiences(args))
    pairs = _in_category(pairs, args.category)
    outcomes = runs.latest_results(runs.read(project))
    data = {
        "project": project.id,
        "tests": [
            {
                "id": test.id,
                "title": test.title,
                "archived": test.archived,
                # The stored ids, not what it reads as, so a caller can tell a test nobody
                # has classified from one somebody deliberately filed under `other`.
                "audiences": list(test.audiences),
                "category": test.category,
                "step": step.id,
                "step_title": step.title,
                "latest": _outcome_data(outcomes.get(test.id)),
            }
            for step, test in pairs
        ],
    }
    width = max((len(test.title) for _step, test in pairs), default=0)
    for_width = max((len(audience_words(test)) for _step, test in pairs), default=0)
    in_width = max((len(category_of(test)) for _step, test in pairs), default=0)
    lines = [
        f"{_STATUS_GLYPH[_status(outcomes, test)]} {test.id:<4} {test.title:<{width}}  "
        f"{category_of(test):<{in_width}}  {audience_words(test):<{for_width}}  {step.title}"
        + ("  (archived)" if test.archived else "")
        for step, test in pairs
    ]
    context.report(data, "\n".join(lines) if lines else _nothing_listed(args))
    return 0


def _in_category(pairs: Sequence[tuple[Step, Test]], named: str | None) -> list[tuple[Step, Test]]:
    """``pairs`` narrowed to one category, read through ``category_of`` so *Uncategorised*
    names the tests nobody filed. Matched without regard to case, as everywhere."""
    if not named:
        return list(pairs)
    wanted = named.strip().casefold()
    return [pair for pair in pairs if category_of(pair[1]).casefold() == wanted]


def _nothing_listed(args: Namespace) -> str:
    if args.category:
        return f"No test is filed under {args.category!r}."
    if args.audience:
        return f"No test is written for {', '.join(args.audience)}."
    return "No tests yet."


def _status(outcomes: dict[str, runs.Outcome], test: Test) -> str:
    outcome = outcomes.get(test.id)
    return outcome.result.status if outcome else "pending"


# -- test export ----------------------------------------------------------------------


def _configure_export(parser: ArgumentParser) -> None:
    _project_arg(parser)
    parser.add_argument(
        "--format",
        choices=export.FORMATS,
        default=export.FORMATS[0],
        help="markdown a repository keeps, or one self-contained HTML page a person opens",
    )
    parser.add_argument(
        "-o",
        "--out",
        metavar="PATH",
        help="where to write it; without this it goes to standard output",
    )
    parser.add_argument(
        "--scope",
        metavar="STEP",
        help="only the tests behind this step — a check, a release, or any step at all",
    )
    parser.add_argument(
        "--archived", action="store_true", help="include tests taken off the roster"
    )
    _audience_argument(parser, purpose="only the tests written for these")


def _export(context: CliContext, args: Namespace) -> int:
    """The roster as a document. Not ``--json``'s business: this is prose for a person."""
    project = _scoped(context, args.project)
    scope = None if args.scope is None else find_step(context.library, args.scope, project)
    wanted = _wanted_audiences(args)
    pairs = export.narrowed(
        context.library,
        project,
        scope="" if scope is None else scope.id,
        audiences=wanted,
        archived=args.archived,
    )
    text = export.render(
        export.Exported(
            project=project,
            pairs=pairs,
            outcomes=runs.latest_results(runs.read(project)),
            audiences=[a.label for a in AUDIENCES if a.id in wanted],
            archived=args.archived,
            scope=(scope.title or "Untitled step") if scope is not None else "",
        ),
        args.format,
    )
    if args.out is None:
        context.report({"format": args.format, "tests": len(pairs)}, text)
        return 0
    path = Path(args.out)
    path.write_text(text, encoding="utf-8")
    context.report(
        {"format": args.format, "tests": len(pairs), "path": str(path)},
        f"{path} — {len(pairs)} test{'' if len(pairs) == 1 else 's'}",
    )
    return 0


# -- test-category ---------------------------------------------------------------------


def _configure_category_name(parser: ArgumentParser) -> None:
    """The one positional every category verb but ``list`` takes.

    No project positional: these act in the current project the way ``test add`` and ``test
    set`` do, and the global ``--project`` names another. ``list`` is the reader and takes
    the optional positional its siblings ``test list`` and ``test review`` take.
    """
    parser.add_argument("name", help="the category, by its words (matched ignoring case)")


def _icon_argument(parser: ArgumentParser) -> None:
    """``--icon``, which names the set twice over rather than once in this line.

    Thirty glyph names in a ``--help`` line is a wall nobody reads, and this line is in the
    generated ``reference.md`` that every agent session loads. The set is discoverable
    where it is useful instead: ``test-category list --json`` carries it beside what the
    project already has, and a wrong name is refused with the whole tuple.
    """
    parser.add_argument(
        "--icon",
        metavar="GLYPH",
        help="a glyph for the category (beaker, shield, spark, …); "
        "`test-category list --json` names them all",
    )


def _configure_category_add(parser: ArgumentParser) -> None:
    _configure_category_name(parser)
    _icon_argument(parser)


def _configure_category_set(parser: ArgumentParser) -> None:
    _configure_category_name(parser)
    parser.add_argument(
        "--rename",
        metavar="NAME",
        help="new words for it — every test filed under the old ones moves with it",
    )
    _icon_argument(parser)


def _configure_category_assign(parser: ArgumentParser) -> None:
    parser.add_argument(
        "name", help=f"the category to file them under, or {NO_CATEGORY!r} to unfile them"
    )
    parser.add_argument("tests", nargs="+", metavar="TEST", help="test ids, or parts of titles")


def _find_category(project: Project, name: str) -> Category:
    """One of this project's categories, matched by its words; a CliError naming them all."""
    found = next(
        (
            entry
            for entry in all_categories(project)
            if entry.name.casefold() == name.strip().casefold()
        ),
        None,
    )
    if found is None:
        held = ", ".join(entry.name for entry in all_categories(project)) or "none yet"
        raise CliError(f"no category {name!r} in this project — it has: {held}")
    return found


def _save_catalog(context: CliContext, project: Project, entries: Sequence[Category]) -> None:
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_catalog(project, entries)))


def _category_data(project: Project, entry: Category, held: Mapping[str, int]) -> dict[str, object]:
    return {"name": entry.name, "icon": entry.icon, "tests": held.get(entry.name, 0)}


def _category_list(context: CliContext, args: Namespace) -> int:
    project = _scoped(context, args.project)
    entries = all_categories(project)
    held = counts(project, archived=True)
    unfiled = held.get(UNCATEGORISED, 0)
    data = {
        "project": project.id,
        "categories": [_category_data(project, entry, held) for entry in entries],
        "uncategorised": unfiled,
        # The glyphs on offer, so an agent picking one for `--icon` reads them from the
        # verb it was already going to call rather than from a refusal.
        "icons": list(ICONS),
    }
    width = max((len(entry.name) for entry in entries), default=len(UNCATEGORISED))
    lines = [
        f"{entry.name:<{width}}  {held.get(entry.name, 0):>3}"
        + (f"  {entry.icon}" if entry.icon else "")
        for entry in entries
    ]
    lines.append(f"{UNCATEGORISED:<{width}}  {unfiled:>3}")
    context.report(data, "\n".join(lines))
    return 0


def _category_add(context: CliContext, args: Namespace) -> int:
    project = context.project
    name = check_name(args.name)
    icon = check_icon(args.icon or "")
    entries = read_catalog(project)
    existing = next((e for e in entries if e.name.casefold() == name.casefold()), None)
    if existing is not None:
        # Adding one that is already there is that one, reported rather than doubled: a
        # verb an agent may retry must survive the retry (`note add`'s rule).
        if icon and existing.icon != icon:
            entries = [Category(e.name, icon) if e is existing else e for e in entries]
            _save_catalog(context, project, entries)
            existing = Category(existing.name, icon)
        context.report(
            _category_data(project, existing, counts(project, archived=True)),
            f"{existing.name}: already there",
        )
        return 0
    added = Category(name, icon)
    _save_catalog(context, project, [*entries, added])
    context.report(
        _category_data(project, added, counts(project, archived=True)),
        f"{added.name}" + (f"  {added.icon}" if added.icon else ""),
    )
    return 0


def _category_set(context: CliContext, args: Namespace) -> int:
    project = context.project
    entry = _find_category(project, args.name)
    if args.rename is None and args.icon is None:
        raise CliError("nothing to change — pass --rename or --icon")
    name = check_name(args.rename) if args.rename is not None else entry.name
    icon = check_icon(args.icon) if args.icon is not None else entry.icon
    clash = next(
        (
            other
            for other in all_categories(project)
            if other.name.casefold() == name.casefold() and other.name != entry.name
        ),
        None,
    )
    if clash is not None:
        raise CliError(f"this project already has a category called {clash.name!r}")
    stored = read_catalog(project)
    known = {e.name.casefold() for e in stored}
    changed = (
        [Category(name, icon) if e.name == entry.name else e for e in stored]
        # A category only a test named is not in the catalogue yet; renaming it is how it
        # gets in, rather than a refusal the reader can do nothing about.
        if entry.name.casefold() in known
        else [*stored, Category(name, icon)]
    )
    moved = 0
    if name != entry.name:
        for step_id, tests in rewrite(project, lambda ts: renamed(ts, entry.name, name)).items():
            context.apply(SetModuleDataCommand(step_id, MODULE_ID, write(tests)))
            moved += sum(1 for test in tests if test.category == name)
    _save_catalog(context, project, changed)
    context.report(
        {"name": name, "icon": icon, "was": entry.name, "moved": moved},
        f"{entry.name} → {name}" if name != entry.name else f"{name}  {icon or 'no icon'}",
    )
    return 0


def _category_remove(context: CliContext, args: Namespace) -> int:
    project = context.project
    entry = _find_category(project, args.name)
    unfiled = 0
    # Off the list *and* off the tests: a category a test still named would come straight
    # back, because `catalog` reads what the tests say as well as what was written down.
    for step_id, tests in rewrite(project, lambda ts: renamed(ts, entry.name, "")).items():
        context.apply(SetModuleDataCommand(step_id, MODULE_ID, write(tests)))
        unfiled += sum(1 for test in tests if not test.category)
    _save_catalog(context, project, [e for e in read_catalog(project) if e.name != entry.name])
    context.report(
        {"name": entry.name, "unfiled": unfiled},
        f"{entry.name}: removed — {unfiled} test{'' if unfiled == 1 else 's'} now unfiled",
    )
    return 0


def _category_assign(context: CliContext, args: Namespace) -> int:
    project = context.project
    name = "" if args.name.strip().casefold() == NO_CATEGORY else check_name(args.name)
    if name:
        _find_category(project, name)  # Refuse a typo rather than minting a category from it.
    found = [find_test(context.library, needle, project) for needle in args.tests]
    wanted: dict[StepId, set[str]] = {}
    for _project, step, test in found:
        wanted.setdefault(step.id, set()).add(test.id)
    for step_id, test_ids in wanted.items():
        step = context.library.step(step_id)
        context.apply(
            SetModuleDataCommand(step_id, MODULE_ID, write(refiled(read(step), test_ids, name)))
        )
    ids = sorted(test.id for _p, _s, test in found)
    context.report(
        {"category": name, "tests": ids},
        f"{len(ids)} test{'' if len(ids) == 1 else 's'} → {name or UNCATEGORISED}",
    )
    return 0


# -- test review ----------------------------------------------------------------------


def _last_seen(outcome: runs.Outcome | None) -> str:
    """The day a test last had a result, or "" when it never has had one.

    A run's own day: closed if it is, else opened, because a result recorded in a run
    still open was recorded today and not whenever the run eventually ends.
    """
    if outcome is None:
        return ""
    return (outcome.run.closed or outcome.run.opened)[:DAY]


def _behind(notes: Sequence[StepNote], last_seen: str) -> StepNote | None:
    """The newest note the test has not been run since, or None when it is up to date.

    A test nobody has ever run is behind every note on its step: nothing has established
    it against any of them. A note nobody dated cannot be *shown* to postdate a run, so
    it counts only in that case — claiming staleness from an absent date would put a row
    in front of somebody that they cannot act on.
    """
    later = [note for note in notes if note[3] > last_seen] if last_seen else list(notes)
    # By day, then by id, so two notes of one day pick the same one on every run.
    return max(later, key=lambda note: (note[3], note[0])) if later else None


def _review_rows(
    project: Project, status_for: Callable[[Step], str], notes_for: NotesFor
) -> list[dict[str, str]]:
    """One row per stale test, naming the newest note it is behind.

    Per test rather than per note: a test behind three decisions is one thing to do, and
    the newest note is the one that says what it now has to prove.
    """
    by_step = notes_for(project)
    if not by_step:
        return []
    outcomes = runs.latest_results(runs.read(project))
    rows: list[dict[str, str]] = []
    for step in project.steps:
        notes = by_step.get(step.id)
        # Only a done step: work still in progress is *meant* to be ahead of its tests.
        if not notes or status_for(step) != DONE:
            continue
        for test in read(step):
            if test.archived:
                continue  # Off the roster: nobody is going to run it, stale or not.
            last_seen = _last_seen(outcomes.get(test.id))
            found = _behind(notes, last_seen)
            if found is None:
                continue
            note_id, label, note_title, made = found
            ran = f"last run {last_seen}" if last_seen else "never run"
            rows.append(
                {
                    "test": test.id,
                    "title": test.title,
                    "audiences": ", ".join(audiences_of(test)),
                    "step": step.id,
                    "step_title": step.title,
                    "note": note_id,
                    "label": label,
                    "note_title": note_title,
                    "made": made,
                    "last_run": last_seen,
                    "subject": test.id,
                    "what": f"{test.title} on {step.title} — {ran}, behind {note_id} "
                    f"({label}{f', {made}' if made else ''}) {note_title!r}",
                    "advice": REVIEW_ADVICE.format(test=test.id, step=repr(step.title)),
                }
            )
    return rows


def _review(
    context: CliContext, args: Namespace, status_for: Callable[[Step], str], notes_for: NotesFor
) -> int:
    project = _scoped(context, args.project)
    rows = _review_rows(project, status_for, notes_for)
    context.report(
        {"project": project.id, "findings": rows, "count": len(rows)},
        "\n".join(f"{row['subject']:<6} {row['what']}\n    {row['advice']}" for row in rows)
        or REVIEW_CLEAR,
    )
    return 0


# -- archive / unarchive / remove -----------------------------------------------------


def _set_archived(context: CliContext, needle: str, archived: bool) -> int:
    _project, step, test = find_test(context.library, needle, context.current)
    word = "archived" if archived else "on the roster"
    if test.archived == archived:
        # Already there is success — state-setting verbs must survive batches.
        context.report({"id": test.id, "archived": archived}, f"{test.id}: already {word}")
        return 0
    changed = dataclasses.replace(test, archived=archived)
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
    _audience_argument(parser, purpose="run only the tests written for these")
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
    # Narrowed like the listing is, and for the same reason an agent asked for it: "run the
    # QA pass" is a real occasion. The run records only the ids it was opened over — that
    # already says what it covers, so it needs no audience of its own.
    wanted = _wanted_audiences(args)
    pairs = for_audiences(pairs, wanted)
    if not pairs:
        if wanted:
            raise CliError(f"no test in that scope is written for {', '.join(wanted)}")
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
        # Its own flag rather than `--audience`, because `step add` carries every module's
        # and a bare one would read as the step's. Without it the new test lands
        # unclassified and `project lint` asks about it straight away.
        parser.add_argument(
            "--test-audience",
            action="append",
            metavar="WHO",
            help=f"who that test is for — one of: {', '.join(AUDIENCE_IDS)}. Repeat for several.",
        )
        # And its own flag for the same reason: `step add` carries every module's, so a
        # bare `--category` would read as the step's.
        parser.add_argument(
            "--test-category",
            metavar="NAME",
            help="what to file that test under — `dplanner test-category list` names them",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if args.test is None:
            return None
        # The step names its project — `step add` may run with no current project.
        added = Test(
            id=next_test_id(context.library.project_of(step.id)),
            title=args.test,
            audiences=tuple(check_audience(value) for value in (args.test_audience or ())),
            category=check_name(args.test_category) if args.test_category else "",
        )
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write([added])))
        return StepAuthored({"test": added.id}, f"test: {added.id} {added.title}")

    return StepAuthor(configure, author)


def lint_checks() -> list[LintCheck]:
    """Three checks: a test nobody can execute, one that does not say who it is for, and
    one nobody has filed."""

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

    def unclassified(_library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """The raw field, not ``audiences_of`` — this is the one question that is about
        whether somebody has actually said, rather than what the test counts as."""
        return [
            LintFinding(
                check="test.audience",
                subject_id=step.id,
                subject=step.title,
                message=f"test {test.id} ({test.title}) does not say who it is for — it reads "
                f"as {DEFAULT_AUDIENCE!r}: `dplanner test set {test.id} --audience "
                f"{AUDIENCE_IDS[0]}`",
            )
            for step, test in project_tests(project)
            if not test.audiences
        ]

    def unfiled(_library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """The raw field again, and only once the project *has* categories.

        A project that has not started filing its tests is not behind on anything — the
        check exists to catch the test that was added after the filing was laid out, which
        is the one an agent's next `test add` forgets.
        """
        if not all_categories(project):
            return []
        offered = ", ".join(entry.name for entry in all_categories(project))
        return [
            LintFinding(
                check="test.category",
                subject_id=step.id,
                subject=step.title,
                message=f"test {test.id} ({test.title}) is filed under nothing — it reads as "
                f"{UNCATEGORISED!r}: `dplanner test set {test.id} --category <{offered}>`",
            )
            for step, test in project_tests(project)
            if not test.category
        ]

    return [empty_tests, unclassified, unfiled]
