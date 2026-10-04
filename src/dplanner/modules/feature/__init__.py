"""Features: the steps a project delivers, and the spec passages each was read from.

A feature is a **step** — its name is the step's title and its prose the step's description —
so what this package adds is the Type toggle, the Feature tab listing the passages, the Specs
tab's *Cite…* menu, ``dplanner feature …`` and the report's passages. ``migrate.py`` is how the
catalogue the feature records used to live in became each step's own entry. What a feature
*gathers* is ``domain/scope.py``'s answer.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
