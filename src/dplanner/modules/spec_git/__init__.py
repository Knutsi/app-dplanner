"""A git repository as a spec source.

``client.py`` and ``source.py`` are the Qt-free halves — the subprocess door and the
locator, the fetch, the check and the size guard; ``connect.py`` and ``module.py`` are the
Qt ones. The composition root imports the kind from ``module``; nothing is re-exported
here, so the headless files stay reachable without a graphics stack.
"""
