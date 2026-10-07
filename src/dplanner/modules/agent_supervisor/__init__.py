"""The run supervisor: the detached process that drives one headless run turn by turn.

``supervisor.py`` starts each turn, guards it, classifies how it ended and writes it into
the run's ledger record, then ends, parks or retries the run; ``cli.py`` is ``dplanner agent
supervise``. Headless all through, like ``agent_briefing``: there is no window half.
"""
