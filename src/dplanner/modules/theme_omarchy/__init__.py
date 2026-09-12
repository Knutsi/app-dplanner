"""Omarchy's desktop theme as a theme provider: the one being shown, and the person's own,
in ``themes.py``.

Qt-free on purpose, like the agent harness modules: a provider module has no window half.
The composition root lists it in ``theme_providers()``, and the framework's ``ThemeService``
does the watching.
"""
