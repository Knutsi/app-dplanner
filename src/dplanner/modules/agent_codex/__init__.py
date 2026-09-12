"""Codex as an agent harness: what Run Agent knows about it, in ``harness.py``.

Qt-free on purpose: the composition root reaches ``HARNESS`` from the CLI and the entry
point, and a provider module has no window half — an agent CLI is a command, a way to
resume it, the marks it leaves in its shells, and a reader of its own records.
"""
