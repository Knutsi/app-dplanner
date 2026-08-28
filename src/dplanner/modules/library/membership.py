"""The membership origin — Qt-free, because both halves of the module carry it.

Adding or removing a project happens off the undo stack (a repository cannot be un-inited),
and the change is applied directly with this origin: no view made it, so none should
ignore it.
"""

LIBRARY_ORIGIN: object = object()
