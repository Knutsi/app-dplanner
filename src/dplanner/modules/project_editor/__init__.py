"""The canvas: a project's step graph, open in a tab.

Its modes, cards and marks, the scene, sorts and named layouts, stacks, the clipboard, the
minimap, the ruler, find and the canvas keymap. A step's aspects are edited in the Step
Details modal (``step_properties``), never beside the canvas.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
