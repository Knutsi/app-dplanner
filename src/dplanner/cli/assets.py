"""``<noun> attach`` / ``<noun> assets`` — the verb pair any file-carrying aspect offers.

The operations live in :mod:`dplanner.domain.assets`; this is their CLI rendering, written
once so the argument shape, the error messages and the ``--json`` keys cannot drift between
aspects. A module gets the pair by calling :func:`step_asset_commands` from its Qt-free
``cli.py`` with its own wording.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.assets import assets, attach


def step_asset_commands(
    noun: str,
    module_id: str,
    *,
    file_help: str,
    attach_summary: str,
    assets_summary: str,
    example_step: str,
    attached_text: Callable[[str], str] = lambda name: name,
) -> list[CliCommand]:
    """The two commands, worded by the calling module.

    ``attached_text`` renders the human line after an attach — the description aspect uses
    it to say how to reference the image from markdown.
    """

    def configure_attach(parser: ArgumentParser) -> None:
        step_arg(parser)
        parser.add_argument("file", help=file_help)

    def run_attach(context: CliContext, args: Namespace) -> int:
        source = Path(args.file)
        if not source.is_file():
            raise CliError(f"no such file: {args.file}")
        step = find_step(context.library, args.step, context.current)
        name = attach(context.store.files(step.id, module_id), source.read_bytes(), source.name)
        context.report({"step": step.id, "asset": name}, attached_text(name))
        return 0

    def run_assets(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        names = assets(context.store.files(step.id, module_id))
        context.report({"step": step.id, "assets": names}, "\n".join(names) or "(none)")
        return 0

    return [
        CliCommand(
            path=(noun, "attach"),
            summary=attach_summary,
            configure=configure_attach,
            run=run_attach,
            examples=(f"dplanner {noun} attach {example_step} diagram.png",),
        ),
        CliCommand(
            path=(noun, "assets"),
            summary=assets_summary,
            configure=step_arg,
            run=run_assets,
            examples=(f"dplanner {noun} assets {example_step}",),
        ),
    ]
