"""The spec module: a project's specification documents, their figures, and the project's
topology.

A document is imported beside the project (or written in the Specs tab's markdown editor)
and read by people and agents alike; what it *asks for* is read into features by the
feature module, whose passages this module anchors in the text on every read
(``documents.anchor_sources`` over ``core/anchors.py``) and washes in the Specs tab
(``show_passages``). Figures rendered from a page travel beside a step with its briefing.

A document may also come from a **source** — a Confluence page or folder — through a
document source kind the module runs (``source_kind.py`` is the contract, ``sourced.py``
applies what a kind fetched, ``refresh.py`` fetches and checks off the GUI thread).

``documents.py``, ``sourced.py``, ``pdf.py``, ``aspect.py`` and ``cli.py`` are Qt-free;
the composition root imports the Qt half from ``module``.
"""
