"""Confluence Cloud as a spec source: a page or a folder, read into one markdown document
per page beside the project, images included, and never written back.

``client.py`` (GET-only HTTP over the stdlib), ``convert.py`` (storage XHTML to markdown)
and ``source.py`` (the walk, the caps, the URL a person pastes) are Qt-free; the
composition root imports the Qt half — the Connect dialog, the settings page and the
module object that is the spec module's *document source kind* — from ``module``.
"""
