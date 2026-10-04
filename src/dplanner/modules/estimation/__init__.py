"""Estimation: how big a step is, when the work lands, and the reports over both.

The estimate on a step and the start date on a project are planning facts
(``planning/estimate.py``), and the schedule they imply is the planning tier's walk
(``planning/schedule.py``), because everything that reports it has to read one. This module
holds what a person and a terminal do with them: the editors, the bulk Estimates tab, the
verbs and the schedule's report.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
