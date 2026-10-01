"""``dplanner agent-state …`` and ``dplanner usage …`` — the shell's two ledgers, from
the terminal.

**agent-state** is how an agent reports where it stands, from inside its shell. Run Agent
stamps ``launched``; the agent moves the state along as it works — ``plan-for-review``
when its plan is ready, ``working`` while implementing, ``pending-approval`` while waiting
on one, ``needs-input`` when it has a question for the developer — and clears it when the
run ends (``status set … done`` is the claim about the work; this is the claim about the
shell).

**usage** is what the runs consumed, read from the project's ledger (``domain/ledger.py``).
``show`` prints a step's runs and their total; ``list`` prints a project's steps with a
total each, most first, and the project's sum. ``harvest`` reads a run's consumption back
from the agent CLI's own records into its ledger record — what the wrapper script runs
when the agent exits, named by ``--run`` or ``$DPLANNER_RUN``; ``--all`` sweeps every run
of this machine that is due, as the window does. ``record`` adopts a run nobody launched
from here: by the harness's own record (``--session`` for a CLI that names one, else the
earliest unclaimed session started in ``--dir`` at or after ``--since``), or by hand with
``--input`` and ``--output``. None of them commits: the window's Save does.

``commands()`` takes the harnesses as a parameter, supplied by the composition root —
the same shape as ``agent_cli.commands(briefing=…)``: a ``cli.py`` never imports another
module, so what crosses modules arrives as an argument.
"""

import os
from argparse import ArgumentParser, Namespace
from dataclasses import replace
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.discovery import RUN_ENV
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness, AgentUsage, Tokens, harness_by_id, summed
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.ledger import LedgerRecord, new_run_id
from dplanner.domain.model import Step, now_stamp
from dplanner.modules.step_agent_run import harvest
from dplanner.modules.step_agent_run.aspect import MODULE_ID, STATES, launched, read, write
from dplanner.modules.step_agent_run.harvest import launch_record
from dplanner.modules.step_agent_run.usage import record_words, spent, words


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

    def _harvest(context: CliContext, args: Namespace) -> int:
        return _harvest_with(context, args, harnesses)

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
        parser.add_argument("--input", type=int, help="fresh input tokens, recorded by hand")
        parser.add_argument("--cached", type=int, default=0, help="cache reads, recorded by hand")
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
            path=("usage", "harvest"),
            summary="Read what a run consumed back from the agent's own records into the"
            " ledger — one run, or every run of this machine that is due.",
            configure=_configure_harvest,
            run=_harvest,
            examples=("dplanner usage harvest --all", "dplanner usage harvest --run 20261001T…"),
        ),
        CliCommand(
            path=("usage", "record"),
            summary="Adopt a run nobody launched from here — read from the agent's own"
            " records, or given by hand.",
            configure=_configure_record,
            run=_record,
            examples=(
                "dplanner usage record S7 --agent claude --session 3f1c… --dir ~/code/widget",
                "dplanner usage record S7 --agent codex --input 12000 --output 3000",
            ),
        ),
    ]


def _configure_harvest(parser: ArgumentParser) -> None:
    parser.add_argument("--run", default="", help=f"the run to read (default: ${RUN_ENV})")
    parser.add_argument("--exit", type=int, help="the agent's exit status: the run has ended")
    parser.add_argument("--all", action="store_true", help="every run of this machine that is due")


def _ledger_dirs(context: CliContext) -> list[Path]:
    dirs = []
    for project in context.library.projects:
        try:
            dirs.append(context.store.project_dir(project.id))
        except KeyError:
            continue
    return dirs


def _step_records(context: CliContext, step: Step) -> list[LedgerRecord]:
    project = context.library.project_of(step.id)
    return [r for r in ledger.records(context.store.project_dir(project.id)) if r.step == step.id]


def _record_json(record: LedgerRecord) -> dict[str, object]:
    tokens = record.tokens
    return {
        "run": record.run,
        "harness": record.harness,
        "session": record.session,
        "launched": record.launched,
        "ended": record.ended,
        "measurement": record.measurement,
        "models": {
            model: {"in": t.input, "cached": t.cached, "out": t.output}
            for model, t in record.models().items()
        },
        "agents": len(record.agents),
        "input": tokens.input,
        "cached": tokens.cached,
        "output": tokens.output,
        "prompt_chars": record.prompt_chars,
    }


def _tokens_json(tokens: Tokens | None) -> dict[str, int]:
    tokens = tokens or Tokens()
    return {"input": tokens.input, "cached": tokens.cached, "output": tokens.output}


def _usage_show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    recorded = _step_records(context, step)
    total = spent(recorded)
    data = {"step": step.id, "runs": [_record_json(r) for r in recorded], **_tokens_json(total)}
    if total is None:
        context.report(data, f"{step.title}: no agent run recorded")
        return 0
    lines = [record_words(record) for record in recorded]
    lines.append(
        f"total: {words(total)} over {len(recorded)} run{'s' if len(recorded) != 1 else ''}"
    )
    context.report(data, f"{step.title}\n" + "\n".join(lines))
    return 0


def _usage_list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    per_step = ledger.by_step(ledger.records(context.store.project_dir(project.id)))
    counted: list[tuple[Step, Tokens]] = [
        (step, total)
        for step in project.steps
        if (total := spent(per_step.get(step.id, []))) is not None
    ]
    counted.sort(key=lambda pair: pair[1].worked, reverse=True)
    project_total = summed(total for _, total in counted)
    data = {
        "project": project.id,
        "steps": [
            {"id": step.id, "title": step.title, **_tokens_json(total)} for step, total in counted
        ],
        **_tokens_json(project_total),
    }
    if not counted:
        context.report(data, f"{project.title}: no agent run recorded")
        return 0
    lines = [f"{words(total):36} {step.title}" for step, total in counted]
    lines.append(f"total: {words(project_total)}")
    context.report(data, "\n".join(lines))
    return 0


def _harvest_with(context: CliContext, args: Namespace, harnesses: tuple[AgentHarness, ...]) -> int:
    dirs = _ledger_dirs(context)
    if args.all:
        written = harvest.sweep(dirs, harnesses)
        context.report({"written": written}, f"read back {written} run{'s' * (written != 1)}")
        return 0
    run = args.run or os.environ.get(RUN_ENV, "")
    if not run:
        raise CliError(f"name the run with --run (or ${RUN_ENV}), or sweep with --all")
    record = harvest.harvest_run(dirs, run, harnesses, code=args.exit, ended=args.exit is not None)
    if record is None:
        raise CliError(f"no run {run} in this library's ledgers")
    context.report(_record_json(record), f"{run}: {words(record.tokens)}")
    return 0


def _record_with(context: CliContext, args: Namespace, harnesses: tuple[AgentHarness, ...]) -> int:
    step = find_step(context.library, args.step, context.current)
    project = context.library.project_of(step.id)
    project_dir = context.store.project_dir(project.id)
    harness = harness_by_id(harnesses, args.agent)
    assert harness is not None  # argparse's choices already refused anything else.
    now = now_stamp()
    adopted = launch_record(
        run=new_run_id(),
        project=project.id,
        step=step.id,
        harness=harness.id,
        directory=Path(args.dir or "."),
        session=args.session,
        launched=args.since or now[:10] + "T00:00:00+00:00",
    ).ended_at(now, None)
    if args.input is not None or args.output is not None:
        if args.input is None or args.output is None:
            raise CliError("give both --input and --output, or neither")
        tokens = Tokens(args.input, args.cached, args.output)
        record = replace(
            adopted,
            measurement=ledger.MANUAL,
            harvested=now,
            agents=(AgentUsage("main", {ledger.UNKNOWN_MODEL: tokens}),),
        )
    else:
        if harness.report is None:
            raise CliError(
                f"{harness.label} keeps no record this build can read: give --input and --output"
            )
        claimed = ledger.claimed(r for d in _ledger_dirs(context) for r in ledger.records(d))
        record = harvest.harvest(adopted, harnesses, claimed)
        if not record.agents:
            raise CliError(
                f"no {harness.label} record found — name the session with --session,"
                " or the directory the agent worked in with --dir"
            )
    ledger.write(project_dir, record)
    context.report(
        {"step": step.id, "run": _record_json(record)},
        f"{step.title}: recorded {words(record.tokens)}",
    )
    return 0
