"""Render the report over a synthetic project, for looking at it.

Builds a throwaway library and repository under a temporary directory — a plan with three
milestones, features, estimates, statuses, a description with a picture, tests with a run,
notes, a ticket — and runs the real ``dplanner report`` verbs over it: the page, the
workbook, one CSV, the table list and the site. Nothing touches the user's config or
library.

    uv run python scripts/render_sample_report.py --out /tmp/sample-report
    xdg-open /tmp/sample-report/report.html

Qt-free: the same path ``dplanner report`` takes from a terminal.
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from dplanner.cli.command import CliRegistry
from dplanner.cli.discovery import open_library
from dplanner.cli.gate import TopologyGate
from dplanner.cli.main import run
from dplanner.core.png import encode_rgb
from dplanner.core.storage.locations import init_repo
from dplanner.domain.assets import attach
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.estimation.aspect import write as estimate
from dplanner.modules.estimation.schedule import write_start
from dplanner.modules.feature.aspect import write as feature_marker
from dplanner.modules.feature.catalogue import FeatureRecord, write_catalogue
from dplanner.modules.notes.log import MODULE_ID as NOTES_ID
from dplanner.modules.notes.log import Note, write_log
from dplanner.modules.spec.aspect import read_topology
from dplanner.modules.step_milestone.aspect import write as milestone
from dplanner.modules.step_status.aspect import write as status
from dplanner.modules.step_ticket.aspect import Ticket
from dplanner.modules.step_ticket.aspect import write as ticket
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import Test
from dplanner.modules.testing.aspect import write as tests
from dplanner.modules.time_estimates.schedule import write_project

# (title, days, requires by index, status, kind)
PLAN: list[tuple[str, float | None, list[int], str, str]] = [
    ("Interview the three pilot teams", 3.0, [], "done", ""),
    ("Write the discovery brief", 2.0, [0], "done", ""),
    ("Discovery done", None, [1], "done", "milestone"),
    ("Design the search index", 4.0, [2], "done", ""),
    ("Build the indexer", 6.0, [3], "in-progress", "feature"),
    ("Query language parser", 5.0, [3], "in-progress", "feature"),
    ("Ranking experiments", 8.0, [4, 5], "pending", ""),
    ("Search results page", 4.0, [5], "blocked", "feature"),
    ("Load test at ten times traffic", 3.0, [4], "pending", "check"),
    ("Search rewrite ships", None, [6, 7, 8], "pending", "milestone"),
    ("Migrate saved searches", 3.0, [9], "pending", ""),
    ("Retire the old cluster", 2.0, [10], "pending", "agent"),
    ("Old cluster gone", None, [11], "pending", "milestone"),
]

DESCRIPTION = (
    "## What this is\n\nThe indexer reads every document and writes the inverted index.\n\n"
    "![the shard layout]({picture})\n\n- Batches of 500\n- Idempotent per shard\n\n"
    "See `indexer/README.md` for the shard protocol."
)


def build(root: Path) -> tuple[Path, Path]:
    library_file = root / "library.json"
    create_library(library_file)
    repo = init_repo(root / "plans")
    project_dir = seed_project(repo / "search-rewrite", "Search rewrite")
    with open_library(library_file, default_module_formats(), io.StringIO()) as context:
        project = context.store.attach(project_dir)
        library = context.library
        library.add_child(library.id, project)
        library.set_field(project.id, "summary", "Replace the search stack before the lease ends.")
        start = date.today() - timedelta(days=40)
        SetModuleDataCommand(project.id, "estimation", write_start(start)).redo(library)
        assumptions = write_project(project, efficiency=0.6, team=(2, 2))
        SetModuleDataCommand(project.id, "time_estimates", assumptions).redo(library)
        steps = _steps(library, project.id)
        picture = attach(
            context.store.files(steps[4].id, "step_description"), _gradient(), "gradient.png"
        )
        library.set_text(steps[4].id, "step_description", DESCRIPTION.format(picture=picture))
        library.set_text(steps[6].id, "step_description", "Try BM25 against the learned ranker.")
        jira = Ticket("Jira", "SRCH-42", "https://example.invalid/SRCH-42")
        SetModuleDataCommand(steps[7].id, "step_ticket", ticket(jira)).redo(library)
        _tests(library, project.id, steps)
        notes = [
            Note(
                "N1",
                "decision",
                "One index per tenant",
                "Cross-tenant queries are rare; isolation wins.",
                "2026-08-12",
                steps[3].id,
            ),
            Note(
                "N2",
                "decision",
                "Keep BM25 as the fallback ranker",
                "The learned ranker degrades on cold tenants.\n\n- Revisit after launch",
                "2026-09-01",
                steps[6].id,
            ),
        ]
        SetModuleDataCommand(project.id, NOTES_ID, write_log(notes)).redo(library)
    return library_file, project_dir


def _steps(library: Library, project_id: str) -> list[Step]:
    steps: list[Step] = []
    for title, _days, _requires, _status, _kind in PLAN:
        step = Step(title=title)
        AddNodeCommand(project_id, step).redo(library)
        steps.append(step)
    records = []
    for index, (title, days, requires, word, kind) in enumerate(PLAN):
        step = steps[index]
        if requires:
            SetEdgesCommand(step.id, "requires", [steps[i].id for i in requires]).redo(library)
        if days is not None:
            SetModuleDataCommand(step.id, "estimation", estimate(days)).redo(library)
        if word != "pending":
            SetModuleDataCommand(step.id, "step_status", status(word)).redo(library)
        if kind == "milestone":
            SetModuleDataCommand(step.id, "step_milestone", milestone(title)).redo(library)
        if kind == "feature":
            record = FeatureRecord(f"f{index}", title, f"The product needs **{title.lower()}**.")
            records.append(record)
            SetModuleDataCommand(step.id, "feature", feature_marker(record.id)).redo(library)
        if kind == "check":
            SetModuleDataCommand(step.id, "step_check", {"on": True}).redo(library)
        if kind == "agent":
            SetModuleDataCommand(step.id, "step_agent_instruction", {"on": True}).redo(library)
    SetModuleDataCommand(project_id, "feature", write_catalogue(records)).redo(library)
    SetEdgesCommand(steps[8].id, "relates", [steps[6].id]).redo(library)
    return steps


def _tests(library: Library, project_id: str, steps: list[Step]) -> None:
    indexer = [
        Test("T100", "Indexes a 1 GB corpus under an hour"),
        Test("T101", "Resumes after a crash"),
    ]
    SetModuleDataCommand(steps[4].id, "testing", tests(indexer)).redo(library)
    page = [Test("T102", "Renders 20 results in 200 ms")]
    SetModuleDataCommand(steps[7].id, "testing", tests(page)).redo(library)
    opened = runs.started([], ["T100", "T101", "T102"], label="Sprint 3")[-1]
    opened = runs.marked(opened, "T100", "ok")
    opened = runs.marked(opened, "T101", "failed", "hangs on shard 7")
    SetModuleDataCommand(project_id, "testing", runs.write([opened])).redo(library)


def _gradient() -> bytes:
    pixels = bytes(
        channel
        for y in range(48)
        for x in range(96)
        for channel in ((60 + x * 2) % 256, (120 + y * 2) % 256, 200)
    )
    return encode_rgb(96, 48, 96 * 3, pixels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_out = Path(tempfile.gettempdir()) / "dplanner-sample-report"
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="dplanner-sample-"))
    library_file, project_dir = build(root)

    registry = CliRegistry()
    gate = TopologyGate(record_path=None, topology_of=read_topology)
    registry.register_all(default_cli_commands(gate=gate))
    formats = default_module_formats()

    def dplanner(*argv: str) -> None:
        out = io.StringIO()
        code = run(registry, formats, ["--library", str(library_file), *argv], out, sys.stderr)
        sys.stdout.write(out.getvalue())
        if code:
            raise SystemExit(code)

    page = str(args.out / "report.html")
    dplanner("report", "html", "search-rewrite", "--out", page)
    dplanner("report", "xlsx", "search-rewrite", "--out", str(args.out / "report.xlsx"))
    csv_path = str(args.out / "order.csv")
    dplanner("report", "csv", "search-rewrite", "--table", "order", "--out", csv_path)
    dplanner("report", "tables", "search-rewrite")
    dplanner("report", "site", "search-rewrite")
    print(f"\nproject: {project_dir}")
    print(f"site:    {project_dir.parent / 'reports' / 'index.html'}")
    print(f"page:    {page}")


if __name__ == "__main__":
    main()
