"""The product: what this workspace is planning, and where its code lives.

A window holds exactly one product, so this module has no list and no picker. It contributes
the tab that shows the product's identity, the window title, and the two CLI verbs that read
and write the same three fields.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import NodeId, Product
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import Context, ContextService, Uri, activity_uri
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import centered_column

MODULE_ID = "product"
PRODUCT_KIND = "product"

# The 4-point scale from DESIGN.md. A form is a section, so 8 px inside it and 12 px
# between it and the caption above.
FORM_SPACING = 8
SECTION_SPACING = 12
PAGE_MARGIN = 20
PAGE_WIDTH = 640


@dataclass(frozen=True)
class ProductDeps:
    product: Product
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Product]
    window: QMainWindow


class ProductActivity(ActivityBase):
    """The product's identity, as a form. Three fields, each an undoable command."""

    def __init__(self, product: Product, undo: UndoService[Product]) -> None:
        self._product = product
        self._undo = undo
        self._fields: dict[str, QLineEdit] = {}

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(SECTION_SPACING)

        caption = QLabel("Product")
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        note = QLabel("What this workspace plans, and where the code for it lives.")
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FORM_SPACING)
        for field, label, placeholder in (
            ("name", "Name", "What people call this product"),
            ("repository", "Repository", "https://github.com/owner/repo"),
            ("checkout", "Checkout", "Where this machine has it cloned"),
        ):
            editor = QLineEdit(str(getattr(product, field)))
            editor.setPlaceholderText(placeholder)
            editor.editingFinished.connect(lambda f=field: self._commit(f))
            self._fields[field] = editor
            form.addRow(label, editor)
        layout.addLayout(form)
        layout.addStretch(1)

        self._widget = centered_column(page, PAGE_WIDTH)
        self._unsubscribe = product.field_changed.connect(self._on_model_field)

    @property
    def uri(self) -> Uri:
        return activity_uri(PRODUCT_KIND)

    @property
    def title(self) -> str:
        return self._product.name or "Product"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def close(self) -> None:
        self._unsubscribe()

    def _commit(self, field: str) -> None:
        value = self._fields[field].text().strip()
        if value != getattr(self._product, field):
            self._undo.push(SetFieldCommand(self._product.id, field, value, view_origin=self))

    def _on_model_field(self, node_id: NodeId, field: str, origin: object) -> None:
        # The widget that made the edit already shows it; anyone else's change is applied.
        if origin is self or node_id != self._product.id or field not in self._fields:
            return
        self._fields[field].setText(str(getattr(self._product, field)))


class ProductModule:
    id = MODULE_ID

    def __init__(self, deps: ProductDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def open_product(_context: Context) -> None:
            deps.tabs.open(PRODUCT_KIND)

        deps.tabs.register_factory(
            PRODUCT_KIND, lambda _target: ProductActivity(deps.product, deps.undo)
        )
        deps.actions.register(
            ActionSpec(
                id="product.open",
                label="&Product Details…",
                menu="File",
                group="product",
                order=10,
                tip="Name this product, and say where its repository is",
                run=open_product,
            )
        )
        self._retitle()
        deps.product.field_changed.connect(lambda *_: self._retitle())

    def _retitle(self) -> None:
        """The window says which product it holds — the one thing a second window needs."""
        name = self._deps.product.name.strip()
        self._deps.window.setWindowTitle(f"{name} — DPlanner" if name else "DPlanner")
