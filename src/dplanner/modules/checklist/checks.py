"""The rows no feature owns: git, a reachable internet, and the Azure CLI.

**git is required.** A plan lives in a git repository and DPlanner derives the repository
root of every project, so a machine without git cannot open a plan at all. It is also
cheap enough to ask at every start, which is what ``required`` costs a machine.

**Internet and az advise.** Planning works on a plane; only the GitHub and Confluence
features want the network, and they say so where they bite. ``az`` is here because a
developer asked for it and it is honest about itself: DPlanner never calls it, and its row
and its group say as much rather than implying a machine is short of something.

Every probe's ``which``, ``run`` and ``reach`` are arguments so a test never touches the
real machine — the ``launcher.is_installed`` convention.
"""

import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable

from dplanner.cli.checklist import MachineCheck, Reading, Remedy

Which = Callable[[str], str | None]
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
Reach = Callable[[], str]

# One capped HEAD at the host the application actually talks to, asked only when somebody
# is looking: this probe is not required, so it never runs at start and a launch makes no
# request of its own.
REACH_URL = "https://api.github.com/"
REACH_TIMEOUT_S = 3.0

# Where to read about a tool this checklist cannot install for you. A row names one only
# when the address is certain: a guessed link is a worse answer than no link.
GIT_URL = "https://git-scm.com/downloads"
AZ_URL = "https://learn.microsoft.com/cli/azure/install-azure-cli"


def _run(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _reach() -> str:
    """Empty when the host answered, else why it did not. Never raises."""
    request = urllib.request.Request(REACH_URL, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=REACH_TIMEOUT_S):
            return ""
    except urllib.error.HTTPError:
        return ""  # It answered; what it answered is not this question.
    except (urllib.error.URLError, OSError, ValueError) as error:
        return f"{type(error).__name__}"


def _version(command: list[str], run: Runner) -> str:
    try:
        result = run(command)
    except OSError as error:
        return f"could not be run ({type(error).__name__})"
    return result.stdout.strip().splitlines()[0] if result.returncode == 0 else ""


def _git(which: Which, run: Runner) -> Reading:
    if which("git") is None:
        return Reading(ok=False, detail="not on PATH")
    said = _version(["git", "--version"], run)
    return Reading(ok=bool(said), detail=said or "installed, but would not say its version")


def _internet(reach: Reach) -> Reading:
    why = reach()
    return Reading(
        ok=not why, detail=f"{REACH_URL} answered" if not why else f"unreachable ({why})"
    )


def _az(which: Which, run: Runner) -> Reading:
    if which("az") is None:
        return Reading(ok=False, detail="not installed — only needed if your work deploys to Azure")
    try:
        result = run(["az", "account", "show", "--output", "none"])
    except OSError as error:
        return Reading(ok=False, detail=f"installed, but could not be run ({type(error).__name__})")
    if result.returncode != 0:
        return Reading(ok=False, detail="installed, but not signed in")
    return Reading(ok=True, detail="installed and signed in")


def checks(
    *,
    which: Which = shutil.which,
    run: Runner | None = None,
    reach: Reach | None = None,
) -> list[MachineCheck]:
    runner = _run if run is None else run
    reacher = _reach if reach is None else reach
    return [
        MachineCheck(
            id="git.installed",
            group="Git and GitHub",
            label="git",
            probe=lambda: _git(which, runner),
            remedy=Remedy(
                words="Every plan lives in a git repository; DPlanner cannot open one without it.",
                url=GIT_URL,
                packages={"": "git", "windows": "Git.Git"},
            ),
            required=True,
        ),
        MachineCheck(
            id="network.internet",
            group="Services",
            label="Internet reachable",
            probe=lambda: _internet(reacher),
            remedy=Remedy(
                words="Pull requests, branches and external spec sources need it; "
                "planning does not.",
            ),
        ),
        MachineCheck(
            id="az.installed",
            group="Other tools",
            label="Azure CLI (az)",
            probe=lambda: _az(which, runner),
            remedy=Remedy(
                # No packages: az is a Microsoft repository or a install script on most
                # distributions, and `apt install azure-cli` on a stock machine simply
                # fails. The page says the truth for whichever one this is.
                words="DPlanner never calls az — this row is here for the work you plan, "
                "not for DPlanner.",
                command="az login",
                url=AZ_URL,
            ),
        ),
    ]
