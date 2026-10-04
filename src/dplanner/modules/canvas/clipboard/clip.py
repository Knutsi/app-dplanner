"""What a copied step is, and how a copy is pasted.

Qt-free, because the window's Cut/Copy/Paste/Duplicate and ``dplanner step duplicate`` are
one function: a step is read into a self-contained :class:`StepClip`, and a paste turns a
list of them into **one** command — the same object either surface applies, so a paste is
one undo step in a window and one transaction on the command line.

**A copy is a clone, never the same step.** Every clone has a fresh id and an empty folder
name, so the store mints it a directory of its own; the copied id survives only long enough
to remap the links *between* copied steps. Those are the only links a copy carries: the
pasted set keeps its internal arrangement and arrives disconnected from everything outside
it, whether it lands in the same project or another. Wiring it in is the user's next move,
not something a paste guesses at.

**A stack is copied whole or not at all.** A copy of every member of a stack pastes as a new
stack — a fresh id, the chain carried by the links between copies, the seat on its first
member — and a copy of some of them pastes as plain steps: a stack is a line of steps, and
part of one is just steps. Each clip remembers the frame it stood in, so a Duplicate lands a
whole stack below its frame and a part of one beside it, never on a member it left behind.

**Files ride in the payload.** A cut removes the step and the next autosave deletes its
directory, so a later paste has nowhere else to read an attachment from. The bytes are
written after the command is applied — an attachment is not undoable, the trade
``FORMAT.md`` makes for every file area — which is why :func:`write_files` is a separate
step the caller runs once the clones exist.

**A module with a say in what a copy carries hands in a policy.** Aspect data is opaque to
this file and copied verbatim, but some facts cannot honestly travel: an id minted per
project, the state of a shell somebody is running, and a step id an aspect names. Each owner
exports a :data:`PastePolicy` from its Qt-free half, the composition root assembles the
tuple, and the policies see the whole batch before any command exists — so ids minted for
three pasted steps cannot collide with each other — together with the old→new id map the
links are remapped by, for an aspect that names other steps.
"""

import base64
import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.domain.assets import area_assets
from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    SetEdgesCommand,
)
from dplanner.domain.model import EDGE_KINDS, Library, NodeId, Project, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.modules.canvas.layouts.placement import below, positions
from dplanner.modules.canvas.layouts.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.canvas.layouts.positions import (
    STACK_KEY,
    node_size,
    read_size,
    write_member,
    write_position,
)
from dplanner.modules.canvas.layouts.sorts import H_GAP, V_GAP
from dplanner.modules.canvas.stacks.stack import Rect, chain, frame, mint_id, read_stacks

# The clipboard format. A vendor type, so nothing but this application ever mistakes the
# payload for text — the titles travel beside it as ``text/plain`` for pasting elsewhere.
MIME_TYPE = "application/x-dplanner-steps+json"

# A module's hands on steps about to arrive in ``project``: called with the clones before
# they exist anywhere, free to rewrite or drop its own entry on each, and with each copied
# step's id mapped to its clone's — the map the links between copies are remapped by.
type PastePolicy = Callable[[Project, list[Step], Mapping[StepId, StepId]], None]


@dataclass(frozen=True)
class StepClip:
    """One copied step, complete in itself."""

    id: StepId  # The source id — only so links between copied steps can be remapped.
    title: str
    edges: dict[str, list[StepId]]
    module_data: dict[str, dict[str, Any]]
    module_text: dict[str, str]
    files: dict[str, dict[str, bytes]]  # Module id → area-relative name → bytes.
    # Where it sat when copied — stored or ambient — so a block keeps its arrangement.
    x: float
    y: float
    # The frame of the stack it stood in, if any: where a Duplicate lands clear of it.
    frame: Rect | None = None


def clip(
    library: Library, files: FilesFor, file_modules: Sequence[str], step_ids: Sequence[StepId]
) -> list[StepClip]:
    """Read these steps into clips, in the given order. A member keeps its stack only when
    every member of that stack is copied with it."""
    placed: dict[NodeId, dict[StepId, tuple[float, float]]] = {}
    frames: dict[StepId, Rect] = {}  # A member's stack's frame, by the member's id.
    whole: set[StepId] = set()  # The members of every stack copied whole.
    copied = set(step_ids)
    clips = []
    for step_id in step_ids:
        step = library.step(step_id)
        project = library.project_of(step_id)
        if project.id not in placed:
            placed[project.id] = seats = positions(library, project)
            sizes = {s.id: node_size(s) for s in project.steps}
            for stack in read_stacks(project.steps):
                box = frame(stack, seats[stack.head], sizes.__getitem__)
                frames.update((member, box) for member in stack.members)
                if copied.issuperset(stack.members):
                    whole.update(stack.members)
        x, y = placed[project.id][step_id]
        module_data = copy.deepcopy(step.module_data)
        if step_id in frames and step_id not in whole:
            module_data[POSITION_KEY].pop(STACK_KEY)
        clips.append(
            StepClip(
                id=step.id,
                title=step.title,
                edges={kind: list(targets) for kind, targets in step.edges.items()},
                module_data=module_data,
                module_text=dict(step.module_text),
                files=_files_of(files, step.id, file_modules),
                x=x,
                y=y,
                frame=frames.get(step_id),
            )
        )
    return clips


def _files_of(
    files: FilesFor, step_id: StepId, file_modules: Sequence[str]
) -> dict[str, dict[str, bytes]]:
    held: dict[str, dict[str, bytes]] = {}
    for module_id in file_modules:
        names = area_assets(files, step_id, module_id)
        if not names:
            continue
        area = files(step_id, module_id)
        blobs = {name: data for name in names if (data := area.read_bytes(name)) is not None}
        if blobs:
            held[module_id] = blobs
    return held


def to_json(clips: Sequence[StepClip]) -> bytes:
    """The clipboard payload. Bytes are base64, since JSON has no other place for them."""
    return json.dumps(
        {
            "steps": [
                {
                    "id": c.id,
                    "title": c.title,
                    "edges": c.edges,
                    "module_data": c.module_data,
                    "module_text": c.module_text,
                    "files": {
                        module_id: {
                            name: base64.b64encode(data).decode("ascii")
                            for name, data in blobs.items()
                        }
                        for module_id, blobs in c.files.items()
                    },
                    "x": c.x,
                    "y": c.y,
                    **({"frame": list(c.frame)} if c.frame is not None else {}),
                }
                for c in clips
            ]
        }
    ).encode("utf-8")


def from_json(data: bytes) -> list[StepClip]:
    """The clips a payload holds — none for anything that is not one of ours.

    Tolerant on purpose: the clipboard is shared with every other program and with older
    and newer builds of this one, so a payload that does not parse is "nothing to paste",
    never an error.
    """
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return []
    clips = []
    for entry in raw["steps"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        clips.append(
            StepClip(
                id=entry["id"],
                title=str(entry.get("title", "")),
                edges={
                    str(kind): [str(t) for t in targets]
                    for kind, targets in _dict(entry.get("edges")).items()
                    if isinstance(targets, list)
                },
                module_data={
                    str(k): dict(v)
                    for k, v in _dict(entry.get("module_data")).items()
                    if isinstance(v, dict)
                },
                module_text={str(k): str(v) for k, v in _dict(entry.get("module_text")).items()},
                files={
                    str(module_id): {
                        str(name): base64.b64decode(text)
                        for name, text in _dict(blobs).items()
                        if isinstance(text, str)
                    }
                    for module_id, blobs in _dict(entry.get("files")).items()
                },
                x=_number(entry.get("x")),
                y=_number(entry.get("y")),
                frame=_rect(entry.get("frame")),
            )
        )
    return clips


def _dict(value: object) -> dict[Any, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _rect(value: object) -> Rect | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    x, y, w, h = (_number(part) for part in value)
    return x, y, w, h


def paste(
    library: Library,
    project_id: NodeId,
    clips: Sequence[StepClip],
    *,
    anchor: tuple[float, float] | None,
    policies: Sequence[PastePolicy] = (),
    verb: str = "Paste",
) -> tuple[Command, list[Step]]:
    """The one command that puts clones of ``clips`` into ``project_id``, and the clones.

    ``anchor`` is where the block's top-left goes — the canvas's last click. None places
    every clone one row below where its original sat, which is what Duplicate means and what
    a paste on a canvas nobody has clicked falls back to — a whole stack one row below its
    frame, and a step copied out of a stack beside the frame. ``verb`` names the undo entry.

    Each stack copied whole gets a fresh id, so the copy is a stack of its own and never
    joins its original; the first in its chain takes the seat.

    The clones' aspects are set on the objects before the add — the node does not exist yet,
    so a command per entry would only lengthen the composite — but the links go through
    :class:`SetEdgesCommand`, so the model validates them and every view hears of them. Only
    links between the clips survive, remapped; a link to anything outside the set is dropped.
    """
    if not clips:
        raise ValueError("nothing to paste")
    project = library.project(project_id)
    left, top = min(c.x for c in clips), min(c.y for c in clips)
    by_id = {c.id: c for c in clips}
    stacked: dict[str, list[StepId]] = {}
    for c in clips:
        if old := _stack_of(c):
            stacked.setdefault(old, []).append(c.id)
    renamed = {old: mint_id() for old in stacked}
    firsts = {
        chain(members, lambda m: by_id[m].edges.get("requires", []))[0][0]
        for members in stacked.values()
    }
    clones: list[Step] = []
    for c in clips:
        clone = Step(title=c.title)
        clone.module_data = copy.deepcopy(c.module_data)
        clone.module_text = dict(c.module_text)
        stack = renamed.get(_stack_of(c), "")
        if anchor is not None:
            x, y = anchor[0] + c.x - left, anchor[1] + c.y - top
        elif c.frame is None:
            x, y = below(c.x, c.y, node_size(clone)[1])
        elif stack:
            x, y = c.x, c.y + c.frame[3] + V_GAP
        else:
            x, y = c.frame[0] + c.frame[2] + H_GAP, c.y
        # The copy keeps the size its original was given, like every other stored fact.
        size = read_size(clone)
        clone.module_data[POSITION_KEY] = (
            write_member(stack, size)
            if stack and c.id not in firsts
            else write_position(x, y, size, stack=stack)
        )
        clones.append(clone)
    remapped = {c.id: clone.id for c, clone in zip(clips, clones, strict=True)}
    for policy in policies:
        policy(project, clones, remapped)

    commands: list[Command] = [AddNodeCommand(project_id, clone) for clone in clones]
    for c, clone in zip(clips, clones, strict=True):
        for kind, targets in c.edges.items():
            if kind not in EDGE_KINDS:
                continue  # A kind this build does not know cannot be validated; skip it.
            wanted = [remapped[t] for t in targets if t in remapped]
            if wanted:
                # A clone carries the links its originals have, as they are: a copy chooses
                # no link, so no rule judges one (``Library.set_edges`` on ``rules``).
                commands.append(SetEdgesCommand(clone.id, kind, wanted, rules=False))
    label = f"{verb} Step" if len(clones) == 1 else f"{verb} {len(clones)} Steps"
    return CompositeCommand(label, commands), clones


def _stack_of(c: StepClip) -> str:
    stack = c.module_data.get(POSITION_KEY, {}).get(STACK_KEY)
    return stack if isinstance(stack, str) else ""


def write_files(files: FilesFor, pasted: Sequence[tuple[Step, StepClip]]) -> None:
    """Put each clip's files beside its clone. After the command, because the area of a
    step that is not in the library yet has no directory to settle."""
    for clone, c in pasted:
        for module_id, blobs in c.files.items():
            area = files(clone.id, module_id)
            for name, data in blobs.items():
                area.write_bytes(name, data)


def titles(clips: Sequence[StepClip]) -> str:
    """The payload's plain-text twin: one title per line, for pasting into anything else."""
    return "\n".join(c.title for c in clips)
