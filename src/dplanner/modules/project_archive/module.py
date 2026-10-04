"""The archive: Remove from Library that remembers, and the way back.

Archiving moves a project's directory to the library file's ``archived`` list, per user,
and the project is no longer loaded. The index's Archive folder (``archive_index.py``) and
the Archive tab (``archive_tab.py``) list it, and restoring is ``connect_project`` again —
the store's attach takes the directory off the list. The Project menu's membership band
(``verbs.py``) is this module's, Remove from Library included, because it acts on an
archived row as readily as on a live project.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.core.formats import UnsupportedFormatError
from dplanner.core.signals import Signal
from dplanner.core.storage.provider import StorageError
from dplanner.domain.model import Library, Project, ProjectId
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import ContextService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import notice
from dplanner.framework.window import StatusHost
from dplanner.modules.project_archive.archive_index import ArchiveSegment
from dplanner.modules.project_archive.archive_tab import ARCHIVE_KIND, ArchiveActivity
from dplanner.modules.project_archive.verbs import MembershipVerbs
from dplanner.theme.icons import archive_icon


@dataclass(frozen=True)
class ProjectArchiveDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    segments: IndexSegmentRegistry
    tabs: TabHost
    theme: ThemeService
    parent: QWidget
    status: StatusHost
    autosave: AutosaveService
    # Attach a directory and add the project to the library with the membership origin —
    # what restores an archived one.
    connect_project: Callable[[Path], Project]
    # Remove from Library: the store lets go, then the model.
    disconnect_project: Callable[[ProjectId], None]
    # The same, keeping the directory in the library file's archive.
    archive_project: Callable[[ProjectId], None]
    # The archive itself — the store's, per user — and the one edit not made by moving a
    # project: forgetting an entry.
    archived: Callable[[], list[Path]]
    archive_changed: Signal[()]
    forget_archived: Callable[[Path], None]
    # Whether a project still has edits that have not reached disk — an archived project
    # is never saved again, so it leaves only once they have.
    has_unflushed: Callable[[ProjectId], bool]


class ProjectArchiveModule:
    id = "project_archive"

    def __init__(self, deps: ProjectArchiveDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        MembershipVerbs(
            library=deps.library,
            parent=deps.parent,
            disconnect=deps.disconnect_project,
            archive=self.archive,
            restore=self.restore,
            forget=deps.forget_archived,
            archived=deps.archived,
            show_archive=lambda: self.open_archive(None, preview=False),
        ).register_into(deps.actions)
        deps.tabs.register_factory(
            ARCHIVE_KIND,
            lambda _target: ArchiveActivity(
                archived=deps.archived,
                changed=deps.archive_changed,
                actions=deps.actions,
                context=deps.context,
            ),
        )
        deps.segments.register(
            IndexSegment(
                id="archive",
                label="Archive",
                factory=lambda root: ArchiveSegment(
                    root,
                    archived=deps.archived,
                    changed=deps.archive_changed,
                    open_archive=lambda directory, preview: self.open_archive(
                        directory, preview=preview
                    ),
                    context=deps.context,
                    actions=deps.actions,
                    theme=deps.theme,
                ),
                order=40,  # Last, below Tests (20) and Docs (30): out of the way.
                icon=archive_icon,
            )
        )

    def archive(self, project_id: ProjectId) -> None:
        """Out of the library and into its archive — once its edits are on disk, because an
        archived project is never loaded, and so never saved, again."""
        deps = self._deps
        if not deps.library.has(project_id):
            return
        project = deps.library.project(project_id)
        title = project.title or project.folder_name
        deps.autosave.flush_now()
        if deps.has_unflushed(project_id):
            notice(
                deps.parent,
                "Archive Project",
                f"The last edits to “{title}” could not be written to disk, so it was not "
                "archived.",
            )
            return
        deps.archive_project(project_id)
        deps.status.show_status(f"“{title}” archived — Go ▸ Archive has it", 6000)

    def restore(self, directory: Path) -> None:
        """Back into the library: restoring is connecting, and the attach takes the
        directory off the archive."""
        deps = self._deps
        try:
            project = deps.connect_project(directory)
        except (StorageError, UnsupportedFormatError, OSError, json.JSONDecodeError) as error:
            notice(deps.parent, "Restore Project", f"{directory} could not be opened — {error}")
            return
        title = project.title or project.folder_name
        deps.status.show_status(f"“{title}” restored to the library", 4000)

    def open_archive(self, directory: Path | None, *, preview: bool) -> None:
        """Show the Archive tab, with ``directory``'s row picked when one is named."""
        activity = self._deps.tabs.open(ARCHIVE_KIND, preview=preview)
        if directory is not None and isinstance(activity, ArchiveActivity):
            activity.pick(directory)
