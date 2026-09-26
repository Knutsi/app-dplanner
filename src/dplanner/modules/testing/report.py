"""What testing says in a report: each step's tests with their latest result, and one
table of every test for the person who runs them.

A test result is not a step status (``ARCHITECTURE.md``), so the table shows the result's
own words — ok, failed, skipped, or nothing yet — beside the step the test belongs to.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable
from datetime import date

from dplanner.cli.report.parts import (
    Column,
    Contribution,
    Facet,
    Placed,
    ReportSource,
    Row,
    Table,
)
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import audience_words, read
from dplanner.modules.testing.filing import category_of

TABLE_ID = "tests"
NOT_RUN = "not run"


def report_source(*, key_of: Callable[[Step], str]) -> ReportSource:
    def source(_library: Library, project: Project, _files: FilesFor, _day: date) -> Contribution:
        latest = runs.latest_results(runs.read(project))
        facets = {}
        rows: list[Row] = []
        for step in project.steps:
            tests = [test for test in read(step) if not test.archived]
            if not tests:
                continue
            lines = []
            for test in tests:
                outcome = latest.get(test.id)
                result = outcome.result.status if outcome is not None else NOT_RUN
                lines.append(f"- **{test.id}** {test.title} — {audience_words(test)} — {result}")
                rows.append(
                    Row(
                        (
                            test.id,
                            test.title,
                            category_of(test),
                            audience_words(test),
                            key_of(step),
                            result,
                            outcome.run.id if outcome else "",
                        ),
                        step_id=step.id,
                    )
                )
            facets[step.id] = (Facet("Tests", "\n".join(lines), kind="markdown"),)
        if not rows:
            return Contribution(facets=facets)
        table = Table(
            TABLE_ID,
            "Tests",
            (
                Column("Test", "key"),
                Column("Title"),
                # Filterable, both of them: a published page is read by whoever the plan is
                # shared with, and "show me the QA tests" and "show me the import tests" are
                # the two questions they arrive with.
                Column("Category", filter=True),
                Column("Audience", filter=True),
                Column("Step", "key"),
                Column("Latest result", "status"),
                Column("Run", "key"),
            ),
            tuple(rows),
            note="The latest result is the newest run that recorded one; a test nobody has "
            "run yet says so. A test that does not say who it is for reads as Other, and one "
            "filed under nothing reads as Uncategorised.",
        )
        return Contribution(placed=(Placed("steps", 20, table),), facets=facets)

    return source
