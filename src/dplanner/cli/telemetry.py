"""``dplanner telemetry``: the journal, read from the command line.

The window and every CLI run append to one file (``core/telemetry.py``), so this is where
an agent — or a person at a terminal — reads what the application did and how long it
took: the slow actions, the failures with their tracebacks, the stalls the watchdog
sampled, and its own runs beside the window's. A cross-feature verb in the ``project
lint`` mould: it owns the shapes and the ``--json`` keys, and no module is involved. The
paths arrive from the composition root, so a test reads a journal under ``tmp_path``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.core.telemetry import Span, read_journal

DEFAULT_LAST = 50
CRASH_TAIL_LINES = 40


def commands(*, journal: Path, crash_log: Path) -> list[CliCommand]:
    def configure_show(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--last",
            type=int,
            default=DEFAULT_LAST,
            metavar="N",
            help=f"how many of the newest spans to show (default {DEFAULT_LAST}; 0 for all)",
        )
        parser.add_argument(
            "--kind",
            metavar="KIND",
            help="only spans of this kind: action, command, slot, task, autosave, poll, "
            "session, stall, cli, failure",
        )
        parser.add_argument(
            "--slow",
            type=float,
            metavar="MS",
            help="only spans that took at least this many milliseconds",
        )
        parser.add_argument(
            "--failures",
            action="store_true",
            help="only what went wrong, with tracebacks — and the crash log's tail, if any",
        )

    def run_show(context: CliContext, args: Namespace) -> int:
        spans = read_journal(journal)
        if args.kind:
            spans = [span for span in spans if span.kind == args.kind]
        if args.slow is not None:
            spans = [span for span in spans if (span.duration_ms or 0.0) >= args.slow]
        if args.failures:
            spans = [span for span in spans if not span.ok]
        if args.last:
            spans = spans[-args.last :]
        crash = crash_tail(crash_log) if args.failures else ""
        context.report(
            {
                "journal": str(journal),
                "spans": [span.to_record() for span in spans],
                "crash_log": crash or None,
            },
            render(spans, journal, crash=crash, with_tracebacks=args.failures),
        )
        return 0

    def run_path(context: CliContext, _args: Namespace) -> int:
        context.report(
            {"journal": str(journal), "crash_log": str(crash_log)},
            f"{journal}\n{crash_log}",
        )
        return 0

    def run_clear(context: CliContext, _args: Namespace) -> int:
        removed = [str(path) for path in _clear(journal, crash_log)]
        context.report(
            {"removed": removed},
            "\n".join(removed) if removed else "Nothing to clear.",
        )
        return 0

    return [
        CliCommand(
            path=("telemetry", "show"),
            summary="What the window and the CLI did and how long it took, newest last.",
            configure=configure_show,
            run=run_show,
            needs_library=False,
            examples=(
                "dplanner telemetry show --slow 50",
                "dplanner telemetry show --failures",
                "dplanner telemetry show --kind cli --last 10 --json",
            ),
        ),
        CliCommand(
            path=("telemetry", "path"),
            summary="Where the journal and the crash log live.",
            run=run_path,
            needs_library=False,
        ),
        CliCommand(
            path=("telemetry", "clear"),
            summary="Empty the journal, its rotated half and the crash log.",
            run=run_clear,
            needs_library=False,
        ),
    ]


def render(spans: Iterable[Span], journal: Path, *, crash: str, with_tracebacks: bool) -> str:
    lines = [line(span, with_tracebacks) for span in spans]
    if not lines:
        lines.append(f"No spans in {journal}.")
    if crash:
        lines.append("")
        lines.append("crash.log (tail):")
        lines.extend(f"  {text}" for text in crash.splitlines())
    return "\n".join(lines)


def line(span: Span, with_traceback: bool) -> str:
    """One span as one line — and its traceback under it when asked for."""
    when = datetime.fromtimestamp(span.started_at).strftime("%H:%M:%S.%f")[:-3]
    took = "—" if span.duration_ms is None else f"{span.duration_ms:8.1f} ms"
    outcome = "ok" if span.ok else "FAILED"
    indent = "  " if span.parent is not None else ""
    where = f"[{span.surface} {span.pid}]"
    text = f"{when}  {span.kind:<9} {indent}{span.name:<40} {took:>12}  {outcome}  {where}"

    if not span.ok and span.error_message:
        text += f"\n    {span.error_type or 'error'}: {span.error_message}"
    if with_traceback and span.traceback:
        text += "\n" + "\n".join(f"    {row}" for row in span.traceback.rstrip().splitlines())
    return text


def crash_tail(crash_log: Path) -> str:
    if not crash_log.is_file():
        return ""
    try:
        rows = crash_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        raise CliError(f"cannot read {crash_log}: {error}") from error
    return "\n".join(rows[-CRASH_TAIL_LINES:])


def _clear(journal: Path, crash_log: Path) -> list[Path]:
    removed: list[Path] = []
    for path in (journal, journal.with_name(journal.stem + ".1.jsonl"), crash_log):
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed
