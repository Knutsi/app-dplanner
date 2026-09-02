"""Features: the things a project delivers, catalogued beside it and placed on its graph.

A feature is a **record** in the project's catalogue — read out of a spec, or added by
hand — and a feature **step** is that record's one instance on the graph: the work
upstream of it flows into it. The catalogue, the marker and the panel live here; what a
feature *gathers* is ``domain/scope.py``'s answer.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
