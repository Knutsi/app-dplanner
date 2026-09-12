"""Getting DPlanner onto this machine, from the window: the ``dplanner`` command, the
desktop launcher and the agent skill, as one act — written exactly as ``dplanner install
all`` writes them.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
