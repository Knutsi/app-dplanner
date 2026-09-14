"""Coverage: the plan against the spec — milestones → features → passages → tests and
docs, drawn as four columns joined by lines, and printed by ``dplanner coverage``.

The tab is a drill-down: a milestone narrows the features, and a feature stands up the
passages it was read from and the tests and documents that prove it. The terminal's
``coverage show`` walks the same picture the other way, from the spec down.

``trace.py`` is the Qt-free picture both surfaces read; ``cli.py`` the verbs; ``module.py``
and ``scene.py`` the tab. The composition root imports the Qt half from ``module``.
"""
