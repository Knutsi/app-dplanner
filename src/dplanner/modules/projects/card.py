"""The Repositories card on the project panel: where the plan lives, which code it plans,
where that code is on this machine — three glyph rows — a remark while the plan lives
inside its code, and the two verbs that change any of it, run through the registry so
the palette and the Project menu agree with the card.
"""

from pathlib import Path

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId
from dplanner.domain.repositories import SEPARATED
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.projects.project_dialog import glyph_label, restyle
from dplanner.modules.projects.repos import RepositoryServices
from dplanner.modules.projects.repositories_folder import shown_path
from dplanner.theme.icons import ICON_SIZE, branch_icon, code_icon, folder_icon
from dplanner.theme.themes import Theme

ROW_GAP = 6
BLOCK_GAP = 12


class RepositoriesCard(QWidget):
    def __init__(
        self,
        library: Library,
        services: RepositoryServices,
        actions: ActionRegistry,
        context: ContextService,
        theme: ThemeService | None = None,
    ) -> None:
        super().__init__()
        self._library = library
        self._services = services
        self._project_id: NodeId | None = None

        self.plan_glyph, self.plan_text = glyph_label(self), QLabel(self)
        self.code_glyph, self.code_text = glyph_label(self), QLabel(self)
        self.checkout_glyph, self.checkout_text = glyph_label(self), QLabel(self)
        rows = QGridLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setHorizontalSpacing(8)
        rows.setVerticalSpacing(ROW_GAP)
        # Each value label's own name, to return to after a muted spell as #InspectorNote.
        self._names = {
            self.plan_text: "RepoCardPlan",
            self.code_text: "RepoCardCode",
            self.checkout_text: "RepoCardCheckout",
        }
        for row, (glyph, text) in enumerate(
            (
                (self.plan_glyph, self.plan_text),
                (self.code_glyph, self.code_text),
                (self.checkout_glyph, self.checkout_text),
            )
        ):
            text.setObjectName(self._names[text])
            text.setWordWrap(True)
            rows.addWidget(glyph, row, 0)
            rows.addWidget(text, row, 1)
        rows.setColumnStretch(1, 1)

        self.note = QLabel("The plan lives inside the code it plans.", self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        self.note.hide()

        self.settings_button = QPushButton("Settings…", self)
        self.settings_button.setObjectName("RepoCardSettings")
        self.settings_button.clicked.connect(
            lambda: actions.run("projects.settings", context.current())
        )
        self.move_button = QPushButton("Set up a plan repository…", self)
        self.move_button.setObjectName("RepoCardMove")
        self.move_button.clicked.connect(lambda: actions.run("projects.move", context.current()))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.settings_button)
        buttons.addWidget(self.move_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(BLOCK_GAP)
        layout.addLayout(rows)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

        self._unsubscribes = [
            library.field_changed.connect(lambda node_id, _field, _origin: self._changed(node_id)),
            services.checkout_changed.connect(self._changed),
        ]
        if theme is not None:
            self._unsubscribes.append(theme.changed.connect(self._paint))
            self._paint(theme.current)

    # -- the InspectorExtension contract ---------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._project_id = target_id
        self._refresh()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()

    # -- what it says ------------------------------------------------------------------------------

    def _changed(self, node_id: str) -> None:
        if node_id == self._project_id:
            self._refresh()

    def _refresh(self) -> None:
        project_id = self._project_id
        if project_id is None or not self._library.has(project_id):
            self.setEnabled(False)
            return
        self.setEnabled(True)
        facts = self._services.facts_of(project_id)
        self._set(
            self.plan_text, facts.plan_label or "not in a git repository", not facts.plan_root
        )
        self.plan_text.setToolTip(str(facts.plan_root or ""))
        self._set(
            self.code_text, facts.code_label or "no code repository recorded", not facts.repository
        )
        if facts.repository:
            checkout = facts.checkout
            where = shown_path(checkout) if checkout else "not checked out on this machine"
            self._set(self.checkout_text, where, checkout is None)
        else:  # The older shape: the plan's repository is where the code is.
            root = facts.plan_root or Path()
            self._set(self.checkout_text, shown_path(root) if facts.plan_root else "", False)
        self.note.setVisible(facts.warns)
        self.move_button.setVisible(facts.state != SEPARATED)  # Nothing to set up once apart.

    def _set(self, label: QLabel, text: str, muted: bool) -> None:
        label.setText(text)
        restyle(label, "InspectorNote" if muted else self._names[label])

    def _paint(self, theme: Theme) -> None:
        color = theme.text_secondary
        for glyph, painter in (
            (self.plan_glyph, branch_icon),
            (self.code_glyph, code_icon),
            (self.checkout_glyph, folder_icon),
        ):
            glyph.setPixmap(painter(color).pixmap(ICON_SIZE, ICON_SIZE))
