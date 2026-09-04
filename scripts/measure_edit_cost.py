"""What an edit costs the GUI thread, measured headless through the journal.

Builds the real application over a synthetic project (``--steps``, default 80: a chain with
branches, an estimate on every step, a milestone every twenty), opens every project tab,
pushes ten commands of three kinds — a title keystroke, an estimate write, a description
keystroke — and reads the journal back: the ``command`` span is the synchronous work per
push, the ``slot`` and ``refresh`` spans under it say which view paid for it.

    uv run python scripts/measure_edit_cost.py              # immediate: every view inline
    uv run python scripts/measure_edit_cost.py --deferred   # the window's regime: coalesced
    uv run python scripts/measure_edit_cost.py --idle       # the disk poll, git, the minimap

This is how the delays in ``framework/debounce.py``'s conversions were chosen, and it is
the number to quote before changing one. Nothing it builds touches the user's config or
library: QSettings and the library file live under a temporary directory.
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
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
from dplanner.modules.step_milestone.aspect import write as milestone

TABS = ("project", "order", "time", "progression", "tests", "docs", "assets")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--steps", type=int, default=80)
    parser.add_argument("--deferred", action="store_true", help="coalesced, as the window runs")
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

    def burst(label: str, make: Callable[[int], Command], count: int = 10) -> None:
        started = time.perf_counter()
        for index in range(count):
            services.undo.push(make(index))
            app.processEvents()
        settle()
        elapsed = (time.perf_counter() - started) * 1000.0
        print(f"\n== {label}: {count} pushes in {elapsed:.0f} ms ==")
        spans = current().recent()
        commands = [s for s in spans if s.kind == "command"]
        average = sum(s.duration_ms or 0.0 for s in commands) / max(1, len(commands))
        longest = max((s.duration_ms or 0.0 for s in commands), default=0.0)
        print(f"   command spans: {len(commands)}, avg {average:.1f} ms, max {longest:.1f} ms")
        totals: dict[tuple[str, str], float] = defaultdict(float)
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for span in spans:
            if span.kind in ("slot", "refresh"):
                totals[(span.kind, span.name)] += span.duration_ms or 0.0
                counts[(span.kind, span.name)] += 1
        for (kind, name), total in sorted(totals.items(), key=lambda item: -item[1])[:12]:
            print(f"   {total:8.1f} ms  {counts[(kind, name)]:3d}x  {kind:<7} {name}")
        current().clear()

    burst("title keystrokes", lambda i: SetFieldCommand(target.id, "title", f"Title {i}"))
    burst(
        "estimate writes",
        lambda i: SetModuleDataCommand(target.id, "estimation", estimate(1.0 + i)),
    )
    burst(
        "description keystrokes",
        lambda i: EditTextCommand(TextEdit(target.id, "step_description", 0, "", "x")),
    )

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


if __name__ == "__main__":
    main()
