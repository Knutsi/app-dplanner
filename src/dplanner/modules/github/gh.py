"""The module's own door to the ``gh`` CLI — the only GitHub dependency, and Qt-free.

``core.storage.github`` also wraps ``gh``, but that is a concrete storage provider and
off-limits to a feature module (architecture rule 8), so this file owns its own subprocess
calls and its own ``owner/repo`` parsing. The overlap is small and deliberate: what the
storage layer parses is the *workspace's* origin, what this parses is the *product's*
repository URL, and neither should learn about the other.

Everything here degrades to a refusal rather than an exception a caller has to guess at:
``gh_refusal()`` says in one line why gh cannot be used, and ``GhError`` carries gh's own
stderr when a real invocation fails.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

GH_TIMEOUT = 20.0  # seconds; listing and viewing are small requests.
PR_LIST_LIMIT = 100

PR_FIELDS = "number,title,state,url,headRefName"


class GhError(Exception):
    """A ``gh`` invocation failed; the message is gh's own first stderr line."""


@dataclass(frozen=True)
class PrInfo:
    number: int
    title: str
    state: str  # "open" | "merged" | "closed", lowercased at this boundary.
    url: str
    head_ref: str


def which_gh() -> str | None:
    """The ``gh`` executable, or None when it is not installed."""
    return shutil.which("gh")


def gh_refusal(*, check_auth: bool = False) -> str | None:
    """Why ``gh`` cannot be used right now, in one line — or None when it can.

    The auth probe is opt-in because it spawns a subprocess: the CLI skips it and lets the
    real command's failure be the probe, while a background caller checks first so it can
    stop retrying rather than fail every tick.
    """
    gh = which_gh()
    if gh is None:
        return "gh not found on PATH — GitHub features need the GitHub CLI"
    if check_auth:
        status = subprocess.run([gh, "auth", "status"], capture_output=True, check=False)
        if status.returncode != 0:
            return "gh is not authenticated — run `gh auth login`"
    return None


def parse_repo(url: str) -> str | None:
    """``owner/repo`` from a GitHub URL, https or ssh form — None for anything else."""
    if "github.com" not in url:
        return None
    tail = url.split("github.com", 1)[-1].lstrip(":/").removesuffix(".git").rstrip("/")
    parts = tail.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return "/".join(parts)


def pr_number_from(ref: str) -> int | None:
    """The PR number in ``12``, ``#12`` or a ``…/pull/12`` URL — None when there is none.

    Only the first word counts, so a picker line like ``#12  Add login flow`` parses too.
    """
    words = ref.split()
    candidate = words[0].lstrip("#") if words else ""
    if "/pull/" in candidate:
        candidate = candidate.split("/pull/", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return int(candidate) if candidate.isdigit() else None


def list_prs(repo: str) -> list[PrInfo]:
    """The repository's pull requests, every state, newest first (capped at 100)."""
    output = _run(
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        str(PR_LIST_LIMIT),
        "-R",
        repo,
        "--json",
        PR_FIELDS,
    )
    return [_pr_info(row) for row in json.loads(output)]


def view_pr(repo: str, number: int) -> PrInfo | None:
    """One pull request, or None when the repository has no PR with that number."""
    try:
        output = _run("pr", "view", str(number), "-R", repo, "--json", PR_FIELDS)
    except GhError as error:
        if "could not resolve" in str(error).lower() or "no pull requests" in str(error).lower():
            return None
        raise
    return _pr_info(json.loads(output))


def list_branches(repo: str) -> list[str]:
    """The repository's branch names, as GitHub lists them."""
    output = _run("api", f"repos/{repo}/branches?per_page=100", "--paginate", "--jq", ".[].name")
    return [line for line in output.splitlines() if line]


def _pr_info(row: dict[str, Any]) -> PrInfo:
    return PrInfo(
        number=int(row.get("number", 0) or 0),
        title=str(row.get("title", "")),
        state=str(row.get("state", "")).lower(),
        url=str(row.get("url", "")),
        head_ref=str(row.get("headRefName", "")),
    )


def _run(*args: str) -> str:
    gh = which_gh()
    if gh is None:
        raise GhError("gh not found on PATH — GitHub features need the GitHub CLI")
    try:
        result = subprocess.run(
            [gh, *args], capture_output=True, text=True, check=False, timeout=GH_TIMEOUT
        )
    except subprocess.TimeoutExpired as error:
        raise GhError(f"gh {' '.join(args[:2])}: timed out") from error
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise GhError(detail[0] if detail else f"gh {' '.join(args[:2])} failed")
    return result.stdout
