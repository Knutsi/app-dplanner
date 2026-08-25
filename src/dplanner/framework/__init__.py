"""The Qt-aware application framework.

The framework knows nothing about what your application is for. It provides the machinery
modules plug into: tab-hosted activities, a URI context graph, a context-driven action
registry with a dynamic menu bar, palette, toolbar and context menus, a single undo stack,
an observable task list, a vendor-neutral LLM facade, and the registries that make up every
surface a feature can occupy.

Modules (under :mod:`dplanner.modules`) register everything user-visible. Nothing here
imports them, and ``tests/test_architecture.py`` fails the build if that ever changes.
"""
