"""``dplanner agent-state …`` and ``dplanner usage …`` — the shell's two ledgers, from
the terminal.

**agent-state** is how an agent reports where it stands, from inside its shell. Run Agent
stamps ``launched``; the agent moves the state along as it works — ``plan-for-review``
when its plan is ready, ``working`` while implementing, ``pending-approval`` while waiting
on one, ``needs-input`` when it has a question for the developer — and clears it when the
run ends (``status set … done`` is the claim about the work; this is the claim about the
shell).

**usage** is what the runs consumed (``usage.py``). ``show`` prints a step's rows and
their total; ``list`` prints a project's steps with a total each, most expensive first,
and the project's sum; ``record`` writes a row for a run the window did not launch — by
the harness's own record (``--session`` for a CLI that names one, else the earliest
session started in ``--dir`` at or after ``--since``), or by hand with ``--input`` and
``--output``. The window records the same row when the shell it launched ends, so the
two surfaces keep one ledger.

``commands()`` takes the harnesses as a parameter, supplied by the composition root —
the same shape as ``agent_cli.commands(briefing=…)``: a ``cli.py`` never imports another
module, so what crosses modules arrives as an argument.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.agents import AgentHarness, RunFacts, Usage, harness_by_id
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Step, now_stamp
from dplanner.modules.step_agent_run.aspect import MODULE_ID, STATES, launched, read, write
from dplanner.modules.step_agent_run.usage import MODULE_ID as USAGE_ID
from dplanner.modules.step_agent_run.usage import row_for, rows, totals, with_row, words


def commands(*, harnesses: tuple[AgentHarness, ...]) -> list[CliCommand]:
    return [
        CliCommand(
            path=("agent-state", "set"),
            summary="Say where a launched agent stands on a step.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner agent-state set 'Read the spec' plan-for-review",),
        ),
        CliCommand(
            path=("agent-state", "show"),
            summary="Where the agent on one step stands, and since when.",
            configure=step_arg,
            run=_show,
            examples=("dplanner agent-state show 'Read the spec'",),
        ),
        CliCommand(
            path=("agent-state", "clear"),
            summary="The run is over; leaves no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner agent-state clear 'Read the spec'",),
        ),
        *_usage_commands(harnesses),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("state", choices=STATES, help="where the agent stands")


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    # The original launch stamp survives as the state moves along.
    context.apply(
        SetModuleDataCommand(step.id, MODULE_ID, write(args.state, launched=launched(step)))
    )
    context.report({"step": step.id, "state": args.state}, f"{step.title}: {args.state}")
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    state = read(step)
    data = {"step": step.id, "state": state, "launched": launched(step)}
    context.report(data, f"{step.title}: {state}" if state else f"{step.title}: no agent run")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id, "state": ""}, f"{step.title}: no agent run")
    return 0


# -- usage --------------------------------------------------------------------------------------


def _usage_commands(harnesses: tuple[AgentHarness, ...]) -> list[CliCommand]:
    def _record(context: CliContext, args: Namespace) -> int:
        return _record_with(context, args, harnesses)

    def _configure_record(parser: ArgumentParser) -> None:
        step_arg(parser)
        parser.add_argument(
            "--agent",
            choices=[harness.id for harness in harnesses],
            required=True,
            help="which agent CLI ran the step",
        )
        parser.add_argument("--session", default="", help="the session id, when the CLI names one")
        parser.add_argument(
            "--dir", default="", help="where the agent worked, to find a session by its records"
        )
        parser.add_argument(
            "--since", default="", help="ISO time the run started (default: today, midnight)"
        )
        parser.add_argument("--input", type=int, help="input tokens, recorded by hand")
        parser.add_argument("--output", type=int, help="output tokens, recorded by hand")

    return [
        CliCommand(
            path=("usage", "show"),
            summary="The tokens each agent run on a step consumed, and their total.",
            configure=step_arg,
            run=_usage_show,
            examples=("dplanner usage show S7",),
        ),
        CliCommand(
            path=("usage", "list"),
            summary="What every step in a project has consumed, most first.",
            configure=project_arg,
            run=_usage_list,
            examples=("dplanner usage list discovery",),
        ),
        CliCommand(
            path=("usage", "record"),
            summary="Record a run's tokens on a step — read from the agent's own records,"
            " or given by hand.",
            configure=_configure_record,
            run=_record,
            examples=(
                "dplanner usage record S7 --agent claude --session 3f1c… --dir ~/code/widget",
                "dplanner usage record S7 --agent codex --input 12000 --output 3000",
            ),
        ),
    ]


def _row_json(row: dict[str, object]) -> dict[str, object]:
    return {
        key: row.get(key) for key in ("harness", "session", "input", "output", "details", "ended")
    }


def _usage_show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    recorded = rows(step)
    total = totals(step)
    data = {
        "step": step.id,
        "runs": [_row_json(row) for row in recorded],
        "input": total.input if total else 0,
        "output": total.output if total else 0,
    }
    if total is None:
        context.report(data, f"{step.title}: no agent run recorded")
        return 0
    lines = [
        f"{row.get('ended', '')[:10]}  {row.get('harness', '?'):9}"
        f" {words(Usage(int(row['input']), int(row['output'])))}"
        for row in recorded
    ]
    lines.append(
        f"total: {words(total)} over {len(recorded)} run{'s' if len(recorded) != 1 else ''}"
    )
    context.report(data, f"{step.title}\n" + "\n".join(lines))
    return 0


def _usage_list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    counted: list[tuple[Step, Usage]] = [
        (step, total) for step in project.steps if (total := totals(step)) is not None
    ]
    counted.sort(key=lambda pair: pair[1].total, reverse=True)
    project_total = Usage(sum(u.input for _, u in counted), sum(u.output for _, u in counted))
    data = {
        "project": project.id,
        "steps": [
            {"id": step.id, "title": step.title, "input": u.input, "output": u.output}
            for step, u in counted
        ],
        "input": project_total.input,
        "output": project_total.output,
    }
    if not counted:
        context.report(data, f"{project.title}: no agent run recorded")
        return 0
    lines = [f"{words(u):24} {step.title}" for step, u in counted]
    lines.append(f"total: {words(project_total)}")
    context.report(data, "\n".join(lines))
    return 0


def _record_with(context: CliContext, args: Namespace, harnesses: tuple[AgentHarness, ...]) -> int:
    step = find_step(context.library, args.step, context.current)
    harness = harness_by_id(harnesses, args.agent)
    assert harness is not None  # argparse's choices already refused anything else.
    session = args.session
    if args.input is not None or args.output is not None:
        if args.input is None or args.output is None:
            raise CliError("give both --input and --output, or neither")
        usage = Usage(args.input, args.output)
    else:
        if harness.report is None:
            raise CliError(
                f"{harness.label} keeps no record this build can read: give --input and --output"
            )
        since = args.since or now_stamp()[:10] + "T00:00:00+00:00"
        report = harness.report(RunFacts(session=session, directory=args.dir, launched=since))
        if report is None or report.usage is None:
            raise CliError(
                f"no {harness.label} record found — name the session with --session,"
                " or the directory the agent worked in with --dir"
            )
        session, usage = report.session, report.usage
    row = row_for(harness.id, session, usage)
    context.apply(SetModuleDataCommand(step.id, USAGE_ID, with_row(step, row)))
    context.report(
        {"step": step.id, "run": _row_json(row)}, f"{step.title}: recorded {words(usage)}"
    )
    return 0
