"""Specification documents beside a project, the requirements marked in them, and the
steps those requirements justify.

A project carries imported spec documents (PDF, markdown, plain text). An agent reads
them, marks **requirements** — named obligations anchored to a document — and links the
steps it creates back to them, so a changed spec can be diffed and the affected steps
found. The Qt half renders documents in a Specs tab; ``dplanner spec`` is the agent's way
in.
"""
