"""How the application scales: what each gesture costs the GUI thread, by project size.

Builds the real application headless over ``scripts/synthetic_library.py``'s library at
each of ``--sizes``, opens the tabs of one regime, and runs every scenario the window has
a gesture for — a burst of ten edits of each kind, a click on a step, a context refresh,
a connect and a paste through the verbs with a step selected (reporting how many times
the context was announced and the dock relaid itself, which is what made them slow once),
the details dialog, a cold tab open, a paint of the canvas, the disk poll, the recorder,
a full garbage collection, the keyring, and each domain derivation on its own — reading
the journal back after each: the ``command`` spans are the synchronous cost of a push,
the ``slot`` and ``refresh`` spans say which view paid, and a rebuild that runs *after*
the first quiet spell is the second wave.

    uv run python scripts/measure_scaling.py                              # few tabs, five sizes
    uv run python scripts/measure_scaling.py --tabs all --json out.json   # the scaling profile
    uv run python scripts/measure_scaling.py --sizes 100 --profile select # attribution
    uv run python scripts/measure_scaling.py --sizes 80 --immediate \
        --tabs project,order,time,progression,tests,docs,assets \
        --scenarios title,estimate,description

The last line is the 2026-09-04 measurement (``measure_edit_cost.py``, which this script
replaces). Deferred is the window's regime and the default; ``--immediate`` runs every
view inline, which moves attribution but not the total, and is the honesty check. The
numbers here are the ones to quote before changing a delay in ``framework/debounce.py``.
Nothing it builds touches the user's config, journal or library.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import json
import os
import platform
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# Forced, not defaulted: a shell that presets the platform (Arch with a tiling WM does)
# would put every build on the desktop, and a window busy in a measurement loop is one
# the compositor reports as not responding. The theme is blanked for the reason
# tests/conftest.py gives: gtk3 starts eight threads and a compositor connection.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""
# The repository root, so `scripts.synthetic_library` imports the same way the tests do.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.core.secrets import get_secret
from dplanner.core.telemetry import Span, Telemetry, current, install
from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    EditTextCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
    remove_steps_command,
)
from dplanner.domain.model import Library, Project, Step, TextEdit
from dplanner.domain.ordering import depths, placed
from dplanner.domain.progression import progression
from dplanner.domain.scope import cone
from dplanner.domain.store import LibraryStore
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.framework.session import AppSession
from dplanner.modules.estimation.aspect import read as estimated_days
from dplanner.modules.estimation.aspect import write as estimate
from dplanner.modules.estimation.schedule import project_schedule, start_of
from dplanner.modules.feature import aspect as feature_aspect
from dplanner.modules.feature.aspect import FeatureSource
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.project_editor.clipboard import clip, paste
from dplanner.modules.project_editor.look import BACKGROUNDS, Look
from dplanner.modules.project_editor.placement import auto_positions
from dplanner.modules.project_editor.positions import MODULE_ID as EDITOR_ID
from dplanner.modules.project_editor.positions import write_position
from dplanner.modules.spec import aspect as spec_aspect
from dplanner.modules.spec.documents import SpecIndex, import_document, write_index
from dplanner.modules.step_agent_instruction.aspect import enabled as is_agent
from dplanner.modules.step_milestone.aspect import read as milestone_label
from dplanner.modules.step_properties.dialog import StepDetailsDialog
from dplanner.modules.step_status.aspect import read as step_status
from dplanner.modules.step_status.aspect import write as status
from dplanner.modules.time_estimates.module import TimeEstimatesModule
from dplanner.modules.time_estimates.schedule import read_efficiency, read_start, time_report

FEW_TABS = ("project", "order", "time")
ALL_TABS = (
    *FEW_TABS,
    "progression",
    "tests",
    "docs",
    "assets",
    "estimate",
    "coverage",
    "all_tests",
    "specs",
)
PUSHES = 10
QUIET_GAP_S = 0.15  # No span for this long, and nothing pending, is quiet.
QUIET_CAP_S = 5.0


# -- what one scenario measured ----------------------------------------------------------------


@dataclass
class Result:
    scenario: str
    size: int
    gesture_ms: float = 0.0  # Wall time of the gestures themselves, pumping between them.
    command_ms: float = 0.0  # The synchronous cost inside the pushes (the ``command`` spans).
    command_max_ms: float = 0.0
    quiet_ms: float = 0.0  # From the last gesture until nothing was pending or running.
    flush_ms: float = 0.0  # The autosave flush the gestures left owing.
    refresh_count: int = 0
    refresh_ms: float = 0.0
    slot_ms: float = 0.0
    action_ms: float = 0.0
    second_wave: dict[str, int] = field(default_factory=dict)  # Refreshes after the recorder.
    twice: dict[str, int] = field(default_factory=dict)  # Settled views that rebuilt twice.
    record_all_count: int = 0
    gc_count: int = 0
    gc_ms: float = 0.0
    top: list[tuple[str, int, float]] = field(default_factory=list)  # (kind name, count, ms)
    extra: dict[str, float] = field(default_factory=dict)  # Per-scenario numbers.

    @property
    def total_ms(self) -> float:
        return self.gesture_ms + self.quiet_ms


class GcMeter:
    """Every collection the interpreter ran while a scenario was measured."""

    def __init__(self) -> None:
        self.count = 0
        self.ms = 0.0
        self._started = 0.0
        gc.callbacks.append(self._hook)

    def reset(self) -> None:
        self.count, self.ms = 0, 0.0

    def _hook(self, phase: str, _info: dict[str, Any]) -> None:
        if phase == "start":
            self._started = time.perf_counter()
        else:
            self.count += 1
            self.ms += (time.perf_counter() - self._started) * 1000.0


# -- the application under measurement ---------------------------------------------------------


class Harness:
    def __init__(self, app: QApplication, session: AppSession, size: int, tabs: Sequence[str]):
        self.app = app
        self.session = session
        services = session.services
        assert services is not None
        self.services = services
        self.library: Library = services.document
        self.size = size
        self.tabs = tuple(tabs)
        self.gc = GcMeter()
        by_title = {project.title: project for project in self.library.projects}
        self.project: Project = by_title["Big"]
        self.other: Project = by_title.get("Sibling", self.project)
        self.steps: list[Step] = list(self.project.steps)
        self.target = self.steps[min(5, len(self.steps) - 1)]

    # -- pumping ---------------------------------------------------------------------------------

    def pump(self) -> None:
        self.app.processEvents()

    def push(self, command: Command) -> None:
        self.services.undo.push(command)
        self.pump()

    def quiet(self) -> float:
        """Pump until nothing is pending and the journal has been silent for a gap."""
        started = time.perf_counter()
        last_seen = started
        seen = journal_length()
        while time.perf_counter() - started < QUIET_CAP_S:
            self.pump()
            time.sleep(0.005)
            now = journal_length()
            if now != seen:
                seen, last_seen = now, time.perf_counter()
            pending = self.services.debounce.pending()
            if not pending and time.perf_counter() - last_seen >= QUIET_GAP_S:
                break
        return (time.perf_counter() - started) * 1000.0

    def open_tabs(self) -> None:
        for kind in self.tabs:
            self.open_tab(kind)
        self.pump()
        self.quiet()

    def open_tab(self, kind: str) -> object:
        target = None if kind == "all_tests" else self.project.id
        return self.services.tabs.open(kind, target)

    def selection(self, *step_ids: str) -> Context:
        nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)
        return Context({SCOPE_SELECTION: nodes})

    def select(self, *step_ids: str) -> None:
        nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)
        self.services.context.set_scope(SCOPE_SELECTION, nodes)
        self.pump()

    def canvas(self) -> Any:
        return self.open_tab("project")

    def store(self) -> LibraryStore:
        store = self.services.repo
        assert isinstance(store, LibraryStore)
        return store

    def recorder(self) -> Any:
        module = next(m for m in self.services.modules if isinstance(m, TimeEstimatesModule))
        return module.recorder

    # -- measuring -------------------------------------------------------------------------------

    def measure(self, scenario: str, body: Callable[[Harness], dict[str, float] | None]) -> Result:
        self.quiet()
        self.services.autosave.flush_now()
        self.pump()
        current().clear()
        self.gc.reset()
        started = time.perf_counter()
        extra = body(self) or {}
        gesture_ms = (time.perf_counter() - started) * 1000.0
        quiet_ms = self.quiet()
        spans = list(current().recent())
        result = analyse(scenario, self.size, spans)
        result.gesture_ms, result.quiet_ms = gesture_ms, quiet_ms
        result.gc_count, result.gc_ms = self.gc.count, self.gc.ms
        result.extra = extra
        current().clear()
        flush_started = time.perf_counter()
        self.services.autosave.flush_now()
        result.flush_ms = (time.perf_counter() - flush_started) * 1000.0
        self.quiet()
        current().clear()
        return result


def journal_length() -> int:
    # The ring itself rather than ``recent()``: a copy of every span, twice a millisecond,
    # was the largest Python cost in a profile of the application under measurement.
    return len(current()._ring)


def analyse(scenario: str, size: int, spans: Sequence[Span]) -> Result:
    result = Result(scenario, size)
    commands = [s for s in spans if s.kind == "command"]
    result.command_ms = sum(s.duration_ms or 0.0 for s in commands)
    result.command_max_ms = max((s.duration_ms or 0.0 for s in commands), default=0.0)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for span in spans:
        totals[(span.kind, span.name)] += span.duration_ms or 0.0
        counts[(span.kind, span.name)] += 1
        if span.kind == "refresh":
            result.refresh_count += 1
            result.refresh_ms += span.duration_ms or 0.0
        elif span.kind == "slot":
            result.slot_ms += span.duration_ms or 0.0
        elif span.kind == "action":
            result.action_ms += span.duration_ms or 0.0
    recorder_runs = [s for s in spans if s.kind == "refresh" and "record_all" in s.name]
    result.record_all_count = len(recorder_runs)
    # The recorder listens to its own write, so a second run is the tell that it wrote —
    # and every refresh after the first run is then the second wave that write caused.
    if len(recorder_runs) >= 2:
        first = recorder_runs[0]
        ended = first.started_at + (first.duration_ms or 0.0) / 1000.0
        after: dict[str, int] = defaultdict(int)
        for span in spans:
            if span.kind == "refresh" and span.started_at > ended and "record_all" not in span.name:
                after[short(span.name)] += 1
        result.second_wave = dict(after)
    settled: dict[str, int] = defaultdict(int)
    for span in spans:
        if span.kind == "refresh" and span.detail.get("delay_ms", 0) > 0:
            settled[short(span.name)] += 1
    result.twice = {name: n for name, n in settled.items() if n >= 2}
    ranked = sorted(totals.items(), key=lambda item: -item[1])[:12]
    result.top = [
        (f"{kind} {short(name)}", counts[(kind, name)], ms) for (kind, name), ms in ranked
    ]
    return result


def short(name: str) -> str:
    return name.split(" (")[0]


# -- the scenarios -----------------------------------------------------------------------------

Body = Callable[[Harness], "dict[str, float] | None"]
SCENARIOS: dict[str, Body] = {}


def scenario(name: str) -> Callable[[Body], Body]:
    def register(body: Body) -> Body:
        SCENARIOS[name] = body
        return body

    return register


@scenario("title")
def _title(h: Harness) -> None:
    for i in range(PUSHES):
        h.push(SetFieldCommand(h.target.id, "title", f"Title {i}"))


@scenario("estimate")
def _estimate(h: Harness) -> None:
    for i in range(PUSHES):
        h.push(SetModuleDataCommand(h.target.id, "estimation", estimate(1.0 + i)))


@scenario("description")
def _description(h: Harness) -> None:
    for _ in range(PUSHES):
        h.push(EditTextCommand(TextEdit(h.target.id, "step_description", 0, "", "x")))


@scenario("status")
def _status(h: Harness) -> None:
    words = ("in-progress", "done", "blocked", "pending")
    for i in range(PUSHES):
        h.push(SetModuleDataCommand(h.target.id, "step_status", status(words[i % 4])))


@scenario("link")
def _link(h: Harness) -> None:
    waiter = h.steps[-1]
    before = list(waiter.edges.get("requires", []))
    extra = [s.id for s in h.steps[: PUSHES // 2] if s.id not in before]
    for i in range(PUSHES // 2):
        h.push(SetEdgesCommand(waiter.id, "requires", [*before, *extra[: i + 1]]))
    for i in range(PUSHES // 2):
        h.push(SetEdgesCommand(waiter.id, "requires", [*before, *extra[: PUSHES // 2 - i - 1]]))


@scenario("add")
def _add(h: Harness) -> None:
    for i in range(PUSHES):
        step = Step(title=f"Born {i}")
        step.module_data[EDITOR_ID] = write_position(40.0 * i, -300.0)
        h.push(CompositeCommand("New Step", [AddNodeCommand(h.project.id, step)]))


@scenario("paste20")
def _paste(h: Harness) -> None:
    ids = [s.id for s in h.steps[:20]]
    clips = clip(h.library, h.store().files, (), ids)
    command, _clones = paste(h.library, h.project.id, clips, anchor=(0.0, -800.0))
    h.push(command)


@scenario("delete")
def _delete(h: Harness) -> None:
    born = [s.id for s in h.project.steps if s.title.startswith("Born ")]
    doomed = born[:PUSHES] or [s.id for s in h.project.steps[-PUSHES:]]
    h.push(remove_steps_command(h.library, doomed, "Delete"))


@scenario("undo_redo")
def _undo_redo(h: Harness) -> None:
    for i in range(PUSHES // 2):
        h.push(SetFieldCommand(h.target.id, "title", f"Undone {i}"))
    for _ in range(PUSHES // 2):
        h.services.undo.undo()
        h.pump()
    for _ in range(PUSHES // 2):
        h.services.undo.redo()
        h.pump()


@scenario("foreign_edit")
def _foreign(h: Harness) -> None:
    step = h.other.steps[min(5, len(h.other.steps) - 1)]
    for i in range(PUSHES):
        h.push(SetFieldCommand(step.id, "title", f"Elsewhere {i}"))


@scenario("select")
def _select(h: Harness) -> None:
    picks = [s for s in h.steps if milestone_label(s)][:2]
    picks += [s for s in h.steps if s.module_data.get("feature")][:2]
    picks += h.steps[10:16]
    for step in picks[:PUSHES]:
        h.select(step.id)
    h.select()


@scenario("select20")
def _select_many(h: Harness) -> dict[str, float]:
    activity = h.canvas()
    h.services.tabs.focus(activity)
    h.pump()
    ids = [s.id for s in h.steps[:20]]
    started = time.perf_counter()
    activity.select_steps(ids)
    h.pump()
    picked = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    activity.select_steps([])
    h.pump()
    cleared = (time.perf_counter() - started) * 1000.0
    return {"pick20_ms": picked, "clear_ms": cleared}


@scenario("spec_typing")
def _spec_typing(h: Harness) -> dict[str, float]:
    """A keystroke in the Specs editor, on a spec big enough to have citations in it.

    The editor's expensive derivations — where each cited passage now sits, and the wash
    over the lit ones — used to run on every keystroke, each one walking the whole
    document once per passage. They are coalesced now, so this reports both halves: what
    a keystroke holds the GUI thread for, and what one settle costs after the typing
    stops.
    """
    body = "".join(
        f"## Section {n}\n\nThe system shall record reading {n} for every site.\n\n"
        for n in range(220)
    )
    quotes = [f"The system shall record reading {n} for every site." for n in range(0, 160, 20)]
    spec_id, feature_id = spec_aspect.MODULE_ID, feature_aspect.MODULE_ID
    area = h.store().files(h.project.id, spec_id)
    documents, _document, _outcome = import_document(
        area, [], "big", body.encode(), "big.md", "2026-09-13"
    )
    h.push(
        SetModuleDataCommand(
            h.project.id, spec_id, write_index(SpecIndex(documents=documents, assets=[]))
        )
    )
    # A feature is a step, so the citations the editor must find again live on one.
    h.push(
        SetModuleDataCommand(
            h.target.id,
            feature_id,
            feature_write(tuple(FeatureSource(document="big", quote=q) for q in quotes)),
        )
    )

    activity: Any = h.services.tabs.open("specs", h.project.id)
    activity.select_document("big")
    h.quiet()
    editor = activity._editor
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    started = time.perf_counter()
    for _ in range(PUSHES):
        editor.insertPlainText("x")
    typing = (time.perf_counter() - started) / PUSHES * 1000.0
    started = time.perf_counter()
    activity._resettle()
    settle = (time.perf_counter() - started) * 1000.0
    return {"keystroke_ms": typing, "settle_ms": settle, "kb": len(body) / 1024}


@scenario("context_refresh")
def _context(h: Harness) -> None:
    h.select(h.target.id)
    h.quiet()
    current().clear()
    for _ in range(PUSHES):
        h.services.context.refresh()
        h.pump()


def _click(h: Harness, activity: Any, step_id: str) -> None:
    """A press and a release on the step's card, through the view — what a mouse sends."""
    view = activity._view
    viewport = view.viewport()
    node = activity._scene._nodes[step_id]
    local = QPointF(view.mapFromScene(node.scenePos() + QPointF(90, 28)))
    for kind, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(
            kind,
            local,
            QPointF(viewport.mapToGlobal(local.toPoint())),
            Qt.MouseButton.LeftButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        h.app.sendEvent(viewport, event)


def _heard(h: Harness, gesture: Callable[[], None]) -> dict[str, float]:
    """Run a gesture the way a person does and count what the window heard: how long the
    GUI thread was held, how many times the context was announced and how many times the
    dock relaid the window. One announcement and no relayout is the number to keep."""
    announced: list[int] = []
    relaid: list[int] = []
    unsubscribe = h.services.context.changed.connect(lambda _context: announced.append(1))
    dock = h.services.window.dock
    original = dock._refresh

    def counted() -> None:
        relaid.append(1)
        original()

    dock._refresh = counted  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        gesture()
        h.pump()
        held = (time.perf_counter() - started) * 1000.0
        h.quiet()
    finally:
        dock._refresh = original  # type: ignore[method-assign]
        unsubscribe()
    return {"held_ms": held, "announced": float(len(announced)), "relaid": float(len(relaid))}


@scenario("connect")
def _connect(h: Harness) -> dict[str, float]:
    """`c`, click the source, click the target — with the source selected, so the step
    panel is live — and the selection is left on the source for the next one."""
    activity = h.canvas()
    h.services.tabs.focus(activity)
    h.pump()
    source, target = h.steps[0], h.steps[-1]
    activity.select_step(source.id)
    h.quiet()

    def gesture() -> None:
        h.services.actions.run("steps.connect", h.services.context.current())
        _click(h, activity, source.id)
        _click(h, activity, target.id)

    extra = _heard(h, gesture)
    if source.id not in h.library.step(target.id).edges.get("requires", []):
        raise RuntimeError("the connect gesture wrote no link")
    h.services.undo.undo()
    h.pump()
    return extra


@scenario("paste")
def _paste_gesture(h: Harness) -> dict[str, float]:
    """Copy the selected step and paste it, through the verbs: one step, placed, selected."""
    activity = h.canvas()
    h.services.tabs.focus(activity)
    h.pump()
    activity.select_step(h.target.id)
    h.quiet()
    h.services.actions.run("steps.copy", h.services.context.current())
    h.quiet()
    activity._view.note_click(QPointF(200.0, -600.0))
    before = {step.id for step in h.project.steps}
    extra = _heard(h, lambda: h.services.actions.run("steps.paste", h.services.context.current()))
    born = [step.id for step in h.project.steps if step.id not in before]
    if not born:
        raise RuntimeError("the paste gesture placed no step")
    h.push(remove_steps_command(h.library, born, "Delete"))
    return extra


@scenario("details")
def _details(h: Harness) -> dict[str, float]:
    stamps: list[tuple[float, float]] = []

    def fake_exec(dialog: StepDetailsDialog) -> int:
        entered = time.perf_counter()
        dialog.show()
        h.pump()
        stamps.append((entered, time.perf_counter()))
        dialog.hide()
        return 0

    original = StepDetailsDialog.exec
    StepDetailsDialog.exec = fake_exec  # type: ignore[method-assign, assignment]
    construct: list[float] = []
    first_show: list[float] = []
    dispose: list[float] = []
    try:
        for step in h.steps[:5]:
            started = time.perf_counter()
            h.services.actions.run("steps.details", h.selection(step.id))
            ended = time.perf_counter()
            h.pump()
            entered, shown = stamps[-1]
            construct.append((entered - started) * 1000.0)
            first_show.append((shown - entered) * 1000.0)
            dispose.append((ended - shown) * 1000.0)
    finally:
        StepDetailsDialog.exec = original  # type: ignore[method-assign]
    return {
        "construct_ms": statistics.median(construct),
        "first_show_ms": statistics.median(first_show),
        "dispose_ms": statistics.median(dispose),
    }


@scenario("tabs")
def _tabs(h: Harness) -> dict[str, float]:
    tabs = h.services.tabs
    opened: dict[str, float] = {}
    for kind in ALL_TABS:
        if not tabs.can_open(kind):
            continue
        for activity in tabs.activities():
            if activity.uri.startswith(f"{kind}:"):
                tabs.close_activity(activity)
        h.pump()
        h.quiet()
        started = time.perf_counter()
        h.open_tab(kind)
        h.pump()
        quiet = h.quiet()
        opened[f"open_{kind}_ms"] = (time.perf_counter() - started) * 1000.0 - quiet + min(quiet, 1)
        opened[f"settle_{kind}_ms"] = quiet
        if kind not in h.tabs:
            for activity in tabs.activities():
                if activity.uri.startswith(f"{kind}:"):
                    tabs.close_activity(activity)
            h.pump()
    h.open_tabs()
    return opened


@scenario("paint")
def _paint(h: Harness) -> dict[str, float]:
    activity = h.canvas()
    h.services.tabs.focus(activity)
    h.pump()
    view = activity._view
    scene = activity._scene
    numbers: dict[str, float] = {}
    viewport = view.viewport().size()
    numbers["viewport_px"] = float(viewport.width() * viewport.height())
    for background in BACKGROUNDS:
        activity.set_look(Look().with_background(background))
        for zoom_name in ("framed", "close"):
            view.frame_content()
            if zoom_name == "close":
                view.zoom_by(20)  # Up to the readable end; the cap holds it there.
            for picked in (0, 1, 20):
                scene.select_steps([s.id for s in h.steps[:picked]])
                h.pump()
                samples = []
                for _ in range(5):
                    started = time.perf_counter()
                    view.grab()
                    samples.append((time.perf_counter() - started) * 1000.0)
                numbers[f"{background}/{zoom_name}/picked{picked}_ms"] = min(samples)
    scene.select_steps([])
    activity.set_look(Look())
    view.frame_content()
    return numbers


@scenario("poll")
def _poll(h: Harness) -> dict[str, float]:
    return {"changed_underneath_ms": _each(h.store().changed_underneath, 20)}


@scenario("recorder")
def _recorder(h: Harness) -> dict[str, float]:
    recorder = h.recorder()
    if recorder is None:
        return {}
    return {
        "record_all_ms": _each(recorder.record_all, 3),
        "snapshot_ms": _each(lambda: recorder.snapshot(h.project), 5),
    }


@scenario("gc")
def _gc(h: Harness) -> dict[str, float]:
    return {
        "objects": float(len(gc.get_objects())),
        "collect_gen2_ms": _each(lambda: gc.collect(2), 3),
        "collect_gen0_ms": _each(lambda: gc.collect(0), 5),
    }


@scenario("keyring")
def _keyring(h: Harness) -> dict[str, float]:
    return {"get_secret_ms": _each(lambda: get_secret("llm_openai", "api_key"), 5)}


@scenario("derive")
def _derive(h: Harness) -> dict[str, float]:
    library, project = h.library, h.project
    last, first = h.steps[-1].id, h.steps[0].id
    calls: dict[str, Callable[[], object]] = {
        "depths": lambda: depths(library, project),
        "placed": lambda: placed(library, project),
        "cone": lambda: cone(library, project, last),
        "project_schedule": lambda: project_schedule(library, project),
        "progression": lambda: progression(library, project, step_status),
        "link_refusal": lambda: library.link_refusal(first, "requires", last),
        "auto_positions": lambda: auto_positions(library, project),
        "time_report": lambda: time_report(
            library,
            project,
            estimated_days,
            is_agent,
            start=start_of(project),
            efficiency=read_efficiency(project),
            is_milestone=lambda step: bool(milestone_label(step)),
            start_for=read_start,
        ),
    }
    return {f"{name}_ms": _each(call, 20) for name, call in calls.items()}


def _each(call: Callable[[], object], times: int, cap_s: float = 2.0) -> float:
    """Mean wall time of one call, over ``times`` calls or ``cap_s``, whichever is first."""
    samples: list[float] = []
    started = time.perf_counter()
    for _ in range(times):
        one = time.perf_counter()
        call()
        samples.append((time.perf_counter() - one) * 1000.0)
        if time.perf_counter() - started > cap_s and len(samples) >= 2:
            break
    return statistics.mean(samples)


# -- the run -----------------------------------------------------------------------------------


def build(app: QApplication, root: Path, size: int, args: argparse.Namespace) -> Harness:
    started = time.perf_counter()
    library_file = build_library(
        root / str(size), steps=size, projects=args.projects, unplaced=args.unplaced
    )
    built_ms = (time.perf_counter() - started) * 1000.0
    session = new_session()
    started = time.perf_counter()
    assert session.open_initial(library_file)
    opened_ms = (time.perf_counter() - started) * 1000.0
    services = session.services
    assert services is not None
    services.debounce.set_immediate(args.immediate)
    harness = Harness(app, session, size, args.tabs)
    harness.extra_open = {"build_ms": built_ms, "open_ms": opened_ms}  # type: ignore[attr-defined]
    harness.open_tabs()
    return harness


def discard(harness: Harness, app: QApplication) -> None:
    """Release one size's build, and clear the clipboard while Python is still alive.

    The paste scenario copies through ``steps.copy``, which hands a Python-made ``QMimeData``
    to the clipboard; under the offscreen platform Qt keeps it in a global static that libc
    destroys *after* the interpreter, and its wrapper's destructor then calls into a
    finalized Python — the exit-time segfault CLAUDE.md's *A worker that segfaults after
    reporting green* describes, and ``tests/conftest.py`` clears after every test.
    """
    harness.session.close()
    QGuiApplication.clipboard().clear()
    app.processEvents()
    gc.collect()


def medians(results: Sequence[Result]) -> Result:
    if len(results) == 1:
        return results[0]
    merged = Result(results[0].scenario, results[0].size)
    for name in (
        "gesture_ms",
        "command_ms",
        "command_max_ms",
        "quiet_ms",
        "flush_ms",
        "refresh_ms",
        "slot_ms",
        "action_ms",
        "gc_ms",
    ):
        setattr(merged, name, statistics.median(getattr(r, name) for r in results))
    for name in ("refresh_count", "record_all_count", "gc_count"):
        setattr(merged, name, int(statistics.median(getattr(r, name) for r in results)))
    keys = {key for r in results for key in r.extra}
    merged.extra = {
        key: statistics.median(r.extra[key] for r in results if key in r.extra) for key in keys
    }
    middle = sorted(results, key=lambda r: r.total_ms)[len(results) // 2]
    merged.second_wave, merged.twice, merged.top = middle.second_wave, middle.twice, middle.top
    spread = max(r.total_ms for r in results) - min(r.total_ms for r in results)
    if merged.total_ms and spread / merged.total_ms > 0.2:
        merged.extra["spread_share"] = spread / merged.total_ms
    return merged


def profile_one(harness: Harness, name: str, args: argparse.Namespace) -> None:
    body = SCENARIOS[name]
    out = Path(args.profile_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.profiler == "pyinstrument":
        import pyinstrument  # type: ignore[import-not-found]

        profiler = pyinstrument.Profiler()
        profiler.start()
        harness.measure(name, body)
        profiler.stop()
        html = out / f"{name}-{harness.size}.html"
        html.write_text(profiler.output_html())
        print(profiler.output_text(unicode=True, color=False, show_all=False)[:6000])
        print(f"call tree: {html}")
        return
    profiler = cProfile.Profile()
    profiler.enable()
    harness.measure(name, body)
    profiler.disable()
    path = out / f"{name}-{harness.size}.prof"
    profiler.dump_stats(str(path))
    for order in ("cumulative", "tottime"):
        print(f"\n== {name} at {harness.size} steps, by {order} ==")
        pstats.Stats(profiler).sort_stats(order).print_stats(30)
    print(f"stats: {path}")


def print_table(name: str, rows: Sequence[Result]) -> None:
    print(f"\n== {name} ==")
    head = "  size  gesture  command  max   quiet   flush  refr#  refresh   slot  2nd  twice  gc"
    print(head)
    for r in rows:
        second = sum(r.second_wave.values())
        print(
            f"{r.size:6d} {r.gesture_ms:8.1f} {r.command_ms:8.1f} {r.command_max_ms:5.1f}"
            f" {r.quiet_ms:7.0f} {r.flush_ms:7.1f} {r.refresh_count:6d} {r.refresh_ms:8.1f}"
            f" {r.slot_ms:6.1f} {second:4d} {len(r.twice):6d} {r.gc_ms:5.1f}"
        )
    last = rows[-1]
    for key, value in sorted(last.extra.items()):
        print(f"        {key:<40} {value:10.2f}")
    if last.second_wave:
        print(f"        second wave at {last.size}: {last.second_wave}")
    if last.twice:
        print(f"        rebuilt twice at {last.size}: {last.twice}")
    for label, count, ms in last.top[:8]:
        print(f"        {ms:8.1f} ms {count:4d}x  {label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sizes", default="25,50,100,200,400")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--tabs", default="few", help="few | all | a comma list of kinds")
    parser.add_argument("--projects", type=int, default=3)
    parser.add_argument("--unplaced", type=float, default=0.0)
    parser.add_argument("--immediate", action="store_true", help="every view inline")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--profile", default=None, help="one scenario, under a profiler")
    parser.add_argument("--profiler", choices=("cprofile", "pyinstrument"), default="cprofile")
    parser.add_argument("--profile-dir", default=tempfile.gettempdir())
    parser.add_argument("--force-gc", action="store_true", help="collect after every push")
    args = parser.parse_args()
    args.tabs = {"few": FEW_TABS, "all": ALL_TABS}.get(args.tabs, tuple(args.tabs.split(",")))
    sizes = [int(s) for s in args.sizes.split(",")]
    names = [s for s in args.scenarios.split(",") if s]
    unknown = [s for s in names if s not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario {unknown}; one of {', '.join(SCENARIOS)}")

    set_early_attributes()
    app = QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="dplanner-scaling-"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "qsettings"))
    configure_application(app)
    install(Telemetry(slow_ms=0.0, ring=200_000))  # Keep every slot, however quick.
    if args.force_gc:
        from dplanner.framework.gc_policy import collect_if_due

        original_pump = Harness.pump

        def pump(self: Harness) -> None:
            original_pump(self)
            collect_if_due()

        Harness.pump = pump  # type: ignore[method-assign]

    import keyring

    meta: dict[str, Any] = {
        "date": date.today().isoformat(),
        "commit": _commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "keyring_backend": type(keyring.get_keyring()).__name__,
        "tabs": list(args.tabs),
        "sizes": sizes,
        "immediate": args.immediate,
        "projects": args.projects,
        "unplaced": args.unplaced,
    }
    results: dict[str, list[Result]] = defaultdict(list)
    for size in sizes:
        harness = build(app, tmp, size, args)
        meta["spec_count"] = len(harness.services.actions.all_specs())
        opening = getattr(harness, "extra_open", {})
        print(
            f"\n#### {size} steps: built in {opening.get('build_ms', 0):.0f} ms, "
            f"opened in {opening.get('open_ms', 0):.0f} ms, tabs {', '.join(args.tabs)}"
        )
        results["open"].append(Result("open", size, extra=dict(opening)))
        if args.profile:
            profile_one(harness, args.profile, args)
        else:
            for name in names:
                runs = [harness.measure(name, SCENARIOS[name]) for _ in range(args.repeat)]
                results[name].append(medians(runs))
        discard(harness, app)

    if not args.profile:
        for name, rows in results.items():
            print_table(name, rows)
    if args.json:
        payload = {
            "meta": meta,
            "results": [asdict(r) for rows in results.values() for r in rows],
        }
        args.json.write_text(json.dumps(payload, indent=1))
        print(f"\nwritten {args.json}")
    print("\ndone")


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


if __name__ == "__main__":
    main()
