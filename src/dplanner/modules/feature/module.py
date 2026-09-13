"""The feature module in the running application: the Type toggle, the Feature tab and
the Specs tab's *Cite…* menu.

There is no list of features here and no verb that creates one: a feature *is* a step, so
``Step ▸ New`` and the toggle are how one arrives and ``Step ▸ Delete`` is how one goes.
What a feature *gathers* is still rendered by the module that owns tests — a list of tests
is testing's business.

The one gesture that births a step from this module is the Specs tab's *Cite…* ▸ *New
feature step…*: the spec module asks for a passage to be cited, and where no existing
feature is picked a step is born carrying it, through the ``place_step`` callback the
composition root writes over the graph editor. Neither module learns the other's name.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QInputDialog, QMenu, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.feature.aspect import (
    MODULE_ID,
    SPEC,
    FeatureSource,
    cited_at,
    is_feature,
    read,
    write,
)
from dplanner.modules.feature.editor import FeatureEditor
from dplanner.theme.icons import layers_icon


def _no_digest(_project_id: NodeId, _document: str) -> str:
    return ""


def _no_documents(_project_id: NodeId) -> list[str]:
    return []


# (project, title, the entry the new step is born carrying) → the new step's id. A feature
# step born where nobody pointed: the graph editor decides where it goes and gives birth to
# it, so this module never learns what a canvas is.
type PlaceFeatureStep = Callable[[NodeId, str, dict[str, Any]], StepId]


@dataclass(frozen=True)
class FeatureDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    sections: InspectorSectionRegistry
    parent: QWidget | None = None
    # The spec documents a passage can name — the editor's dropdown. Spec's business,
    # handed in so this module never learns how documents are stored.
    documents_of: Callable[[NodeId], list[str]] = _no_documents
    # (project id, document name) → the document's digest now — what a passage edited in
    # the editor is stamped with, so the spec module's read-time judgement has a base.
    digest_of: Callable[[NodeId, str], str] = _no_digest
    # Births a feature step somewhere free on the graph; None is a build with no canvas,
    # where *Cite…* offers only the features already there.
    place_step: PlaceFeatureStep | None = None


class FeatureModule:
    id = MODULE_ID

    def __init__(self, deps: FeatureDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.actions.register(
            aspect_toggle(
                id="feature.toggle",
                label=SPEC.label,
                order=20,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=is_feature,
                fresh=lambda _step, _project: write(),
                icon=layers_icon,
                tip="Make this step a feature: the work upstream of it flows into it, and "
                "its tests are read and run by it",
            )
        )
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=45,
                factory=lambda: FeatureEditor(
                    deps.library,
                    deps.undo,
                    deps.documents_of,
                    digest_of=deps.digest_of,
                ),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and is_feature(deps.library.step(step_id))
                ),
            )
        )

    # -- citing a passage into a feature -------------------------------------------------------

    def cite_passage(self, project_id: NodeId, document: str, quote: str, page: int | None) -> None:
        """Cite ``quote`` of ``document`` as a feature's passage — the window's half of
        ``feature cite``: a menu of the project's feature steps under the cursor, and
        *New feature step…* to start one on the spot."""
        menu = self.cite_menu(project_id, document, quote, page)
        menu.exec(QCursor.pos())
        menu.deleteLater()

    def cite_menu(self, project_id: NodeId, document: str, quote: str, page: int | None) -> QMenu:
        """The picker behind :meth:`cite_passage`, built without showing it: one entry per
        feature step and *New feature step…*, each writing one command when triggered."""
        library = self._deps.library
        steps = (
            [step for step in library.project(project_id).steps if is_feature(step)]
            if library.has(project_id)
            else []
        )
        menu = QMenu(self._deps.parent)

        def cite(step: Step | None) -> None:
            self._cite_into(project_id, step, document, quote, page)

        for known in steps:
            action = menu.addAction(known.title or "Untitled feature")
            action.triggered.connect(lambda _checked=False, step=known: cite(step))
        if self._deps.place_step is None:
            return menu
        if steps:
            menu.addSeparator()
        fresh = menu.addAction("New feature step…")
        fresh.triggered.connect(lambda _checked=False: cite(None))
        return menu

    def _cite_into(
        self,
        project_id: NodeId,
        step: Step | None,
        document: str,
        quote: str,
        page: int | None,
    ) -> None:
        """The passage onto ``step`` — or onto a step born carrying it, titled by the
        person, when it is None. One gesture, one undo entry either way."""
        source = FeatureSource(
            document=document,
            quote=quote,
            page=page,
            digest=self._deps.digest_of(project_id, document),
        )
        if step is None:
            place = self._deps.place_step
            if place is None:
                return
            title, accepted = QInputDialog.getText(self._deps.parent, "New Feature", "Feature:")
            if not accepted or not title.strip():
                return
            place(project_id, title.strip(), write((source,)))
            return
        cites = read(step) or ()
        if cited_at(cites, document, quote) is not None:
            return
        self._deps.undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write((*cites, source)), label="Cite Passage")
        )
