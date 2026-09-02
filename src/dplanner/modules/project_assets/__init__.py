"""The project's assets: one browser over every module's file areas, and the pool.

The catalog itself is :mod:`dplanner.domain.assets`; this module renders it (the Assets
tab), stages images before anything uses them (the pool — its own file area beside the
project), and names things (display titles in ``module_data``, because a content-addressed
file cannot carry a name and a link must never have to).
"""
