"""Bindable text fields: what a text widget needs to know about the library.

Three methods — read it, turn an edit into a command, watch it — and
:class:`~dplanner.framework.text_binding.TextBinding` does the rest.

There is one field class rather than one per document, because prose is keyed by the module
that owns it rather than named as a field on the model. A module that wants an editable
document asks for ``ModuleTextField(library, node_id, MODULE_ID)`` and gets positional
editing for free: a keystroke costs one small splice, and several open views of the same
document stay in sync without rebuilding.
"""

from collections.abc import Callable

from dplanner.domain.commands import Command, EditTextCommand
from dplanner.domain.model import Library, NodeId, TextEdit


class ModuleTextField:
    """One module's prose on one node, edited positionally."""

    def __init__(self, library: Library, node_id: NodeId, key: str) -> None:
        self._library = library
        self._node_id = node_id
        self._key = key

    def read(self) -> str:
        return self._library.text(self._node_id, self._key)

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        edit = TextEdit(self._node_id, self._key, pos, removed, added)
        return EditTextCommand(edit, view_origin=origin)

    def connect(self, applied: Callable[[int, str, str, object], None]) -> Callable[[], None]:
        def on_edit(edit: TextEdit, origin: object) -> None:
            if edit.node_id == self._node_id and edit.key == self._key:
                applied(edit.pos, edit.removed, edit.added, origin)

        return self._library.text_edited.connect(on_edit)
