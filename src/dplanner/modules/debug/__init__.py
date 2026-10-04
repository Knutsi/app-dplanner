"""Developer-facing surfaces, under the Debug menu.

The LLM Calls and Telemetry tabs, the Design Examples every UI change is compared against,
and *Debug ▸ Windows* — the Windows check and the RDP launcher for the developer's VM.

The module class and its ``Deps`` are imported from ``module.py`` by the composition root.
This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
