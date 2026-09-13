"""A folder on this computer as a spec source.

``source.py`` is the Qt-free half — the locator and the thin wrappers over
``domain/document_folder.py``'s walk, which this kind shares with ``spec_git``. ``module.py``
is the kind itself. The composition root imports the Qt half from ``module``; nothing is
re-exported here, so the CLI can reach the headless files without loading a graphics stack.
"""
