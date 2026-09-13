"""Reporting in the window: exports, a preview, the on-Save publisher, a settings page.

Every path here builds the same :class:`~dplanner.cli.report.assemble.Report` the terminal
builds, **on the GUI thread** — that is the read of the model — and renders and writes it
**on a worker**, through this module's own ``TaskRunner``, so a big plan's page shows up in
the task centre rather than freezing the window. A report is plain data, which is what
makes the hand-over safe; nothing on the worker touches a ``Step``.

**File ▸ Export ▸ Plan Report (HTML / PDF)…, Plan Tables (Excel)…** ask for a path the way
the order list's CSV does and write there. **Project ▸ Preview Report** writes to a
per-run temporary directory and opens the browser on it — the fast loop for looking at
the plan as a bystander would.

**Save publishes.** The sync module asks :meth:`ReportingModule.prepare_publication` for
each dirty repository before it commits; the answer is a closure the save runs on its own
worker, which writes the repository's site under ``reports/`` and hands back the paths to
record in the same commit. The switch (Settings ▸ Reports, per user, on by default) is the
only thing read here that is not the plan. A clean plan with a stale site publishes
nothing on Save — the settings page's *Write Now* is for that.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QWidget

from dplanner.cli.report import page, sheets, website
from dplanner.cli.report.assemble import Report, build
from dplanner.cli.report.parts import ReportSource
from dplanner.domain.model import Library, ProjectId, Step
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.user_config import get_global
from dplanner.framework.window import StatusHost
from dplanner.modules.reporting import paper
from dplanner.modules.reporting.settings_page import MODULE_ID, PUBLISH_KEY, build_page

BUSY_NOTICE = "Still writing the last report — try again in a moment"
NOTICE_MS = 5000

Publication = Callable[[], Sequence[str]]


@dataclass(frozen=True)
class ReportingDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tasks: TaskService
    status: StatusHost
    settings_sections: SettingsSectionRegistry
    parent: QWidget  # The export dialogs' window, and the runner's owner.
    files: FilesFor
    project_dir: Callable[[ProjectId], Path]
    repo_root: Callable[[ProjectId], Path | None]
    plan_remote: Callable[[ProjectId], str]
    # The same sources `dplanner report` reads, and the readers every step row needs.
    sources: Sequence[ReportSource]
    key_of: Callable[[Step], str]
    kind_of: Callable[[Step], str]
    status_for: Callable[[Step], str]


class _Writer(QObject):
    """Owns the runner; what a body wrote comes back on a queued Qt signal, the one seam
    a runner has — and the parenting is deliberate: a parentless QObject holding a
    self-connected signal is a cycle Python frees whenever the collector next runs, which may
    be inside somebody else's event loop. Parented, it dies with the build."""

    written = QtSignal(str, str)  # (what, path)

    def __init__(self, tasks: TaskService, parent: QObject) -> None:
        super().__init__(parent)
        self.runner = TaskRunner(tasks, parent=self)


def publish_on_save() -> bool:
    return bool(get_global(MODULE_ID, PUBLISH_KEY, True))


class ReportingModule:
    id = MODULE_ID

    def __init__(self, deps: ReportingDeps) -> None:
        self._deps = deps
        self._writer: _Writer | None = None

    def register(self) -> None:
        deps = self._deps
        self._writer = _Writer(deps.tasks, deps.parent)
        self._writer.written.connect(self._on_written)
        exports = (
            ("html", "Plan &Report (HTML)…", 20, "Write the plan as one HTML page"),
            ("pdf", "Plan Report (&PDF)…", 30, "Write the plan as a PDF"),
            ("xlsx", "Plan &Tables (Excel)…", 40, "Every table of the plan as a workbook"),
        )
        for kind, label, order, tip in exports:
            deps.actions.register(
                ActionSpec(
                    id=f"report.{kind}",
                    label=label,
                    menu="File",
                    group="export",
                    submenu="Export",
                    order=order,
                    tip=tip,
                    state=self._on_a_project,
                    run=self._exporter(kind),
                )
            )
        deps.actions.register(
            ActionSpec(
                id="report.preview",
                label="Preview &Report",
                menu="Project",
                group="open",
                order=60,
                tip="Open the plan's report in the browser",
                state=self._on_a_project,
                run=self._preview,
            )
        )
        deps.settings_sections.register(
            SettingsSection(
                id=MODULE_ID,
                category=("Reports",),
                factory=lambda parent: build_page(
                    parent,
                    write_now=self.write_site,
                    busy_changed=self._writer.runner.busy_changed if self._writer else None,
                ),
            )
        )

    # -- the report --------------------------------------------------------------------------

    def build(self, project_id: ProjectId) -> Report:
        """The report, read from the model now — GUI thread only."""
        deps = self._deps
        return build(
            deps.library,
            deps.library.project(project_id),
            deps.files,
            deps.sources,
            key_of=deps.key_of,
            kind_of=deps.kind_of,
            status_for=deps.status_for,
            plan_remote=deps.plan_remote(project_id),
        )

    def prepare_publication(
        self, repo_root: Path, project_ids: Sequence[ProjectId]
    ) -> Publication | None:
        """Save's hook: None when the switch is off, else the repository's site to write."""
        if not publish_on_save():
            return None
        return self._publication(repo_root, project_ids)

    def _publication(self, repo_root: Path, project_ids: Sequence[ProjectId]) -> Publication:
        deps = self._deps
        reports = [
            (website.slug_for(deps.project_dir(project_id), repo_root), self.build(project_id))
            for project_id in project_ids
        ]

        def publish() -> Sequence[str]:
            pages = [
                website.SiteReport(
                    slug,
                    page.render(report, about=page.about_text(report)),
                    page.summary_script(report, slug),
                )
                for slug, report in reports
            ]
            return website.write(repo_root, pages)

        return publish

    def write_site(self) -> None:
        """Settings' Write Now: every repository's site, whatever the switch says."""
        deps = self._deps
        by_root: dict[Path, list[ProjectId]] = {}
        for project in deps.library.projects:
            root = deps.repo_root(project.id)
            if root is not None:
                by_root.setdefault(root, []).append(project.id)
        publications = [(root, self._publication(root, ids)) for root, ids in by_root.items()]
        writer = self._writer
        assert writer is not None

        def body() -> None:
            for root, publish in publications:
                publish()
                writer.written.emit("site", str(root / website.REPORTS_DIR))

        self._run("Writing report sites", body, key="report.site")

    # -- the verbs ---------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        return ENABLED if self._focused(context) is not None else DISABLED

    def _focused(self, context: Context) -> ProjectId | None:
        library = self._deps.library
        project_id = context.focus_entity("project")
        if project_id is not None and library.has(project_id):
            return project_id
        step_id = context.focus_entity("step")
        if step_id is not None and library.has(step_id):
            return library.project_of(step_id).id
        return None

    def _exporter(self, kind: str) -> Callable[[Context], None]:
        return lambda context: self._export(context, kind)

    def _export(self, context: Context, kind: str) -> None:
        deps = self._deps
        project_id = self._focused(context)
        if project_id is None:
            return
        title = deps.library.project(project_id).title or "Untitled project"
        suffix, filter_text, dialog_title = {
            "html": (".html", "Web pages (*.html)", "Export Plan Report"),
            "pdf": (".pdf", "PDF files (*.pdf)", "Export Plan Report"),
            "xlsx": (".xlsx", "Excel workbooks (*.xlsx)", "Export Plan Tables"),
        }[kind]
        suggested = f"{title} plan report{suffix}"
        chosen, _filter = QFileDialog.getSaveFileName(
            deps.parent, dialog_title, str(Path.home() / suggested), filter_text
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        report = self.build(project_id)
        self._write(kind, report, path)

    def _preview(self, context: Context) -> None:
        project_id = self._focused(context)
        if project_id is None:
            return
        report = self.build(project_id)
        directory = Path(tempfile.mkdtemp(prefix="dplanner-report-"))
        self._write("preview", report, directory / "index.html")

    def _write(self, kind: str, report: Report, path: Path) -> None:
        writer = self._writer
        assert writer is not None

        def body() -> None:
            if kind in ("html", "preview"):
                path.write_text(
                    page.render(report, about=page.about_text(report)),
                    encoding="utf-8",
                    newline="\n",
                )
            elif kind == "pdf":
                paper.write(report, path)
            else:
                sheets.write_workbook(path, report)
            writer.written.emit(kind, str(path))

        self._run("Writing report", body, key=f"report.{kind}")

    def _run(self, label: str, body: Callable[[], None], *, key: str) -> None:
        writer = self._writer
        assert writer is not None
        if not writer.runner.run(label, body, key=key, keep_finished=True):
            self._deps.status.show_status(BUSY_NOTICE, NOTICE_MS)

    def _on_written(self, kind: str, path: str) -> None:
        if kind == "preview":
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        what = "Report site" if kind == "site" else "Report"
        self._deps.status.show_status(f"{what} written to {path}", NOTICE_MS)
