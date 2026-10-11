"""The run supervisor: the detached process that drives one headless run turn by turn.

``supervisor.py`` starts each turn, guards it, classifies how it ended and writes it into
the run's ledger record, then ends, parks or retries the run. It is also the run-control
every other module goes through: the step's launch lock (``launching``), starting a run
detached, advancing or waking a pass, stopping one, and ``revive`` — restarting the runs
whose supervisor died. ``limits.py`` is what each agent account last said about its usage,
and whether a launch waits for it; ``cli.py`` is ``dplanner agent supervise`` and ``agent
limits``. Headless all through, like ``agent_briefing``: there is no window half.
"""
