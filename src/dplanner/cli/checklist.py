"""``dplanner checklist show`` — is this machine set up to run DPlanner?

A cross-feature verb in the ``project lint`` mould, and for the same reason: whether a
machine is ready is a fact about *every* feature at once — the GitHub module owns ``gh``,
the agent modules own their CLIs, the installer owns its three pieces — and no module can
ask it without importing the others. So this file owns the shapes, the order, the report
and the exit code; each owning module exports :func:`checks` from its own Qt-free
``checks.py``; and the composition root assembles the tuple both surfaces read. Nothing
here imports a module, and nothing here is about a *plan* — ``needs_library`` is False.

Two states, not four. A probe answers :class:`Reading` — ok or not, with the words — and
the *tone* is derived from ``required``: a failing required check is the error tone, a
failing recommendation is information, and a check still being probed is busy. That is
``framework/signalling``'s four tones exactly, with no fifth added; whether a failure is
"missing" or "stale" is in the probe's own words, where it reads.

A :class:`Remedy` may name an **action id**. That is how a module offers to fix its own
row without any other module importing it: the window runs the id through
``ActionRegistry.run`` and the verb prints the words and the command.
"""

from argparse import Namespace
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from dplanner.cli.command import CliCommand, CliContext

# The display order of the groups, and the closed vocabulary a check's ``group`` names —
# menus.py's MENU_STRUCTURE for the same reason: a typo fails at assembly with the
# offending id rather than landing the row silently at the bottom.
GROUPS: tuple[str, ...] = (
    "DPlanner",
    "Git and GitHub",
    "Agents",
    "Services",
    "Other tools",
)


@dataclass(frozen=True)
class Reading:
    """What a probe found: whether it is well, and the words that say so."""

    ok: bool
    detail: str = ""  # "git 2.51.0", "installed but not signed in", "not on PATH"


@dataclass(frozen=True)
class Remedy:
    """What to do about a failing check.

    ``words`` always says it. ``command`` is what to type, printed by the verb. ``action``
    names a registered action the window offers as a button on the row — the owning
    module's own id, which is what lets it offer a fix without being imported — and
    ``verb`` is that button's word.
    """

    words: str
    command: str = ""
    action: str = ""
    verb: str = ""


Probe = Callable[[], Reading]


@dataclass(frozen=True)
class MachineCheck:
    """One row: a fact about this machine that DPlanner would like to be true.

    ``required`` means two things, and they are the same thing: the verb exits 1 while it
    fails, and it is probed at every start — so a required check must be cheap, with no
    network and no subprocess it cannot afford.
    """

    id: str  # Stable, module-prefixed: "github.gh", "install.skill".
    group: str  # One of GROUPS.
    label: str
    probe: Probe
    remedy: Remedy | None = None
    required: bool = False


def ordered(checks: Iterable[MachineCheck]) -> list[MachineCheck]:
    """The rows in the order every surface shows them: by group, required first inside it.

    Contributed order decides the rest, so a module's own list reads as it wrote it.
    """
    read = list(checks)
    for check in read:
        if check.group not in GROUPS:
            raise ValueError(f"{check.id}: no checklist group named {check.group!r}")
    return sorted(
        read,
        key=lambda check: (GROUPS.index(check.group), not check.required),
    )


def render(rows: Sequence[tuple[MachineCheck, Reading]]) -> str:
    """The text report: a heading per group, a state and the words, the remedy under it."""
    lines: list[str] = []
    group = ""
    for check, reading in rows:
        if check.group != group:
            group = check.group
            lines.append(group)
        # "problem" rather than "missing": a stale skill is not missing, and only the
        # probe's own words know which it is.
        state = "ok" if reading.ok else ("problem" if check.required else "advice")
        lines.append(f"  {state:<8} {check.label:<24} {reading.detail}".rstrip())
        if not reading.ok and check.remedy is not None:
            lines.append(f"           {check.remedy.words}")
            if check.remedy.command:
                lines.append(f"           $ {check.remedy.command}")
    lines.append(summary(rows))
    return "\n".join(lines)


def summary(rows: Sequence[tuple[MachineCheck, Reading]]) -> str:
    """One line: what a person should do about what they are looking at."""
    missing = sum(1 for check, reading in rows if check.required and not reading.ok)
    advice = sum(1 for check, reading in rows if not check.required and not reading.ok)
    if missing:
        said = f"{missing} required {'item needs' if missing == 1 else 'items need'} attention"
        return f"{said}; {advice} {'suggestion' if advice == 1 else 'suggestions'}."
    if advice:
        return (
            "Everything required is in place — "
            f"{advice} {'suggestion' if advice == 1 else 'suggestions'}."
        )
    return "This machine has everything."


def to_record(check: MachineCheck, reading: Reading) -> dict[str, object]:
    remedy = check.remedy
    return {
        "check": check.id,
        "group": check.group,
        "label": check.label,
        "required": check.required,
        "ok": reading.ok,
        "detail": reading.detail,
        "remedy": (
            None
            if remedy is None
            else {"words": remedy.words, "command": remedy.command, "action": remedy.action}
        ),
    }


def commands(checks: Sequence[MachineCheck]) -> list[CliCommand]:
    def _show(context: CliContext, _args: Namespace) -> int:
        rows = [(check, check.probe()) for check in ordered(checks)]
        missing = [check for check, reading in rows if check.required and not reading.ok]
        context.report(
            {
                "checks": [to_record(check, reading) for check, reading in rows],
                "failing": sum(1 for _check, reading in rows if not reading.ok),
                "required_failing": len(missing),
                "summary": summary(rows),
            },
            render(rows),
        )
        return 1 if missing else 0

    return [
        CliCommand(
            path=("checklist", "show"),
            summary="What this machine has of what DPlanner needs — git, the GitHub CLI, "
            "an agent CLI, a terminal, the keychain and DPlanner's own installs — with a "
            "remedy for each. Exits 1 while a required item is missing.",
            run=_show,
            needs_library=False,
            examples=("dplanner checklist show", "dplanner checklist show --json"),
        )
    ]
