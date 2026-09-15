"""A project link: everything a colleague needs to set this project up, as one artefact.

Joining a project means knowing three things — which plan repository holds it, where in
that repository it sits, and which code it plans — and until now the only way to pass them
on was to write them in a message. A **project link** is those facts as data, so the
receiving window can clone, attach and record the checkout without anybody retyping a URL.

It travels two ways, and they carry exactly the same fields:

``a file``      ``search-rewrite.dlink`` — JSON, the shape every other file this application
                writes has (FORMAT.md's *The project link*). Mail it, drop it in a chat,
                commit it beside a README.
``a link``      ``dplanner://project?plan=…&path=…&code=…`` — one line to paste, which is
                also what the Share dialog's QR code encodes.

**Readable on purpose.** The query form spells the repositories out rather than packing
them into a blob, because a person asked to open somebody else's link should be able to see
what it points at before they open it. That is worth the extra characters.

Nothing here touches the library, clones anything or opens a project: it reads and writes
the description. :func:`find_clone` is the one exception that looks at the disk, and only
to answer *do I already have this repository?* — the question that decides whether a clone
is needed at all.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from dplanner.core.fsio import slugify
from dplanner.core.storage.locations import canonical_remote, origin_url, remote_label
from dplanner.domain.model import Project
from dplanner.domain.repositories import RepositoryFacts

SUFFIX = ".dlink"
SCHEME = "dplanner"
HOST = "project"  # dplanner://project?… — the noun, so a later link kind needs no new scheme.
MARKER = "project-link"  # The file's own "this is what I am" key.
FORMAT = 1
# The path of a plan repository that *is* one project — the same spelling `domain/plan_repo`
# uses for a listing's root-level entry, so the two cannot disagree.
ROOT = "."


class LinkError(Exception):
    """Why a link cannot be made or cannot be read, in words a person can act on."""


@dataclass(frozen=True)
class ProjectLink:
    """One project as somebody else's machine needs to hear about it.

    ``plan_remote`` and ``plan_path`` are the pair that locates the plan; everything else
    is what the receiving surface can *say* about it before a single byte is cloned, which
    is what lets the wizard name the project it is about to set up.
    """

    plan_remote: str
    plan_path: str = ROOT
    project_id: str = ""
    title: str = ""
    summary: str = ""
    code_remote: str = ""

    @property
    def plan_label(self) -> str:
        return remote_label(self.plan_remote)

    @property
    def code_label(self) -> str:
        return remote_label(self.code_remote) if self.code_remote else ""

    @property
    def name(self) -> str:
        """What to call the project before it is open: its title, else its folder."""
        if self.title:
            return self.title
        return Path(self.plan_path).name if self.plan_path != ROOT else self.plan_label

    @property
    def filename(self) -> str:
        return f"{slugify(self.name, fallback='project')}{SUFFIX}"


def link_for(project: Project, directory: Path, facts: RepositoryFacts) -> ProjectLink:
    """The link that would bring ``project`` to somebody else's machine.

    Raises :class:`LinkError` where there is nothing to share: a plan that is not in a
    repository at all, or one whose repository is local-only — nobody can clone a folder
    that exists on one laptop, and a link that names one would fail on arrival rather than
    here, where the person can still do something about it.
    """
    root = facts.plan_root
    if root is None:
        raise LinkError("this plan is not in a git repository — there is nothing to clone")
    if not facts.plan_remote:
        raise LinkError(
            f"{root.name} has no remote, so nobody else can clone it — publish it to "
            "GitHub from Project ▸ Settings… first"
        )
    return ProjectLink(
        plan_remote=facts.plan_remote,
        plan_path=relative_path(root, directory),
        project_id=project.id,
        title=project.title,
        summary=project.summary,
        code_remote=facts.repository,
    )


def relative_path(root: Path, directory: Path) -> str:
    """Where a project sits inside its plan repository, as the link spells it."""
    relative = directory.resolve().relative_to(root.resolve()).as_posix()
    return relative or ROOT


def project_directory(root: Path, link: ProjectLink) -> Path:
    """The project's directory inside a clone of its plan repository."""
    return root if link.plan_path == ROOT else root / link.plan_path


def find_clone(roots: Iterable[Path], remote: str) -> Path | None:
    """The first of ``roots`` that is a clone of ``remote`` — the reason most links need
    no clone at all, because a team shares one plan repository."""
    wanted = canonical_remote(remote)
    for root in roots:
        if root.is_dir() and canonical_remote(origin_url(root)) == wanted:
            return root
    return None


def find_checkout(recorded: Iterable[tuple[str, Path | None]], remote: str) -> Path | None:
    """A checkout of ``remote`` this machine already has, from the ``(code repository,
    checkout)`` pairs the library holds.

    :func:`find_clone`'s sibling, one repository over: a team's second project in the same
    code needs no second clone, and offering the checkout they already use is the
    difference between a wizard that knows this machine and one that asks twice.
    """
    wanted = canonical_remote(remote)
    for repository, checkout in recorded:
        if checkout is not None and repository and canonical_remote(repository) == wanted:
            return checkout
    return None


# -- the file -------------------------------------------------------------------------------


def document(link: ProjectLink) -> dict[str, Any]:
    """The link as the ``.dlink`` file's JSON. Absence encodes the default, as everywhere
    else in this format: an empty field writes no key."""
    found: dict[str, Any] = {
        SCHEME: MARKER,
        "format": FORMAT,
        "plan": {"remote": link.plan_remote, "path": link.plan_path},
    }
    if link.project_id:
        found["id"] = link.project_id
    if link.title:
        found["title"] = link.title
    if link.summary:
        found["summary"] = link.summary
    if link.code_remote:
        found["code"] = {"remote": link.code_remote}
    return found


def document_text(link: ProjectLink) -> str:
    """The bytes of a ``.dlink``: two-space indent, sorted keys, one trailing newline —
    `FORMAT.md`'s *Bytes on disk*, because this file is part of that format too."""
    return json.dumps(document(link), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def read_document(raw: object) -> ProjectLink:
    """A parsed ``.dlink`` as a link. Raises :class:`LinkError` on anything else."""
    if not isinstance(raw, dict) or raw.get(SCHEME) != MARKER:
        raise LinkError("this is not a DPlanner project link")
    _check_format(raw.get("format", FORMAT))
    plan = raw.get("plan")
    if not isinstance(plan, dict):
        raise LinkError("the link names no plan repository")
    code = raw.get("code")
    return _build(
        plan_remote=_text(plan.get("remote")),
        plan_path=_text(plan.get("path")) or ROOT,
        project_id=_text(raw.get("id")),
        title=_text(raw.get("title")),
        summary=_text(raw.get("summary")),
        code_remote=_text(code.get("remote")) if isinstance(code, dict) else "",
    )


def read_file(path: Path) -> ProjectLink:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise LinkError(f"{path.name} could not be read — {error}") from error
    except json.JSONDecodeError as error:
        raise LinkError(f"{path.name} is not a readable link — {error}") from error
    return read_document(raw)


# -- the link -------------------------------------------------------------------------------


def encode(link: ProjectLink) -> str:
    """The one-line form: ``dplanner://project?plan=…``.

    Built by hand rather than with ``urlencode`` so that a remote's ``/`` and ``:`` survive
    as themselves — the whole point of the readable form is that a person can see which
    repository they are being sent to without decoding anything.
    """
    fields = [
        ("plan", link.plan_remote),
        ("path", link.plan_path),
        ("code", link.code_remote),
        ("id", link.project_id),
        ("title", link.title),
        ("summary", link.summary),
    ]
    query = "&".join(f"{key}={quote(value, safe=':/@._-')}" for key, value in fields if value)
    return f"{SCHEME}://{HOST}?{query}&format={FORMAT}"


def decode(text: str) -> ProjectLink:
    """Read the one-line form. Raises :class:`LinkError` on anything else."""
    parts = urlsplit(text.strip())
    if parts.scheme.lower() != SCHEME or parts.netloc.lower() != HOST:
        raise LinkError(f"this is not a {SCHEME}://{HOST} link")
    fields = dict(parse_qsl(parts.query, keep_blank_values=True))
    _check_format(fields.get("format", FORMAT))
    return _build(
        plan_remote=fields.get("plan", ""),
        plan_path=fields.get("path", "") or ROOT,
        project_id=fields.get("id", ""),
        title=fields.get("title", ""),
        summary=fields.get("summary", ""),
        code_remote=fields.get("code", ""),
    )


def read(text: str) -> ProjectLink:
    """A link however it arrived: pasted as a line, or named as a file on disk.

    One reader because one field takes both — what somebody sends is a link *or* an
    attachment and the person receiving it should not have to know which kind of thing
    they are holding.
    """
    said = text.strip().strip('"').strip("'")
    if not said:
        raise LinkError("paste a project link, or choose a .dlink file")
    if "://" in said or said.lower().startswith(f"{SCHEME}:"):
        # Anything shaped like a URL is answered by `decode`, which names the scheme it
        # wanted — a repository's own https:// address is the commonest wrong paste, and
        # "no such file" would be the wrong thing to tell somebody holding one.
        return decode(said)
    path = Path(said).expanduser()
    if path.is_file():
        return read_file(path)
    if path.suffix == SUFFIX or "/" in said or "\\" in said:
        raise LinkError(f"no such file: {said}")
    raise LinkError(f"this is neither a {SCHEME}:// link nor a {SUFFIX} file")


# -- shared ---------------------------------------------------------------------------------


def _build(**fields: str) -> ProjectLink:
    link = ProjectLink(**fields)
    if not link.plan_remote:
        raise LinkError("the link names no plan repository")
    return link


def _check_format(raw: object) -> None:
    try:
        found = int(str(raw))
    except ValueError as error:
        raise LinkError(f"unreadable link format: {raw!r}") from error
    if found > FORMAT:
        raise LinkError(
            f"this link was written by a newer DPlanner (format {found}) — update to open it"
        )


def _text(raw: object) -> str:
    return str(raw) if isinstance(raw, str | int) else ""
