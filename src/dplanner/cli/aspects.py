"""``dplanner aspect list`` — what a step can carry.

This command belongs to no feature: it answers a question *about* the features. So it takes
the aspects as an argument and the composition root supplies them, which is the same shape
as every other cross-feature wiring in this application — the list is assembled in one
place, and nothing here imports a module.
"""

from argparse import Namespace
from collections.abc import Sequence

from dplanner.cli.command import CliCommand, CliContext
from dplanner.domain.aspects import AspectSpec


def commands(specs: Sequence[AspectSpec]) -> list[CliCommand]:
    def run(context: CliContext, _args: Namespace) -> int:
        data = [{"id": s.id, "label": s.label, "summary": s.summary} for s in specs]
        width = max((len(spec.label) for spec in specs), default=0)
        text = "\n".join(f"{spec.label:<{width}}  {spec.summary}" for spec in specs)
        context.report({"aspects": data}, text or "(no aspects in this build)")
        return 0

    return [
        CliCommand(
            path=("aspect", "list"),
            summary="The kinds of fact a step can carry, and the verbs that write them.",
            run=run,
            needs_workspace=False,
            examples=("dplanner aspect list", "dplanner aspect list --json"),
        )
    ]
