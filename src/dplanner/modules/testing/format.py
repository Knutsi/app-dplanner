"""The house shape of a test body, and the constant naming the door it is read through.

A project's topology says how its *graph* is shaped; this says how a *test* is written —
preconditions, then numbered steps — and it is delivered the same way and for the same
reasons (``cli/shaping.py``): **printed, never stored**, because a plan's own prose reaches
every agent briefing and a house document written into one is paid for again on every step
anybody ever executes; and **behind a gate**, because ``dplanner test format`` is then the
one door every test-writing agent goes through, whichever agent CLI it is driving. The
skill is Claude's alone; the gate is everybody's.

``ARCHITECTURE.md``'s *The test format is read before a test is written* has the reasoning.
"""

from pathlib import Path

# The verb that prints it: what `test add` and `test set` declare as their `reads_guide`,
# and what the composition root keys the gate by — one constant, so the two cannot drift.
FORMAT_VERB = "test format"

# How the refusal names what has not been read. A sentence starts with it.
FORMAT_SUBJECT = "how a test is written here"


def guide() -> str:
    return (Path(__file__).parent / "format.md").read_text(encoding="utf-8")
