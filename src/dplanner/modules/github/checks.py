"""Whether this machine can reach GitHub the way this module does: ``gh``, and a session.

Both rows advise rather than block. A machine without ``gh`` still records typed branches
and PR numbers — DESIGN.md's *A machine without gh* flow is the whole design — so a
checklist that made it required would raise a modal for a degradation, which is the box
this checklist replaced.

Two rows rather than one because the remedies differ: installing the CLI and signing in are
different acts, and a row that said "gh is not right" would name neither.
"""

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.modules.github.gh import gh_refusal, which_gh

GH_URL = "https://cli.github.com"
# What each family calls it; the rest use "gh". `install_line` picks by this machine.
GH_PACKAGES = {"": "gh", "arch": "github-cli", "alpine": "github-cli", "windows": "GitHub.cli"}


def _installed() -> Reading:
    found = which_gh()
    return Reading(ok=found is not None, detail=found or "not on PATH")


def _signed_in() -> Reading:
    if which_gh() is None:
        return Reading(ok=False, detail="gh is not installed")
    refusal = gh_refusal(check_auth=True)
    return Reading(ok=refusal is None, detail=refusal or "signed in")


def checks() -> list[MachineCheck]:
    return [
        MachineCheck(
            id="github.gh",
            group="Git and GitHub",
            label="GitHub CLI (gh)",
            probe=_installed,
            remedy=Remedy(
                words="Branches and pull requests are typed rather than picked without it.",
                url=GH_URL,
                packages=GH_PACKAGES,
            ),
        ),
        MachineCheck(
            id="github.auth",
            group="Git and GitHub",
            label="gh signed in",
            probe=_signed_in,
            remedy=Remedy(
                words="Sign in so DPlanner can list branches and pull requests.",
                command="gh auth login",
                url=GH_URL,
            ),
        ),
    ]
