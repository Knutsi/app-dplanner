"""A large synthetic library, for measuring the application and for feeling it.

Three projects in one plan repository — *Big* and *Sibling* of ``--steps`` steps each, and
*Small* of twenty — with the mix of aspects a real plan carries: a chain with branches and
a few plain links, statuses (a done prefix, a working band, the odd blocked step), an
estimate on most steps, a milestone every fifteen, a feature step per record quoting a
spec of a requirement per step, agent steps, checks, two tests on most steps with three
closed runs and one open, notes, a description on every step, and a stored position on
every step (or on all but an ``--unplaced`` share, to price the automatic layout). Two
projects of the same size is what catches a view that listens to the whole library instead
of its own project.

    uv run python scripts/synthetic_library.py --steps 400 --out ~/dplanner-perf
    dplanner window --library ~/dplanner-perf/library.json     # from your own terminal

Qt-free, written through the CLI's ``open_library`` so the plan lands on disk in the real
format; ``scripts/measure_scaling.py`` builds the same library under a temporary directory.
Nothing touches the user's config or library.
"""

from __future__ import annotations

import argparse
import io
import random
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from dplanner.cli.discovery import open_library
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.domain.store import ModuleFileArea
from dplanner.modules import default_module_formats
from dplanner.modules.estimation.aspect import write as estimate
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.feature.aspect import FeatureSource
from dplanner.modules.feature.aspect import write as feature_marker
from dplanner.modules.notes.log import MODULE_ID as NOTES_ID
from dplanner.modules.notes.log import Note, write_log
from dplanner.modules.project_editor.positions import MODULE_ID as EDITOR_ID
from dplanner.modules.project_editor.positions import write_position
from dplanner.modules.project_editor.sorts import layered_flow
from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
from dplanner.modules.spec.documents import SpecIndex, import_document, write_index
from dplanner.modules.step_agent_instruction.aspect import write_state as agent_state
from dplanner.modules.step_check.aspect import write as check
from dplanner.modules.step_milestone.aspect import write as milestone
from dplanner.modules.step_status.aspect import write as status
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import Test
from dplanner.modules.testing.aspect import write as tests
from dplanner.modules.testing.filing import Category, write_catalog
from dplanner.modules.time_estimates.schedule import write_project

PROJECTS = (("big", "Big"), ("sibling", "Sibling"), ("small", "Small"))
SMALL_STEPS = 20

DESCRIPTION = (
    "## What step {n} is\n\nThe {n}th piece of the plan, with a **bold** claim and a "
    "`code` word.\n\n- One thing it must do\n- Another it must not\n"
)


def build_library(
    root: Path, *, steps: int, projects: int = 3, unplaced: float = 0.0, seed: int = 1
) -> Path:
    """Write the library under ``root`` and return its file. ``projects`` is at most three."""
    random.seed(seed)
    library_file = root / "library.json"
    create_library(library_file)
    repo = init_repo(root / "plans")
    with open_library(library_file, default_module_formats(), io.StringIO()) as context:
        for slug, title in PROJECTS[: max(1, min(projects, len(PROJECTS)))]:
            project = context.store.attach(seed_project(repo / slug, title))
            context.library.add_child(context.library.id, project)
            count = SMALL_STEPS if slug == "small" else steps
            _fill(context.library, project, count, unplaced)
            _spec(context.store.files(project.id, SPEC_ID), context.library, project, count)
    return library_file


def _spec(area: ModuleFileArea, library: Library, project: Project, count: int) -> None:
    """The spec every feature step quotes, a requirement per step — so a passage is judged
    against a document the size a real plan's is, and not against a name that is missing,
    which costs nothing and once hid a 570 ms settle."""
    requirements = [
        f"## Requirement {index}\n\nThe product needs {_title(index)}. It is measured, logged "
        "and reviewed like everything else in this part of the plan, and nobody ships it "
        "until its tests pass."
        for index in range(count)
    ]
    data = ("# Spec\n\n" + "\n\n".join(requirements) + "\n").encode()
    today = date.today().isoformat()
    documents, _document, _outcome = import_document(area, [], "spec", data, "spec.md", today)
    SetModuleDataCommand(project.id, SPEC_ID, write_index(SpecIndex(documents, []))).redo(library)


def _fill(library: Library, project: Project, count: int, unplaced: float) -> None:
    library.set_field(project.id, "summary", f"{count} steps of synthetic work.")
    start = date.today() - timedelta(days=40)
    SetModuleDataCommand(project.id, "estimation", write_start(start)).redo(library)
    assumptions = write_project(project, efficiency=0.6, team=(2, 1))
    SetModuleDataCommand(project.id, "time_estimates", assumptions).redo(library)

    steps: list[Step] = []
    for index in range(count):
        step = Step(title=f"Step {index}: {_title(index)}")
        AddNodeCommand(project.id, step).redo(library)
        steps.append(step)

    for index in range(1, count):
        sources = [steps[index - 1].id]
        if index % 3 == 0 and index > 1:
            extra = steps[random.randrange(0, index - 1)].id
            sources.append(extra)
        SetEdgesCommand(steps[index].id, "requires", sources).redo(library)
        if index % 10 == 0:
            related = steps[random.randrange(0, index)].id
            SetEdgesCommand(steps[index].id, "relates", [related]).redo(library)

    test_ids: list[str] = []
    for index, step in enumerate(steps):
        is_milestone = index % 15 == 14
        if is_milestone:
            SetModuleDataCommand(step.id, "step_milestone", milestone(f"M{index // 15 + 1}")).redo(
                library
            )
        elif index % 13 != 12:
            SetModuleDataCommand(step.id, "estimation", estimate(float(1 + index % 5))).redo(
                library
            )
        word = _status(index, count)
        if word != "pending":
            SetModuleDataCommand(step.id, "step_status", status(word)).redo(library)
        if index % 10 == 5:
            SetModuleDataCommand(
                step.id,
                "feature",
                feature_marker((FeatureSource("spec", f"The product needs {_title(index)}."),)),
            ).redo(library)
        if index % 7 == 3 and not is_milestone:
            SetModuleDataCommand(step.id, "step_agent_instruction", agent_state(True)).redo(library)
            library.set_text(step.id, "step_agent_instruction", f"Do step {index} carefully.")
        if index % 11 == 7:
            SetModuleDataCommand(step.id, "step_check", check(True)).redo(library)
        if index % 10 < 6:
            # Filed, both ways: a category so the Tests tab has headings to fold, and a
            # sort key so it has a run order inside them. A plan whose tests were all
            # unfiled would exercise neither, and every render and measurement reads this.
            category = TEST_CATEGORIES[index % len(TEST_CATEGORIES)][0]
            own = [
                Test(
                    f"T{100 + 2 * index}",
                    f"Step {index} does the thing",
                    # One body points at the test beside it, so the plan exercises the
                    # references a rendered body links and the preview they open.
                    f"Given, when, then. Run it after T{101 + 2 * index} passes.",
                    category=category,
                    sort_key=TEST_SORT_KEYS[index % len(TEST_SORT_KEYS)],
                ),
                Test(
                    f"T{101 + 2 * index}",
                    f"Step {index} survives a retry",
                    category=category,
                    sort_key=TEST_SORT_KEYS[(index + 1) % len(TEST_SORT_KEYS)],
                ),
            ]
            test_ids.extend(test.id for test in own)
            SetModuleDataCommand(step.id, "testing", tests(own)).redo(library)
        library.set_text(step.id, "step_description", DESCRIPTION.format(n=index))

    SetModuleDataCommand(
        project.id,
        "testing",
        write_catalog(project, [Category(name, icon) for name, icon in TEST_CATEGORIES]),
    ).redo(library)
    SetModuleDataCommand(project.id, "testing", runs.write(project, _runs(test_ids))).redo(library)
    SetModuleDataCommand(project.id, NOTES_ID, write_log(_notes(steps))).redo(library)

    placed = layered_flow(library, project)
    for step in steps:
        if unplaced and random.random() < unplaced:
            continue
        x, y = placed[step.id]
        SetModuleDataCommand(step.id, EDITOR_ID, write_position(x, y)).redo(library)


# What the synthetic plan files its tests under: a catalogue with glyphs, and the sort keys
# that order each category — the two axes a Tests tab is read by.
TEST_CATEGORIES = (
    ("Set up a new customer", "star"),
    ("Import measurements", "layers"),
    ("Reporting", "table"),
    ("Permissions", "shield"),
)
TEST_SORT_KEYS = (
    "Customer list view",
    "Customer detail view",
    "Import wizard",
    "Report designer",
)


def _title(index: int) -> str:
    words = ("index", "parser", "cache", "ledger", "gateway", "report", "export", "migration")
    verbs = ("build", "wire", "harden", "measure", "replace", "document", "test", "ship")
    return f"{verbs[index % len(verbs)]} the {words[(index // 3) % len(words)]}"


def _status(index: int, count: int) -> str:
    if index < count * 0.3:
        return "done"
    if index < count * 0.4:
        return "in-progress"
    if index % 37 == 0:
        return "blocked"
    return "pending"


def _runs(test_ids: list[str]) -> list[runs.Run]:
    history: list[runs.Run] = []
    for number in range(4):
        history = runs.started(history, test_ids, label=f"Run {number + 1}")
        opened = history[-1]
        for position, test_id in enumerate(test_ids):
            if (position + number) % 3 == 0:
                opened = runs.marked(opened, test_id, "ok")
            elif (position + number) % 7 == 0:
                opened = runs.marked(opened, test_id, "failed", "flaky on the second shard")
        history = runs.replaced(history, opened)
    return history


def _notes(steps: list[Step]) -> list[Note]:
    labels = ("decision", "handoff", "later", "spec-change")
    return [
        Note(
            f"N{number + 1}",
            labels[number % len(labels)],
            f"Note {number + 1} about step {number * 8}",
            f"Why step {number * 8} went the way it did.\n\n- One reason\n- Another",
            "2026-09-01",
            steps[number * 8].id,
        )
        for number in range(len(steps) // 8)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--projects", type=int, default=3)
    parser.add_argument("--unplaced", type=float, default=0.0, help="share left to auto-layout")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None, help="where the library goes")
    args = parser.parse_args()
    root = args.out or Path(tempfile.mkdtemp(prefix="dplanner-synthetic-"))
    root = root.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    library_file = build_library(
        root, steps=args.steps, projects=args.projects, unplaced=args.unplaced, seed=args.seed
    )
    elapsed = time.perf_counter() - started
    print(f"built {library_file} in {elapsed:.1f} s")
    print(f"dplanner window --library {library_file}")


if __name__ == "__main__":
    main()
