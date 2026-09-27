"""New Project's code question — which code this project changes — asked so nobody can
skip it.

A plain combo box with nothing current until it is answered: the code repositories this
library already plans first, then the two ways to name another (*From GitHub…*, *A folder
on this computer…*), then *No code repository yet*, which is an answer too. A project made
without one is not read as its own code — it is *unset* (``domain/repositories.py``) — but
a question left silently blank is how a plan came to be read that way, so the dialog
refuses Create until one of these is picked.

The combo is a view of the dialog's draft, never a second record of it: the dialog says
what the draft holds (:meth:`CodeChoice.show_answer`) and hears what the person picked
through the signals, so a code row added or removed in the Locations table below moves it
too. The two *…* entries are verbs rather than answers — picking one puts the standing
answer back before the dialog asks, so a cancelled pick changes nothing.
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QComboBox, QWidget

from dplanner.core.storage.locations import canonical_remote, remote_label

PLACEHOLDER = "Where is the code this project changes?"
FROM_GITHUB = "From GitHub…"
FROM_FOLDER = "A folder on this computer…"
NO_CODE = "No code repository yet"

# What an entry stands for, kept in its data beside the repository it names.
_REPOSITORY, _GITHUB, _FOLDER, _NONE = "repository", "github", "folder", "none"


class CodeChoice(QComboBox):
    repository_chosen = QtSignal(str)  # One the library already plans, as it names it.
    github_requested = QtSignal()
    folder_requested = QtSignal()
    none_chosen = QtSignal()

    def __init__(self, planned: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CodeChoice")
        self.setPlaceholderText(PLACEHOLDER)
        self._planned = list(planned)
        self._repository = ""
        self._no_code = False
        self.activated.connect(self._picked)
        self.show_answer()

    def show_answer(self, repository: str = "", *, no_code: bool = False) -> None:
        """What the draft says: its primary code repository, that there is none yet, or
        — neither — no answer, which shows the question."""
        self._repository, self._no_code = repository, no_code and not repository
        listed = list(self._planned)
        if repository and not any(_same(repository, known) for known in listed):
            listed.insert(0, repository)
        self.blockSignals(True)
        self.clear()
        for known in listed:
            self.addItem(remote_label(known), (_REPOSITORY, known))
            self.setItemData(self.count() - 1, known, Qt.ItemDataRole.ToolTipRole)
        if listed:
            self.insertSeparator(self.count())
        self.addItem(FROM_GITHUB, (_GITHUB, ""))
        self.addItem(FROM_FOLDER, (_FOLDER, ""))
        self.insertSeparator(self.count())
        self.addItem(NO_CODE, (_NONE, ""))
        self.setCurrentIndex(self._answer_index())
        self.blockSignals(False)

    def answered(self) -> bool:
        return bool(self._repository) or self._no_code

    def texts(self) -> list[str]:
        """Every entry's words, top to bottom, separators left out — the test seam."""
        return [self.itemText(index) for index in range(self.count()) if self.itemData(index)]

    def pick(self, text: str) -> None:
        """Choose the entry that says ``text``, as a click would — the test seam."""
        self._picked(self.findText(text))

    def _answer_index(self) -> int:
        for index in range(self.count()):
            data = self.itemData(index)
            if not data:
                continue
            kind, repository = data
            if self._repository and kind == _REPOSITORY and _same(repository, self._repository):
                return index
            if self._no_code and kind == _NONE:
                return index
        return -1

    def _picked(self, index: int) -> None:
        data = self.itemData(index)
        if not data:
            return
        kind, repository = data
        # The standing answer first: a verb that is cancelled, or refused, leaves it.
        self.setCurrentIndex(self._answer_index())
        if kind == _REPOSITORY:
            self.repository_chosen.emit(repository)
        elif kind == _GITHUB:
            self.github_requested.emit()
        elif kind == _FOLDER:
            self.folder_requested.emit()
        else:
            self.none_chosen.emit()


def _same(one: str, other: str) -> bool:
    return canonical_remote(one) == canonical_remote(other)
