"""The canvas: a project's step graph, open in a tab (``activity.py``).

Its modes, cards and marks, the scene, the minimap, find and the canvas keymap; and three
families in packages of their own — ``layouts/`` (positions, placement, sorts, named layouts,
the ruler), ``stacks/`` and ``clipboard/``. A step's aspects are edited in the Step Details
modal (``step_properties``), never beside the canvas. What it stores stays under the module
id ``project_editor``, the package's name before it was this one.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
