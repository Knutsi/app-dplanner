"""Which key on the canvas means which verb.

**A canvas key names action ids; it is never an ``ActionSpec.shortcut``.** A bare ``H`` bound
to a menu-bar QAction fires wherever the application has focus, and would eat a keystroke in
the step description editor. Binding here instead means the key only exists while the canvas
has focus, and the verb it runs is the same one the menu, the palette and the toolbar run —
so the state gate still decides whether anything happens.

**A key names the verbs it means, in order; the first one the context allows runs.** That is
what lets one Delete key mean "remove these links" when edges are picked and "remove these
steps" when steps are, without a branch anywhere: the two actions already know which of them
applies. Keys with one meaning are a one-element tuple and read the same way.

This table is the whole binding layer. A rebinding feature reads it and writes a copy; today
nothing does, and that is the only reason it is a module constant rather than a setting.
"""

from typing import Final

from PySide6.QtCore import Qt

_NONE = Qt.KeyboardModifier.NoModifier

type Binding = tuple[int, Qt.KeyboardModifier]

CANVAS_KEYS: Final[dict[Binding, tuple[str, ...]]] = {
    # Movement: VIM's home row and the arrows, both saying the same thing.
    (Qt.Key.Key_H, _NONE): ("steps.go_left",),
    (Qt.Key.Key_Left, _NONE): ("steps.go_left",),
    (Qt.Key.Key_J, _NONE): ("steps.go_down",),
    (Qt.Key.Key_Down, _NONE): ("steps.go_down",),
    (Qt.Key.Key_K, _NONE): ("steps.go_up",),
    (Qt.Key.Key_Up, _NONE): ("steps.go_up",),
    (Qt.Key.Key_L, _NONE): ("steps.go_right",),
    (Qt.Key.Key_Right, _NONE): ("steps.go_right",),
    # Verbs.
    (Qt.Key.Key_C, _NONE): ("steps.connect",),
    (Qt.Key.Key_F, _NONE): ("canvas.frame",),
    (Qt.Key.Key_N, _NONE): ("steps.new",),
    (Qt.Key.Key_R, _NONE): ("steps.rename",),
    (Qt.Key.Key_Delete, _NONE): ("steps.unlink", "steps.delete", "regions.delete"),
    (Qt.Key.Key_Backspace, _NONE): ("steps.unlink", "steps.delete", "regions.delete"),
    # Modified, but still bound here rather than as a shortcut: Ctrl+A means "select the
    # text" in every editor, and only the canvas may take it to mean steps.
    (Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier): ("steps.select_all",),
}


def bound_actions(key: int, modifiers: Qt.KeyboardModifier) -> tuple[str, ...]:
    """The verbs this key means, most specific first. Empty when it means nothing here."""
    return CANVAS_KEYS.get((key, modifiers), ())
