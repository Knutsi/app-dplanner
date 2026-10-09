"""Run Agent: launching an agent on a step, from the window and from ``dplanner agent run``.

The one launch order both surfaces go through (``launch.py``) and the claim it makes on the
plan (``workflows.py``); a headless run under its supervisor or, with ``--terminal``, a shell
in a terminal (``launcher.py``: the terminals and the wrapper script); launch profiles and
their settings page; whether each agent CLI can run here (``availability.py``,
``checks.py``); and *Autonomous Work ▸ Local*, which launches a coordinator over a selection.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
