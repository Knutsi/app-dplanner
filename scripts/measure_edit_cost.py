"""What an edit costs the GUI thread, measured headless through the journal.

Builds the real application over a synthetic project (``--steps``, default 80: a chain with
branches, an estimate on every step, a milestone every twenty, ``--notes`` handoffs in the
log), opens every project tab, pushes ten commands of three kinds — a title keystroke, an
estimate write, a description keystroke — and reads the journal back: the ``command`` span
is the synchronous work per push, the ``slot`` and ``refresh`` spans under it say which
view paid for it. ``--gestures`` then drives what a person feels on the canvas with a step
selected — a connect, a paste, a delete — through the same doors a mouse uses, and says
for each how long the GUI thread was held, how many times the context was announced and
how many times the panel dock relaid the window.

    uv run python scripts/measure_edit_cost.py              # immediate: every view inline
    uv run python scripts/measure_edit_cost.py --deferred   # the window's regime: coalesced
    uv run python scripts/measure_edit_cost.py --deferred --gestures --notes 300
    uv run python scripts/measure_edit_cost.py --idle       # the disk poll, git, the minimap

This is how the delays in ``framework/debounce.py``'s conversions were chosen, and it is
the number to quote before changing one — or anything the context's announcement reaches.
Nothing it builds touches the user's config or library: QSettings and the library file
live under a temporary directory.
"""

from __future__ import annotations

import argparse
import os
import random
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.core.storage.locations import init_repo
from dplanner.core.telemetry import Telemetry, current, install
from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    EditTextCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step, TextEdit
from dplanner.domain.seed import create_library, seed_project
from dplanner.modules.estimation.aspect import write as estimate
from dplanner.modules.notes.log import MODULE_ID as NOTES_ID
from dplanner.modules.notes.log import Note, write_log
from dplanner.modules.step_milestone.aspect import write as milestone

TABS = ("project", "order", "time", "progression", "tests", "docs", "assets")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--steps", type=int, default=80)
    parser.add_argument("--notes", type=int, default=0, help="handoffs seeded into the log")
    parser.add_argument("--deferred", action="store_true", help="coalesced, as the window runs")
    parser.add_argument("--gestures", action="store_true", help="also drive the canvas gestures")
    parser.add_argument("--idle", action="store_true", help="also time the idle costs")
    args = parser.parse_args()

    set_early_attributes()
    app = QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="dplanner-measure-"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "qsettings"))
    configure_application(app)
    install(Telemetry(slow_ms=0.0, ring=100_000))  # Keep every slot, however quick.

    library_file = tmp / "library.json"
    create_library(library_file)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(not args.deferred)
    library = services.document
    project = services.repo.attach(seed_project(init_repo(tmp / "repo") / "big", "Big"))
    library.add_child(library.id, project)

    random.seed(1)
    steps = []
    for index in range(args.steps):
        step = Step(title=f"Step {index}")
        AddNodeCommand(project.id, step).redo(library)
        steps.append(step)
    for index in range(1, args.steps):
        sources = [steps[index - 1].id]
        if index % 3 == 0:
            sources.append(steps[random.randrange(0, index)].id)
        SetEdgesCommand(steps[index].id, "requires", sources).redo(library)
    for index, step in enumerate(steps):
        SetModuleDataCommand(step.id, "estimation", estimate(float(1 + index % 4))).redo(library)
        if index % 20 == 19:
            label = milestone(f"M{index // 20}")
            SetModuleDataCommand(step.id, "step_milestone", label).redo(library)
        library.set_text(step.id, "step_description", f"What step {index} is.")
    if args.notes:
        notes = [
            Note(
                f"N{index + 1}",
                "handoff",
                f"Handoff {index + 1}: what the agent left for the next one",
                body="Where things are, what is stubbed, what to check first. " * 6,
                made="2026-09-05",
                step=steps[index % len(steps)].id,
            )
            for index in range(args.notes)
        ]
        SetModuleDataCommand(project.id, NOTES_ID, write_log(notes)).redo(library)

    for kind in TABS:
        services.tabs.open(kind, project.id)
    app.processEvents()
    services.debounce.flush_all()
    app.processEvents()
    target = steps[min(5, len(steps) - 1)]
    current().clear()

    def settle() -> None:
        if args.deferred:
            deadline = time.time() + 0.7  # Longer than the longest quiet spell.
            while time.time() < deadline:
                app.processEvents()
                time.sleep(0.01)
            services.debounce.flush_all()
            app.processEvents()

    def report_spans() -> None:
        spans = current().recent()
        totals: dict[tuple[str, str], float] = defaultdict(float)
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for span in spans:
            if span.kind in ("slot", "refresh"):
                totals[(span.kind, span.name)] += span.duration_ms or 0.0
                counts[(span.kind, span.name)] += 1
        for (kind, name), total in sorted(totals.items(), key=lambda item: -item[1])[:12]:
            print(f"   {total:8.1f} ms  {counts[(kind, name)]:3d}x  {kind:<7} {name}")
        current().clear()

    def burst(label: str, make: Callable[[int], Command], count: int = 10) -> None:
        started = time.perf_counter()
        for index in range(count):
            services.undo.push(make(index))
            app.processEvents()
        settle()
        elapsed = (time.perf_counter() - started) * 1000.0
        print(f"\n== {label}: {count} pushes in {elapsed:.0f} ms ==")
        commands = [s for s in current().recent() if s.kind == "command"]
        average = sum(s.duration_ms or 0.0 for s in commands) / max(1, len(commands))
        longest = max((s.duration_ms or 0.0 for s in commands), default=0.0)
        print(f"   command spans: {len(commands)}, avg {average:.1f} ms, max {longest:.1f} ms")
        report_spans()

    burst("title keystrokes", lambda i: SetFieldCommand(target.id, "title", f"Title {i}"))
    burst(
        "estimate writes",
        lambda i: SetModuleDataCommand(target.id, "estimation", estimate(1.0 + i)),
    )
    burst(
        "description keystrokes",
        lambda i: EditTextCommand(TextEdit(target.id, "step_description", 0, "", "x")),
    )

    if args.gestures:
        measure_gestures(app, services, project, steps, settle, report_spans)

    if args.idle:

        def timed(label: str, call: Callable[[], object], times: int) -> None:
            started = time.perf_counter()
            for _ in range(times):
                call()
            each = (time.perf_counter() - started) * 1000.0 / times
            print(f"   {label:<48} {each:8.2f} ms each  ({times}x)")

        print("\n== idle costs ==")
        timed("LibraryStore.changed_underneath()", services.repo.changed_underneath, 50)
        group = services.repo.repo_groups()[0]
        timed("RepoGroup.current_branch() (a git subprocess)", group.current_branch, 30)
        canvas = services.tabs.open("project", project.id)
        view = canvas._view
        timed("GraphView._refresh_minimap()", view._refresh_minimap, 200)

    session.close()
    print("\ndone")


def measure_gestures(
    app: QApplication,
    services: Any,
    project: Any,
    steps: list[Step],
    settle: Callable[[], None],
    report_spans: Callable[[], None],
) -> None:
    """The canvas gestures a person feels, with a step selected so the step panel is live:
    every one through the same door a mouse or a menu uses, never the model directly."""
    services.window.resize(1800, 1100)
    services.window.show()  # Painting is part of what the gesture costs.
    tab = services.tabs.open("project", project.id)
    scene = tab._scene
    app.processEvents()
    settle()

    announced: list[int] = []
    relaid: list[int] = []
    services.context.changed.connect(lambda _context: announced.append(1))
    dock = services.window.dock
    original_refresh = dock._refresh

    def counted_refresh() -> None:
        relaid.append(1)
        original_refresh()

    dock._refresh = counted_refresh

    def click(step_id: str) -> None:
        view = tab._view
        viewport = view.viewport()
        node = scene._nodes[step_id]
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
            app.sendEvent(viewport, event)

    def gesture(label: str, run: Callable[[], None]) -> None:
        announced.clear()
        relaid.clear()
        current().clear()
        started = time.perf_counter()
        run()
        app.processEvents()
        held = (time.perf_counter() - started) * 1000.0
        settle()
        print(
            f"\n== {label}: GUI thread held {held:.0f} ms; context announced "
            f"{len(announced)}x, dock relaid {len(relaid)}x, "
            f"selection {list(scene.selection().steps)} =="
        )
        report_spans()

    source, target = steps[0], steps[-1]
    gesture("select a step", lambda: tab.select_step(source.id))
    gesture(
        "connect (c, click source, click target)",
        lambda: (
            services.actions.run("steps.connect", services.context.current()),
            click(source.id),
            click(target.id),
        ),
    )
    services.actions.run("steps.copy", services.context.current())
    settle()
    tab._view.note_click(QPointF(200.0, 200.0))
    gesture(
        "paste one step", lambda: services.actions.run("steps.paste", services.context.current())
    )
    gesture(
        "delete the pasted step",
        lambda: services.actions.run("steps.delete", services.context.current()),
    )
    gesture("deselect (click empty canvas)", lambda: scene.select_steps([]))
    gesture("select a step again", lambda: tab.select_step(source.id))


if __name__ == "__main__":
    main()
