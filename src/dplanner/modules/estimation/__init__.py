"""Estimation: how big a step is, when the work lands, and the reports over both.

More than a step aspect. This module owns the estimate on a step, the start date on a
project, the editors for both, and the schedule they imply — the derivation itself is the
domain's (``domain/schedule.py``), because everything that reports it has to read one walk.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
