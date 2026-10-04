"""The planning model: what a step's status is, how it is read, and what is ready.

``domain/`` is the graph — nodes, edges and aspect entries it treats as opaque. This tier
sits on top of it and *interprets* the few aspects every planning question needs: the
status vocabulary and its stored format (:mod:`.status`), the estimate (:mod:`.estimate`),
the readiness walk (:mod:`.progression`), the schedule over estimates (:mod:`.schedule`)
and what a collector gathers (:mod:`.scope`). It imports
``core`` and ``domain`` only, never Qt and never a module, and ``domain/`` never imports it —
``tests/test_architecture.py`` holds both. ARCHITECTURE.md's *Planning owns status* has the
reasoning.

Import from the defining module — this package deliberately re-exports nothing.
"""
