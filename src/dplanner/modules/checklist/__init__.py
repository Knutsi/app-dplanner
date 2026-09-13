"""The Checklist: what this machine has, what is missing, and a remedy for each.

The rows come from every module that owns one — this package contributes the ones no
feature owns (git, the internet, the Azure CLI) and renders them all. The registry, the
report and the ``checklist show`` verb live in :mod:`dplanner.cli.checklist`, which is
what lets a terminal ask the same question.
"""
