"""The plan as a page for people who have no DPlanner: what modules say, assembled, drawn.

``parts.py`` is the vocabulary a module's Qt-free ``report.py`` speaks; ``assemble.py``
merges every module's contribution into one :class:`~dplanner.cli.report.assemble.Report`;
``page.py`` and ``drawings.py`` draw it as a single HTML file with inline SVG; ``sheets.py``
writes its tables as CSV and XLSX; ``website.py`` lays the reports of one plan repository
out as a browsable site; ``commands.py`` is ``dplanner report``. The window's half —
the export actions, the on-Save publisher and the PDF — is ``modules/reporting/``.

It lives under ``cli/`` for the reason ``lint.py`` does: a report is a question about
*every* feature at once, no module may import another, and this layer is the highest one
that is still Qt-free and reachable from both surfaces.
"""
