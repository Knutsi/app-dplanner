"""Projects: a project's lifecycle in this library — making, joining, sharing and placing one.

The Projects folder in the index (``index.py``) and the project verbs (``verbs.py``); *File ▸
New Project…* and *Project ▸ Settings…*, both the Project dialog (``project_dialog.py``: its
code question in ``code_choice.py``, the Locations table and its dialog); *Open Project…*,
the wizard (``open_dialog.py`` over the link, browse and Repositories pages); *Share
Project…*; Move Plan; and the repository plumbing they all share — the plan-repository
picker (``repo_picker.py``), the repositories folder and clone policy, the checkout service
a verb gets a repository from, and the :class:`RepositoryServices` bundle the root fills in
(``repos.py``). One package because those surfaces share these widgets: split, each half
would import the other. ``cli.py`` is the ``project`` and ``location`` nouns.

Elsewhere: the tab a project opens into is ``canvas``'s, the archive and Remove from Library
are ``project_archive``'s, and the ``step`` noun is ``steps``'.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
