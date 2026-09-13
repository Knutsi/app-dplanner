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

It may also name **packages** rather than a command, and :func:`install_line` turns them
into the line *this* machine would actually run — ``sudo pacman -S github-cli`` on an Arch
box, ``brew install gh`` on a Mac. Omarchy needs no row of its own in that table and must
not get one: it says ``ID_LIKE=arch`` in ``/etc/os-release``, which is the whole reason that
field is read rather than ``ID`` alone.
"""

import shutil
import sys
from argparse import Namespace
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

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

    ``words`` always says it. ``action`` names a registered action the window offers as a
    button on the row — the owning module's own id, which is what lets it offer a fix
    without being imported — and ``verb`` is that button's word. ``url`` is where to read
    about it, offered as a link on the row and printed by the verb.

    What to *type* is either ``command``, when it is the same everywhere, or ``packages``,
    when it is a package by another name on every machine: a family from :data:`FAMILIES`
    (or ``""`` for the name most of them use) to the package. :func:`command_for` picks.
    A check that cannot name a line it is *sure* of names none — a wrong install command is
    worse than a URL.
    """

    words: str
    command: str = ""
    action: str = ""
    verb: str = ""
    url: str = ""
    packages: Mapping[str, str] = field(default_factory=dict)


# How each package manager installs one package, as a line a person can paste.
MANAGERS: dict[str, str] = {
    "yay": "yay -S {package}",
    "pacman": "sudo pacman -S {package}",
    "apt": "sudo apt install {package}",
    "dnf": "sudo dnf install {package}",
    "zypper": "sudo zypper install {package}",
    "apk": "sudo apk add {package}",
    "brew": "brew install {package}",
    "winget": "winget install {package}",
}

# A distribution family, and the managers to try for it in order. The family is read from
# ``/etc/os-release``'s ``ID`` and then its ``ID_LIKE``, so a derivative is its parent
# unless it names itself here — Omarchy says ``ID_LIKE=arch`` and wants no row of its own,
# and neither does any other Arch or Debian spin. (Its ``omarchy-pkg-install`` is an
# interactive picker, not a line to paste, so it is deliberately not in MANAGERS.)
FAMILIES: dict[str, tuple[str, ...]] = {
    "arch": ("yay", "pacman"),
    "debian": ("apt",),
    "ubuntu": ("apt",),
    "fedora": ("dnf",),
    "rhel": ("dnf",),
    "centos": ("dnf",),
    "suse": ("zypper",),
    "opensuse": ("zypper",),
    "alpine": ("apk",),
}
OS_RELEASE = Path("/etc/os-release")


@dataclass(frozen=True)
class Machine:
    """Which machine's words to use for an install line. Both halves may be empty."""

    family: str = ""  # A key of FAMILIES, or "darwin"/"windows" — what names the package.
    manager: str = ""  # A key of MANAGERS that is actually on PATH — what runs it.


def os_release_families(text: str) -> list[str]:
    """``ID`` then every word of ``ID_LIKE``, in that order — the file's own precedence."""
    read: dict[str, str] = {}
    for line in text.splitlines():
        name, _, value = line.partition("=")
        read[name.strip()] = value.strip().strip('"').strip("'")
    names = [read.get("ID", ""), *read.get("ID_LIKE", "").split()]
    return [name for name in names if name]


def this_machine(
    *,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    os_release: Path = OS_RELEASE,
) -> Machine:
    """What this machine calls its packages and what would install one — "" for neither.

    A manager is only claimed when it is on PATH: suggesting ``brew install`` on a Mac
    without Homebrew is a second thing to go and install, said as if it were the answer.
    """
    if platform == "darwin":
        return Machine("darwin", "brew" if which("brew") else "")
    if platform.startswith("win"):
        return Machine("windows", "winget" if which("winget") else "")
    try:
        text = os_release.read_text(encoding="utf-8")
    except OSError:
        return Machine()
    for family in os_release_families(text):
        for manager in FAMILIES.get(family, ()):
            if which(manager):
                return Machine(family, manager)
    return Machine()


def install_line(packages: Mapping[str, str], machine: Machine) -> str:
    """The line this machine would run to install one of ``packages`` — "" when none fits.

    The package is this family's name for it, or the ``""`` entry, which is the name most
    of them use.
    """
    package = packages.get(machine.family) or packages.get("", "")
    if not package or machine.manager not in MANAGERS:
        return ""
    return MANAGERS[machine.manager].format(package=package)


def command_for(remedy: Remedy, machine: Machine) -> str:
    """What to type: the remedy's own line, or the one this machine's packages make."""
    return remedy.command or install_line(remedy.packages, machine)


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


def render(rows: Sequence[tuple[MachineCheck, Reading]], machine: Machine | None = None) -> str:
    """The text report: a heading per group, a state and the words, the remedy under it.

    ``machine`` decides what a remedy's packages come to; the default asks the machine this
    is running on, which is the only one a report is ever about.
    """
    found = this_machine() if machine is None else machine
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
        if reading.ok or check.remedy is None:
            continue
        lines.append(f"           {check.remedy.words}")
        command = command_for(check.remedy, found)
        if command:
            lines.append(f"           $ {command}")
        if check.remedy.url:
            lines.append(f"           {check.remedy.url}")
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


def to_record(check: MachineCheck, reading: Reading, machine: Machine) -> dict[str, object]:
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
            else {
                "words": remedy.words,
                # What to type *here*: the remedy's own line, or the one this machine's
                # package manager makes of its packages.
                "command": command_for(remedy, machine),
                "action": remedy.action,
                "url": remedy.url,
            }
        ),
    }


def commands(checks: Sequence[MachineCheck]) -> list[CliCommand]:
    def _show(context: CliContext, _args: Namespace) -> int:
        machine = this_machine()
        rows = [(check, check.probe()) for check in ordered(checks)]
        missing = [check for check, reading in rows if check.required and not reading.ok]
        context.report(
            {
                "checks": [to_record(check, reading, machine) for check, reading in rows],
                "failing": sum(1 for _check, reading in rows if not reading.ok),
                "required_failing": len(missing),
                "summary": summary(rows),
            },
            render(rows, machine),
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
