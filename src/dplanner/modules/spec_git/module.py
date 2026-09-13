"""A git repository as a document source kind.

Like the folder kind it registers nothing — the spec module mints the + menu's entry from
the kinds it is handed — so it is constructed beside the others rather than listed as a
module. It has no credential of its own: the person's git does the auth, which is why
``connect`` is a proof rather than a form, and why nothing here reaches a keychain.

The cache root arrives on ``Deps``. No feature module names ``config_dir`` — the
composition root resolves the path and hands it over, the ``TopologyGate(record_path=…)``
shape — which is also what lets a test point the whole thing at ``tmp_path``.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal
from dplanner.domain.document_source import (
    Freshness,
    Locator,
    Snapshot,
    SourceStatus,
    SourceUnavailableError,
)
from dplanner.framework.tasks import TaskService
from dplanner.modules.spec_git.client import git_path
from dplanner.modules.spec_git.connect import GitSourceDialog
from dplanner.modules.spec_git.source import (
    KIND,
    Probe,
    check,
    fetch,
    open_url,
    probe,
    valid_locator,
)
from dplanner.theme.icons import branch_icon

# The directory under the per-user config the composition root hands over. Named here,
# because the shape of the cache is this module's business and the path is the root's.
SPEC_GIT_CACHE = "spec-git"

REFUSAL = "this source's address is not a git repository"
NO_GIT = "git is not installed — a Git repository source needs git on PATH"


@dataclass(frozen=True)
class SpecGitDeps:
    tasks: TaskService
    cache_root: Path  # Per user, per machine, never the plan: config_dir()/spec-git.


class SpecGitKind:
    """Satisfies :class:`dplanner.modules.spec.source_kind.DocumentSourceKind`."""

    id = KIND
    name = "Git"
    label = "&Git Repository…"

    def __init__(self, deps: SpecGitDeps) -> None:
        self._deps = deps
        self.config_changed: Signal[()] = Signal("spec_git.config_changed")

    @staticmethod
    def icon(color: str | QColor) -> QIcon:
        return branch_icon(color)

    def locate(self, parent: QWidget) -> tuple[str, Locator] | None:
        dialog = self._dialog(parent)
        try:
            if dialog.exec() != GitSourceDialog.DialogCode.Accepted:
                return None
            return dialog.chosen()
        finally:
            dialog.deleteLater()

    def status(self, locator: Locator) -> SourceStatus:
        """Two questions and no subprocess — it runs on every context change.

        It deliberately does not look at the cache: "ready" here means *we can try*. There
        is no credential to have or not have, and a cache that was swept is not a reason to
        grey a verb.
        """
        if valid_locator(locator) is None:
            return SourceStatus(False, REFUSAL)
        if git_path() is None:
            return SourceStatus(False, NO_GIT)
        return SourceStatus(True)

    def connect(self, parent: QWidget, locator: Locator) -> bool:
        """No credential is obtained and none is stored: this proves the repository can be
        read from this computer now, and says what to do when it cannot."""
        valid = valid_locator(locator)
        if valid is None or git_path() is None:
            return False
        dialog = self._dialog(parent, valid)
        try:
            proved = dialog.exec() == GitSourceDialog.DialogCode.Accepted and dialog.passed
        finally:
            dialog.deleteLater()
        if proved:
            self.config_changed.emit()
        return proved

    def open_url(self, locator: Locator) -> str:
        valid = valid_locator(locator)
        return open_url(valid) if valid else ""

    def fetch(
        self,
        locator: Locator,
        known: Mapping[str, str],
        progress: Callable[[float], None],
        cancelled: Callable[[], bool],
    ) -> Snapshot:
        return fetch(self._deps.cache_root, self._demand(locator), known, progress, cancelled)

    def check(self, locator: Locator, known: Mapping[str, str]) -> Freshness:
        return check(self._deps.cache_root, self._demand(locator), known)

    # -- internals -------------------------------------------------------------------------------

    def _dialog(self, parent: QWidget | None, locator: Locator | None = None) -> GitSourceDialog:
        # A plain closure over the cache root, never a bound method: the worker that runs
        # it must not reach this object, which holds Deps that reach a widget.
        cache_root = self._deps.cache_root

        def look(url: str, ref: str) -> Probe:
            return probe(cache_root, url, ref)

        return GitSourceDialog(parent, tasks=self._deps.tasks, probe=look, locator=locator)

    def _demand(self, locator: Locator) -> Locator:
        valid = valid_locator(locator)
        if valid is None:
            raise SourceUnavailableError(REFUSAL)
        if git_path() is None:
            raise SourceUnavailableError(NO_GIT)
        return valid
