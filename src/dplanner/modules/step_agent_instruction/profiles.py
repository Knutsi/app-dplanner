"""Launch profiles: which agent runs, and in which terminal or multiplexer — named, per user.

A profile is one answer to Run Agent's two questions — the agent command and the terminal
template — under a name a person picks: *Claude in Ghostty*, *Codex in herdr*. The first
profile is the **default**, what *Run Agent…* itself runs; the rest are the entries of
*Step ▸ Run Agent With*. Both texts keep the meaning they had as single settings: a blank
agent command is the first harness, a blank terminal template is *Automatic*.

Stored per user, per machine (``user_config``), never in the plan: which terminal a
person prefers is not the project's business. **The two settings they replace are read
as the default profile** when no list has been stored yet, so a machine configured before
profiles existed keeps its choices without anybody retyping them — the same idea as a
harness carrying the command texts it shipped earlier.
"""

from dataclasses import dataclass, replace
from typing import Any

from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID

PROFILES_KEY = "profiles"
# The two settings profiles replaced; read only when no profile list is stored.
AGENT_COMMAND_KEY = "agent_command"
LAUNCH_COMMAND_KEY = "launch_command"

DEFAULT_NAME = "Default"


@dataclass(frozen=True)
class Profile:
    name: str
    agent_command: str = ""  # "" means the first harness.
    launch_command: str = ""  # "" means Automatic — the first installed terminal.

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "agent": self.agent_command, "terminal": self.launch_command}

    @classmethod
    def from_json(cls, raw: Any) -> "Profile | None":
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            return None
        return cls(
            name=raw["name"],
            agent_command=str(raw.get("agent", "")),
            launch_command=str(raw.get("terminal", "")),
        )


def read_profiles() -> list[Profile]:
    """Every profile, the default first. Never empty: with nothing stored, the two
    single settings profiles replaced are the one profile."""
    stored = get_global(MODULE_ID, PROFILES_KEY)
    profiles = (
        [p for p in map(Profile.from_json, stored) if p is not None]
        if isinstance(stored, list)
        else []
    )
    if profiles:
        return profiles
    return [
        Profile(
            DEFAULT_NAME,
            agent_command=str(get_global(MODULE_ID, AGENT_COMMAND_KEY, "")),
            launch_command=str(get_global(MODULE_ID, LAUNCH_COMMAND_KEY, "")),
        )
    ]


def write_profiles(profiles: list[Profile]) -> None:
    set_global(MODULE_ID, PROFILES_KEY, [profile.to_json() for profile in profiles])


def default_profile() -> Profile:
    return read_profiles()[0]


def profile_named(name: str) -> Profile | None:
    return next((profile for profile in read_profiles() if profile.name == name), None)


def unique_name(base: str, taken: list[str]) -> str:
    """``base``, or ``base 2``, ``base 3``… — the first not in ``taken``."""
    name, count = base, 1
    while name in taken:
        count += 1
        name = f"{base} {count}"
    return name


def update_profile(index: int, **changes: str) -> None:
    """One field of one stored profile changed; the rest kept as they are."""
    profiles = read_profiles()
    if 0 <= index < len(profiles):
        profiles[index] = replace(profiles[index], **changes)
        write_profiles(profiles)
