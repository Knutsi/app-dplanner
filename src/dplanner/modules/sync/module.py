"""Saving, in the sense of recording a version — across every repository in the library.

What Save means here: files are already on disk (autosave put them there); *Save* records
a version. One library spans several git repositories, so Save commits **each dirty
repository once**, scoped to that repository's project directories — the user's source
code is never swept up — and pushes where a remote exists. The unsaved-changes indicator
counts files across all of them.

Branch operations are different: a branch belongs to one repository, so New Branch and
Switch Branch act on the repository of the *focused project* and are disabled — with the
reason in the label — until a project is focused.

Membership changes at runtime (File ▸ New Project, Open Projects), so the service re-pulls its
repository groups whenever the library's structure changes.

**A branch switched underneath the window is taken in, and said.** A checkout is one
``git checkout`` in a terminal away, or an agent working in the checkout itself, and the
plan on screen is then another branch's without anything having said so — and autosave
writes the next edit to it. So every repository's branch is asked at the workspace
watcher's cadence and compared with the one this window last saw: a switch it did not
make is taken the way its own switch is (``_take_worktree``: the tree into the model, the
undo history dropped when anything was taken) and then warned about, naming the
repository and both branches. The window's own operations re-baseline when they end, so
only a switch from outside is ever reported.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox, QWidget

from dplanner.core.storage.provider import StorageError, StorageProvider
from dplanner.domain.model import Library, ProjectId
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import Context, ContextService
from dplanner.framework.session import SessionControl
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.window import StatusHost, UnsavedChangesHost
from dplanner.framework.window_watch import POLL_MS
from dplanner.modules.sync.exit_dialog import DirtyRepoRow, ExitDialog
from dplanner.modules.sync.save_progress import SaveProgressDialog
from dplanner.modules.sync.service import Publication, RepoGroup, SyncService
from dplanner.modules.sync.view import DiffDialog, IconLabel, UnsavedChangesButton
from dplanner.theme.icons import branch_icon, folder_icon
from dplanner.theme.themes import Theme


@dataclass(frozen=True)
class SyncDeps:
    actions: ActionRegistry
    autosave: AutosaveService
    context: ContextService
    status: StatusHost
    tasks: TaskService  # Storage operations surface in the task centre ("Saving", …).
    chrome: UnsavedChangesHost  # The headline "unsaved changes" flag and quit-time guard.
    theme: ThemeService  # The status-bar glyphs follow the theme's secondary text colour.
    parent: QWidget  # Dialog parent; also the service's QObject parent.
    switcher: SessionControl
    library: Library  # For its structure signal: membership changes re-pull the groups.
    library_path: Path
    # The store's repository face, wired by the composition root.
    repos: Callable[[], Sequence[StorageProvider]]
    repo_for: Callable[[ProjectId], StorageProvider | None]
    # The project the user is in: the focused project, or the focused step's project.
    focused_project: Callable[[Context], ProjectId | None]
    # The titles a repository group covers, for the diff picker and the quit dialog.
    projects_in: Callable[[RepoGroup], list[str]]
    # What a repository publishes beside its plan when it is saved — the reports site —
    # prepared on the GUI thread and run inside the save. None when there is nothing.
    publisher: Callable[[RepoGroup], Publication | None] = lambda _group: None


class SyncModule:
    id = "sync"

    def __init__(self, deps: SyncDeps) -> None:
        self._deps = deps
        self.service: SyncService | None = None
        self._worktree_changed = False
        # The branch each repository was on when this window last looked, by group.
        self._known_branches: dict[int, str] = {}
        # The quit-time save: its dialog while it runs, whatever failure it reported, and
        # whether it has ended — the close guard's second pass reads the last of these.
        self._exit_progress: SaveProgressDialog | None = None
        self._exit_error = ""
        self._exit_saved = False

    def register(self) -> None:
        deps = self._deps

        # Which library this window is on, in every configuration — it is the first thing
        # you want to know when two windows are open.
        path_label = IconLabel("WorkspacePathLabel")
        path_label.set_text(self._library_label())
        deps.status.add_status_widget(path_label)

        branch_label = IconLabel("SyncStatusLabel")
        deps.status.add_status_widget(branch_label)

        def paint_icons(theme: Theme) -> None:
            path_label.set_icon(folder_icon(theme.text_secondary))
            branch_label.set_icon(branch_icon(theme.text_secondary))

        deps.theme.changed.connect(paint_icons)
        paint_icons(deps.theme.current)

        service = SyncService(deps.repos, deps.tasks, parent=deps.parent)
        self.service = service
        # Membership is the library's own children: a step added to a project changes no
        # repository's groups, dirtiness or branch, and asking git for each one on every
        # pasted step was two subprocesses per repository per step on the GUI thread.
        deps.library.structure_changed.connect(
            lambda parent_id, *_: (
                self._on_membership(service) if parent_id == deps.library.id else None
            )
        )

        unsaved_button = UnsavedChangesButton()
        deps.status.add_status_widget(unsaved_button)
        diff_dialog = DiffDialog(deps.parent)

        def poke_context() -> None:
            # Action states re-evaluate on context change only, so a storage-state change
            # must trigger one — the same pattern the undo stack uses.
            deps.context.refresh()

        def refresh_label(*_args: object) -> None:
            group = self._focused_group(service, deps.context.current())
            branch = service.branch_of(group) if group is not None else ""
            shown = branch or "—"
            branch_label.set_text(f"{shown} — working…" if service.is_busy() else shown)

        # The branch label follows the focused project, so a selection change repaints it.
        deps.context.changed.connect(refresh_label)

        # Autosave must never race a checkout; pause() nests, and resume() happens when the
        # operation ends.
        service.before_operation = deps.autosave.pause

        # An operation that rewrote a working tree leaves the in-memory model stale: what
        # the checkout put there is taken into the model once the operation finishes.
        service.worktree_changed.connect(self._note_worktree_changed)

        def on_busy_changed(busy: bool) -> None:
            refresh_label()
            poke_context()
            if busy:
                return
            if self._exit_progress is not None:
                # The runner emits busy_changed(False) *before* failed(...), so the outcome
                # is only known on the next turn — by which time on_failed has run.
                QTimer.singleShot(0, self._exit_save_ended)
            if self._worktree_changed:
                # Autosave stays paused until the fresh tree is in the model, or it would
                # flush the stale one over it. singleShot hops out of this signal cascade.
                QTimer.singleShot(0, self._take_worktree)
                return
            deps.autosave.resume()
            service.refresh()
            self._check_branches(service, warn=False)  # An operation of ours just ended.

        service.busy_changed.connect(on_busy_changed)
        service.notice.connect(lambda text: deps.status.show_status(text, 5000))

        def on_failed(text: str) -> None:
            if self._exit_progress is not None:
                # Said where the person is looking, once: the progress dialog carries it.
                self._exit_error = text
                return
            QMessageBox.warning(deps.parent, "Storage", text)

        service.failed.connect(on_failed)
        service.saving.connect(self._on_saving)
        # Files reach disk 1.5 s after the last keystroke; that is also the earliest moment
        # "unsaved changes" could newly be true.
        deps.autosave.flushed.connect(service.refresh)

        def on_dirty_changed(dirty: bool, file_count: int) -> None:
            poke_context()
            unsaved_button.set_dirty(dirty, file_count)
            summary = f"{file_count} file{'s' if file_count != 1 else ''}" if dirty else ""
            deps.chrome.set_unsaved(dirty, summary)

        service.dirty_changed.connect(on_dirty_changed)

        def open_diff() -> None:
            diff_dialog.set_sources(
                [(self._group_label(group), group.diff) for group in service.groups()]
            )
            diff_dialog.show()  # Non-modal: reviewing a diff must not block editing.
            diff_dialog.raise_()
            diff_dialog.activateWindow()

        def save_from_dialog() -> None:
            # Through the registry rather than the service, so the button honours exactly
            # the same gate as File ▸ Save and Ctrl+S.
            deps.actions.run("sync.save", deps.context.current())
            diff_dialog.accept()

        unsaved_button.clicked.connect(open_diff)
        diff_dialog.save_button.clicked.connect(save_from_dialog)
        deps.chrome.add_close_guard(lambda: self._confirm_close(service))

        self._register_actions(service, open_diff)
        service.refresh()
        refresh_label()

        # The checkout can change under the window — a terminal, an agent working in it.
        # Asked at the workspace watcher's cadence, so a switch is noticed as its files are.
        self._check_branches(service, warn=False)
        branch_poll = QTimer(deps.parent)
        branch_poll.setInterval(POLL_MS)
        branch_poll.timeout.connect(lambda: self._check_branches(service))
        branch_poll.start()

    # -- labels --------------------------------------------------------------------------------

    def _library_label(self) -> str:
        path = self._deps.library_path
        home = Path.home()
        return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)

    def _group_label(self, group: RepoGroup) -> str:
        titles = ", ".join(self._deps.projects_in(group))
        count = group.dirty_file_count()
        files = f" · {count} file{'s' if count != 1 else ''}" if count else ""
        return f"{group.label}{files}" + (f" — {titles}" if titles else "")

    def _focused_group(self, service: SyncService, context: Context) -> RepoGroup | None:
        project_id = self._deps.focused_project(context)
        if project_id is None:
            return None
        group = self._deps.repo_for(project_id)
        return group if isinstance(group, RepoGroup) else None

    def _on_membership(self, service: SyncService) -> None:
        service.rewire()
        service.refresh()
        self._check_branches(service, warn=False)  # New groups: nothing was "underneath".

    # -- the checkout, watched -----------------------------------------------------------------

    def _check_branches(self, service: SyncService, *, warn: bool = True) -> None:
        """One tick: every repository's branch against the one this window last saw.

        ``warn=False`` takes the current branches as the baseline — at start, after a
        membership change and after an operation of ours, none of which happened
        underneath anybody. A tick during an operation stands down: the tree is moving on
        purpose, and the operation re-baselines when it ends. The branch is asked of git
        directly rather than through the service's second-long cache, because seeing a
        change is the whole point of asking.
        """
        if service.is_busy():
            return
        switched: list[tuple[RepoGroup, str, str]] = []
        for group in service.groups():
            branch = group.current_branch()
            known = self._known_branches.get(id(group))
            self._known_branches[id(group)] = branch
            if warn and known is not None and branch != known:
                switched.append((group, known, branch))
        if switched:
            self._branch_switched_underneath(switched)

    def _branch_switched_underneath(self, switched: Sequence[tuple[RepoGroup, str, str]]) -> None:
        """A checkout this window did not make: take the tree the way its own switch is
        taken, then say so — the plan on screen is another branch's now, and autosave
        writes the next edit to it."""
        deps = self._deps
        deps.autosave.pause()  # _take_worktree resumes, as after a switch of our own.
        self._take_worktree()
        deps.context.refresh()  # The branch label follows the focused project.
        lines = [f"{group.label}: {was} → {now}" for group, was, now in switched]
        deps.status.show_status("Branch switched outside DPlanner — " + "; ".join(lines), 8000)
        QMessageBox.warning(
            deps.parent,
            "Branch changed",
            "The plan repository switched branches outside DPlanner:\n\n"
            + "\n".join(f"• {line}" for line in lines)
            + "\n\nThe plan shown is now the one on the new branch, and so is every edit"
            " from here on. A plan kept inside its code repository switches with the"
            " code — an agent working in that checkout may have done this.",
        )

    # -- quitting ------------------------------------------------------------------------------

    def _publications(self, service: SyncService) -> dict[int, Publication]:
        """What each dirty repository publishes beside its plan, prepared now on the GUI
        thread — the model is read here — for the save to run and record."""
        found: dict[int, Publication] = {}
        for group in service.dirty_groups():
            publish = self._deps.publisher(group)
            if publish is not None:
                found[id(group)] = publish
        return found

    def _confirm_close(self, service: SyncService) -> bool:
        deps = self._deps
        if self._exit_saved:
            return True  # The save this guard started has ended; let the window go.
        if self._exit_progress is not None:
            return False  # One is already running, under its own dialog. Ask nothing twice.
        # The debounce means the very last edit may not be on disk yet: flush and re-check
        # before deciding, so quitting right after typing never loses the question.
        deps.autosave.flush_now()
        service.refresh()
        dirty = service.dirty_groups()
        if not dirty:
            return True
        rows = [DirtyRepoRow(label=self._group_label(group)) for group in dirty]
        dialog = ExitDialog(rows, deps.parent)
        if dialog.exec() != ExitDialog.DialogCode.Accepted:
            return False
        if dialog.discard:
            # Unchecked or discarded repositories stay dirty. Nothing is lost: the files
            # are on disk, and the next window shows the same unsaved count.
            return True
        chosen = [dirty[index] for index in dialog.checked_rows()]
        if not chosen:
            return True
        if not self._begin_exit_save(service, dialog.message(), chosen):
            return False  # Storage is busy; the notice says so and the window stays.
        # Not "no" — "not yet". The save runs as an ordinary task under its progress dialog,
        # and closing again is what ends the window once it has finished.
        return False

    def _begin_exit_save(self, service: SyncService, message: str, chosen: list[RepoGroup]) -> bool:
        """Start the quit-time save under its dialog; False when it could not be started."""
        labels = [self._group_label(group) for group in chosen]
        progress = SaveProgressDialog(labels, self._deps.parent)
        self._exit_progress = progress  # Set first: _on_saving reads it, and it is queued.
        self._exit_error = ""
        if not service.save(message, self._publications(service), only=chosen):
            self._exit_progress = None
            progress.deleteLater()
            return False
        progress.finished.connect(self._on_exit_progress_finished)
        progress.setModal(True)
        # Shown once the task is real, so a refused one never flashes a modal — and never
        # exec(): the guards run inside closeEvent, where a nested modal loop is re-entrant.
        progress.show()
        return True

    def _on_saving(self, index: int, phase: str) -> None:
        """Where the running save has got to — nothing to show unless we are quitting."""
        if self._exit_progress is not None:
            self._exit_progress.step(index, phase)

    def _exit_save_ended(self) -> None:
        progress = self._exit_progress
        if progress is None:
            return
        error, self._exit_error = self._exit_error, ""
        if error:
            progress.stopped(error)  # Stays up: the person chooses Close Anyway or Stay.
            return
        progress.accept()

    def _on_exit_progress_finished(self, result: int) -> None:
        progress, self._exit_progress = self._exit_progress, None
        if progress is not None:
            progress.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return  # Stay: the window keeps its unsaved changes and nobody lost a thing.
        self._exit_saved = True
        self._deps.parent.window().close()

    # -- actions -------------------------------------------------------------------------------

    def _register_actions(self, service: SyncService, open_diff: Callable[[], None]) -> None:
        deps = self._deps

        def ready(_context: Context) -> ActionState:
            return ActionState(enabled=not service.is_busy())

        def branch_ready(reason_label: str) -> Callable[[Context], ActionState]:
            def state(context: Context) -> ActionState:
                if service.is_busy():
                    return DISABLED
                if self._focused_group(service, context) is None:
                    return ActionState(enabled=False, label=reason_label)
                return ActionState(enabled=True)

            return state

        def run_save(_context: Context) -> None:
            deps.autosave.flush_now()  # Typing reaches disk before it is committed.
            service.refresh()
            service.save(publications=self._publications(service))

        def run_switch(context: Context) -> None:
            group = self._focused_group(service, context)
            if group is None:
                return
            names = service.branches(group)
            if not names:
                return
            current = service.branch_of(group)
            chosen, accepted = QInputDialog.getItem(
                deps.parent,
                "Switch Branch",
                "Branch:",
                names,
                names.index(current) if current in names else 0,
                False,
            )
            if not accepted or chosen == current:
                return
            deps.autosave.flush_now()
            self._run_guarded(lambda: service.switch_branch_sync(group, chosen))

        def run_new_branch(context: Context) -> None:
            group = self._focused_group(service, context)
            if group is None:
                return
            name, accepted = QInputDialog.getText(deps.parent, "New Branch", "Branch name:")
            if not accepted or not name.strip():
                return
            deps.autosave.flush_now()
            self._run_guarded(lambda: service.create_branch_sync(group, name.strip()))

        deps.actions.register(
            ActionSpec(
                id="sync.save",
                label="&Save",
                menu="File",
                group="save",
                order=10,
                shortcut="Ctrl+S",
                tip="Record a version in every repository with planning changes",
                state=ready,
                run=run_save,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="sync.review_changes",
                label="Rev&iew Changes…",
                menu="File",
                group="save",
                order=20,
                tip="See what has changed since the last save",
                state=ready,
                run=lambda _context: open_diff(),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="sync.new_branch",
                label="New &Branch…",
                menu="File",
                group="branch",
                order=10,
                tip="Start a new line of work in the focused project's repository",
                state=branch_ready("New &Branch — select a project first"),
                run=run_new_branch,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="sync.switch_branch",
                label="S&witch Branch…",
                menu="File",
                group="branch",
                order=20,
                tip="Move the focused project's repository to another line of work",
                state=branch_ready("S&witch Branch — select a project first"),
                run=run_switch,
            )
        )

        def run_pull(_context: Context) -> None:
            service.pull()

        def pull_ready(_context: Context) -> ActionState:
            if service.is_busy():
                return DISABLED
            if not service.has_any_remote():
                return ActionState(enabled=False, label="&Update from Remote — no remotes")
            return ActionState(enabled=True)

        deps.actions.register(
            ActionSpec(
                id="sync.pull",
                label="&Update from Remote",
                menu="File",
                group="branch",
                order=30,
                tip="Bring in work saved elsewhere, in every repository with a remote",
                state=pull_ready,
                run=run_pull,
            )
        )

    def _run_guarded(self, body: Callable[[], None]) -> None:
        """Run a synchronous storage operation with autosave paused, reporting failures.

        Synchronous on purpose: a checkout rewrites the files the application is showing,
        so taking them into the model must follow immediately rather than after an
        event-loop round trip.
        """
        deps = self._deps
        deps.autosave.pause()
        try:
            body()
        except StorageError as error:
            QMessageBox.warning(deps.parent, "Storage", str(error))
            deps.autosave.resume()
            return
        self._take_worktree()

    def _note_worktree_changed(self) -> None:
        self._worktree_changed = True

    def _take_worktree(self) -> None:
        """The working tree was rewritten under the window: read it into the model in place.

        The undo history is forgotten with it — its entries describe the tree that was
        checked out before, and replaying one onto this tree would be a stale edit — but
        only when the tree actually differed; a new branch off the current commit changes
        no plan file and keeps everything. Autosave resumes afterwards: the model now
        matches the tree, so a flush writes exactly what the user changes next.
        """
        deps = self._deps
        self._worktree_changed = False
        deps.switcher.refresh(forget_history=True)
        deps.autosave.resume()
        if self.service is not None:
            self.service.refresh()
            # Whatever branch the tree is on now is the window's own doing: the baseline.
            self._check_branches(self.service, warn=False)
