"""The agent skill, generated from the command registry.

An agent needs to be told what DPlanner is and what it can do. Writing that down by hand
would mean writing every command twice, and the copy would be wrong within a month — a skill
that describes a flag which no longer exists is worse than no skill, because it is believed.

So the skill is a **projection of the registry**: the hand-written part is the part a
registry cannot know (what a project is, how to work with the user), and everything else —
the command list, each command's arguments, the aspects — is rendered from the same objects
``dplanner --help`` renders. It cannot describe a command that does not exist.

**The output is a pure function of the registry.** Argparse wraps help text to the terminal's
width, so the same command run in two windows would produce two different files; the parsers
are built at a fixed width instead. The generated files go into version control, and a diff
that depends on who ran it is a diff nobody reads.
"""

import contextlib
from collections.abc import Sequence
from pathlib import Path

from dplanner.cli.command import CliCommand, CliRegistry
from dplanner.cli.main import PROG, build_tree
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import EDGE_KINDS
from dplanner.identity import APP_NAME, APP_VERSION

SKILL_DIR = ".claude/skills/dplanner"
SKILL_FILE = "SKILL.md"
REFERENCE_FILE = "reference.md"


def _gates(command: CliCommand) -> str:
    """The markers a verb wears in the index: `†` for a verb that reads the topology first,
    `‡` for one that reads the house format of what it writes. The legend names them."""
    topology = "†" if command.edits_graph is not None else ""
    return topology + ("‡" if _guide(command) is not None else "")


def _guide(command: CliCommand) -> str | None:
    """The house document this verb writes in the shape of — None for a verb that writes in
    nobody's shape, and for one the skill does not offer at all."""
    return command.reads_guide if command.in_skill else None


def _description(aspects: Sequence[AspectSpec]) -> str:
    # Projected from the build's aspect list like everything else in the skill, so it
    # cannot under-describe a build the way a hand-written enumeration did.
    carried = ", ".join(spec.label for spec in aspects)
    return (
        "Plan software work as a library of projects, each a graph of steps carrying "
        f"aspects ({carried}). Use when asked to plan, break down or estimate development "
        "work, or when a DPlanner project is present."
    )


def preamble() -> str:
    return (Path(__file__).parent / "skill_preamble.md").read_text(encoding="utf-8")


def generate(registry: CliRegistry, aspects: Sequence[AspectSpec]) -> dict[str, str]:
    """The skill, as filenames to content. Two files, because they are read differently.

    ``SKILL.md`` is what an agent reads first and has to be short enough to hold in mind, so
    its command list is an **index**: one line per noun naming its verbs. A summary per verb
    was a third of the file and said what ``reference.md`` and ``--help`` both already say —
    and an agent that needs one has two faster ways to get it than re-reading the skill.
    ``reference.md`` is every argument of every command, which is a lookup, not a read.
    """
    return {
        SKILL_FILE: _skill(registry, aspects),
        REFERENCE_FILE: _reference(registry),
    }


def _skill(registry: CliRegistry, aspects: Sequence[AspectSpec]) -> str:
    lines = [
        "---",
        f"name: {PROG}",
        f"description: {_description(aspects)}",
        "---",
        "",
        f"# {APP_NAME}",
        "",
        preamble().rstrip(),
        "",
        "## Where the project is",
        "",
        "Commands find the current project from the working directory, in this order:",
        "`--project NAME` (or `$DPLANNER_PROJECT`, which Run Agent sets in the agent's",
        "shell); a walk **up from the working directory** for `project.dproj`, or for the",
        "`.dplanner` index a plan repository keeps at its root — one project directory per",
        "line; and the working directory's git repository being one a library project",
        "plans — its `origin` is the project's code repository, so an agent in the code",
        "checkout, or in a worktree of it, needs no configuration, and the first call from",
        "a checkout records where the code is on this machine. The library of projects is",
        "per user; another one can be named with `--library PATH` or `$DPLANNER_LIBRARY`.",
        "",
        "## Commands",
        "",
    ]
    for noun, commands in registry.groups().items():
        offered = [command for command in commands if command.in_skill]
        if not offered:  # A noun whose every verb is kept out is not a noun here at all.
            continue
        verbs = " · ".join(command.path[1] + _gates(command) for command in offered)
        lines.append(f"- `{PROG} {noun}` — {verbs}")
    lines += [
        "",
        f"† reads the topology first: `{PROG} topology show <project>` once, before it runs.",
    ]
    # A house document is the second door (`cli/gate.py`), and its legend is projected the
    # same way the daggers are: one line per document any offered verb writes in the shape
    # of, so a second one could never arrive unannounced.
    guides = {guide for command in registry.commands() if (guide := _guide(command)) is not None}
    for verb in sorted(guides):
        lines.append(f"‡ reads the house format first: `{PROG} {verb}` once, before it runs.")
    lines += [
        "",
        f"`{PROG} <noun> <verb> --help` names a verb's arguments and is the fastest way to"
        f" check one; every argument of every command is also in"
        f" [{REFERENCE_FILE}]({REFERENCE_FILE}).",
        "",
        "## Aspects a step can carry",
        "",
    ]
    for aspect in aspects:
        lines.append(f"- **{aspect.label}** (`{aspect.id}`) — {aspect.summary}")
    lines += [
        "",
        "## Edge kinds",
        "",
    ]
    for kind, orders in sorted(EDGE_KINDS.items()):
        meaning = "orders the graph; cycles are refused" if orders else "a plain link"
        lines.append(f"- `{kind}` — {meaning}")
    lines += ["", f"<!-- generated by {PROG} {APP_VERSION}; edits are overwritten -->", ""]
    return "\n".join(lines)


def _reference(registry: CliRegistry) -> str:
    _parser, verb_parsers = build_tree(registry)
    lines = [
        f"# {PROG} reference",
        "",
        f"Generated from {APP_NAME}'s command registry. Every command, every argument.",
        "",
    ]
    for command in registry.commands():
        if not command.in_skill:
            continue
        lines += [f"## `{PROG} {command.id}`", "", command.summary, "", "```"]
        # The parser's own help, examples included: one rendering, so the reference and
        # `--help` cannot come to disagree.
        lines.append(verb_parsers[command.id].format_help().rstrip())
        lines.append("```")
        lines.append("")
    lines.append(f"<!-- generated by {PROG} {APP_VERSION}; edits are overwritten -->")
    lines.append("")
    return "\n".join(lines)


# -- installing the skill -----------------------------------------------------------------------
#
# Where it goes, how it stands, and writing and removing it. Installing the *program* — this
# skill together with the ``dplanner`` command and the desktop launcher — is ``cli/install.py``,
# which is built from these and from ``cli/desktop.py``'s.


def target_dir(*, user: bool, here: Path | None = None) -> Path:
    """Where the skill goes: this user's home, or the directory being worked in."""
    base = Path.home() if user else (here or Path.cwd())
    return base / SKILL_DIR


def status(files: dict[str, str], directory: Path) -> str:
    """``installed``, ``stale`` or ``missing`` — what an "Update…" label reads from."""
    for name, content in files.items():
        path = directory / name
        if not path.is_file():
            return "missing"
        if path.read_text(encoding="utf-8") != content:
            return "stale"
    return "installed"


def install(files: dict[str, str], directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in sorted(files.items()):
        path = directory / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def uninstall(files: dict[str, str], directory: Path) -> list[Path]:
    """Remove exactly the files install would write — never anything the user added.

    The directory goes too once it is empty; a directory holding somebody's own files
    survives.
    """
    removed = []
    for name in sorted(files):
        path = directory / name
        if path.is_file():
            path.unlink()
            removed.append(path)
    with contextlib.suppress(OSError):
        directory.rmdir()
    return removed


def commands(aspects: Sequence[AspectSpec], registry: CliRegistry) -> list[CliCommand]:
    """The skill verbs: show, install, uninstall, status.

    They take the registry they describe, which is the same registry they are registered
    into — the composition root closes the loop, and nothing here has to go looking.
    """
    from argparse import ArgumentParser, Namespace

    from dplanner.cli.command import CliContext

    def files() -> dict[str, str]:
        return generate(registry, aspects)

    def show(context: CliContext, _args: Namespace) -> int:
        context.report(files(), files()[SKILL_FILE])
        return 0

    def configure(parser: ArgumentParser) -> None:
        where = parser.add_mutually_exclusive_group()
        where.add_argument(
            "--user",
            action="store_true",
            help=f"install into ~/{SKILL_DIR} (the default)",
        )
        where.add_argument(
            "--repo",
            action="store_true",
            help=f"install into ./{SKILL_DIR}, so it travels with the repository",
        )

    def where(args: Namespace) -> Path:
        return target_dir(user=not args.repo)

    def do_install(context: CliContext, args: Namespace) -> int:
        written = install(files(), where(args))
        context.report(
            {"installed": [str(path) for path in written]},
            "\n".join(str(path) for path in written),
        )
        return 0

    def do_uninstall(context: CliContext, args: Namespace) -> int:
        removed = uninstall(files(), where(args))
        context.report(
            {"removed": [str(path) for path in removed]},
            "\n".join(str(path) for path in removed) if removed else "nothing installed",
        )
        return 0

    def do_status(context: CliContext, args: Namespace) -> int:
        # Imported here rather than at the top: cli/install.py reads this module.
        from dplanner.cli.install import path_hint

        directory = where(args)
        state = status(files(), directory)
        hint = path_hint()
        text = f"{state}  {directory}"
        if hint is not None:
            text += f"\ndplanner is not on PATH — fix with: {hint}"
        context.report(
            {"status": state, "directory": str(directory), "cli_on_path": hint is None},
            text,
        )
        return 0

    return [
        CliCommand(
            path=("skill", "show"),
            summary="Print the agent skill for this build, without installing it.",
            run=show,
            needs_library=False,
            examples=(f"{PROG} skill show",),
        ),
        CliCommand(
            path=("skill", "install"),
            summary="Write the agent skill so a coding agent can find it.",
            configure=configure,
            run=do_install,
            needs_library=False,
            examples=(f"{PROG} skill install", f"{PROG} skill install --repo"),
        ),
        CliCommand(
            path=("skill", "uninstall"),
            summary="Remove the installed agent skill.",
            configure=configure,
            run=do_uninstall,
            needs_library=False,
            examples=(f"{PROG} skill uninstall",),
        ),
        CliCommand(
            path=("skill", "status"),
            summary="Whether the installed skill matches this build.",
            configure=configure,
            run=do_status,
            needs_library=False,
            examples=(f"{PROG} skill status",),
        ),
    ]
