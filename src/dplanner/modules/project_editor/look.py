"""How this user looks at graphs: the marks, the ground under them, and whether a gesture
snaps to its grid — one value, kept per user and pushed to every open canvas.

None of it is a fact about a project. Whether a graph's ends are lit, whether dots are
drawn under it and whether a drag lands on the grid say nothing about the plan, so the
value never reaches the project directory: the module keeps it in ``user_config`` and hands
it to every canvas it builds, and a tab opened later wears the same look. One value rather
than one per preference, because the plumbing — a key, a setter, a fan-out — is the same
for all of them, and the next preference is a field here instead of a third copy of it.

Qt-free, like ``marks.py``: tolerant JSON in, the same JSON out.
"""

from dataclasses import dataclass, field, replace

from dplanner.modules.project_editor.marks import Marks

# The backgrounds a canvas offers, in menu order: name → (the View menu's entry, its tip).
# ``ground.py`` paints each by name.
BACKGROUNDS: dict[str, tuple[str, str]] = {
    "none": ("&Plain", "Nothing under the graph"),
    "dots": ("&Dots", "A dot at every grid crossing under the graph"),
    "lines": ("&Lines", "Graph paper under the graph: a line on every grid pitch"),
    "crosses": ("&Crosses", "A small cross at every grid crossing under the graph"),
}
DEFAULT_BACKGROUND = "dots"


@dataclass(frozen=True)
class Look:
    """Which marks are on, what is drawn under the graph, and whether gestures snap."""

    marks: Marks = field(default_factory=Marks)
    background: str = DEFAULT_BACKGROUND
    snap: bool = True

    def with_mark(self, name: str, on: bool) -> "Look":
        return replace(self, marks=self.marks.with_(name, on))

    def with_background(self, name: str) -> "Look":
        if name not in BACKGROUNDS:
            raise KeyError(name)
        return replace(self, background=name)

    def with_snap(self, on: bool) -> "Look":
        return replace(self, snap=on)

    def to_json(self) -> dict[str, object]:
        return {"marks": self.marks.to_json(), "background": self.background, "snap": self.snap}

    @classmethod
    def from_json(cls, data: object) -> "Look":
        """Tolerant: anything that is not a mapping of the known keys reads as the default."""
        if not isinstance(data, dict):
            return cls()
        background = data.get("background", DEFAULT_BACKGROUND)
        return cls(
            marks=Marks.from_json(data.get("marks")),
            background=background if background in BACKGROUNDS else DEFAULT_BACKGROUND,
            snap=bool(data.get("snap", True)),
        )
