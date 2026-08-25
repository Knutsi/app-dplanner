"""Pluggable export formats.

The registry follows ``TabHost.register_factory``: modules register :class:`ExportSpec`s
at startup, the export action offers whatever is registered — so a future format (EPUB, a
new PDF style) is one ``register`` call in its own module, nothing else.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExportSpec:
    id: str  # "pdf_book" — module prefix not needed; format ids are global.
    label: str  # "PDF — Book"
    file_filter: str  # The save dialog's filter row: "PDF — Book (*.pdf)".
    suffix: str  # ".pdf" — enforced on the chosen path.
    # Takes only a destination: the spec closes over whatever data it needs when the
    # module registers it, so this registry never has to name your model.
    run: Callable[[Path], None]


class ExportRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ExportSpec] = {}

    def register(self, spec: ExportSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"export format {spec.id!r} already registered")
        self._specs[spec.id] = spec

    def specs(self) -> list[ExportSpec]:
        """All formats, in registration order (the first is the dialog's default)."""
        return list(self._specs.values())
