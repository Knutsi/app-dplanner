"""What is wrong with a plan, said where it is fixed.

The panel beside the canvas is a **second presenter of the lint registry** — the same
``lint_checks()`` every module already exports and ``dplanner project lint`` already
reads — exactly as ``modules/checklist/`` is the window's presenter of
``cli/checklist.py``. There is no second registry and no new finding shape.

The composition root imports ``dplanner.modules.problems.module``; nothing is re-exported
here, so the package stays importable without loading Qt.
"""
