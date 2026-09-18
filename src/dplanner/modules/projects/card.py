"""The Repositories card on the project's dashboard: where the plan lives, then every
location the project names — one glyph row each, worded by ``repos.location_words`` so
the card and the Project dialog's table cannot say the same fact two ways — a remark
while the plan lives inside its code, and the two verbs that change any of it, run
through the registry so the palette and the Project menu agree with the card.
"""

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId
from dplanner.domain.repositories import SEPARATED
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.projects.locations_table import role_icon
from dplanner.modules.projects.project_dialog import glyph_label, restyle
from dplanner.modules.projects.repos import (
    MOVE_PLAN,
    SET_UP_PLAN,
    RepositoryServices,
    location_words,
    plan_lines,
)
from dplanner.theme.icons import ICON_SIZE, branch_icon
from dplanner.theme.themes import Theme

ROW_GAP = 6
BLOCK_GAP = 12
NO_LOCATIONS = "no code repository recorded"


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
        self._ink = ""

        self.plan_glyph, self.plan_text = glyph_label(self), QLabel(self)
        self.plan_text.setObjectName("RepoCardPlan")
        self.plan_text.setWordWrap(True)
        self.rows = QGridLayout()
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setHorizontalSpacing(8)
        self.rows.setVerticalSpacing(ROW_GAP)
        self.rows.addWidget(self.plan_glyph, 0, 0)
        self.rows.addWidget(self.plan_text, 0, 1)
        self.rows.setColumnStretch(1, 1)
        # One row per location, rebuilt on every refresh: the widgets are ours to hold
        # and drop, never read back out of the layout (CLAUDE.md's layout rules).
        self._held: list[tuple[QLabel, QLabel, str]] = []

        self.note = QLabel("The plan lives inside the code it plans.", self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        self.note.hide()

        self.settings_button = QPushButton("Settings…", self)
        self.settings_button.setObjectName("RepoCardSettings")
        self.settings_button.clicked.connect(
            lambda: actions.run("projects.settings", context.current())
        )
        self.move_button = QPushButton(SET_UP_PLAN, self)
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
        layout.addLayout(self.rows)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

        self._unsubscribes = [
            library.field_changed.connect(lambda node_id, _field, _origin: self._changed(node_id)),
            # Carries a repository, not a project: any checkout may be one of this
            # project's locations, so the card re-reads its facts.
            services.checkout_changed.connect(lambda _repository: self._refresh()),
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
        plan = plan_lines(facts)
        self.plan_text.setText(plan.identity)
        restyle(self.plan_text, "InspectorNote" if plan.identity_missing else "RepoCardPlan")
        self.plan_text.setToolTip(plan.location)
        for glyph, text, _role in self._held:
            self.rows.removeWidget(glyph)
            self.rows.removeWidget(text)
            glyph.deleteLater()
            text.deleteLater()
        self._held = []
        roles = self._services.roles
        for placement in facts.placements:
            words = location_words(placement, roles)
            glyph, text = glyph_label(self), QLabel(self)
            text.setObjectName("RepoCardLocation")
            text.setWordWrap(True)
            text.setText(f"{words.identity} — {words.where}")
            text.setToolTip(placement.location.repository)
            restyle(text, "InspectorNote" if words.missing else "RepoCardLocation")
            row = len(self._held) + 1
            self.rows.addWidget(glyph, row, 0)
            self.rows.addWidget(text, row, 1)
            self._held.append((glyph, text, placement.location.role))
        if not facts.placements:
            glyph, text = glyph_label(self), QLabel(NO_LOCATIONS, self)
            text.setObjectName("InspectorNote")
            text.setWordWrap(True)
            self.rows.addWidget(glyph, 1, 0)
            self.rows.addWidget(text, 1, 1)
            self._held.append((glyph, text, "code"))
        self._paint_rows()
        self.note.setVisible(facts.warns)
        # A plan apart from its code is not set up again — but it can still be moved, and
        # the button says which of the two this project is asking for.
        self.move_button.setText(MOVE_PLAN if facts.state == SEPARATED else SET_UP_PLAN)

    def texts(self) -> list[str]:
        """What the location rows say, top to bottom — the test seam."""
        return [text.text() for _glyph, text, _role in self._held]

    def _paint(self, theme: Theme) -> None:
        self._ink = theme.text_secondary
        self.plan_glyph.setPixmap(branch_icon(self._ink).pixmap(ICON_SIZE, ICON_SIZE))
        self._paint_rows()

    def _paint_rows(self) -> None:
        if not self._ink:
            return
        for glyph, _text, role in self._held:
            glyph.setPixmap(role_icon(role)(self._ink).pixmap(ICON_SIZE, ICON_SIZE))
