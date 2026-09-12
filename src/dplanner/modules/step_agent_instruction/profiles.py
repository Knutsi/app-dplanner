"""Launch profiles: which agent runs, and in which terminal or multiplexer — named, per user.

A profile is one answer to Run Agent's two questions — the agent command and the terminal
template — under a name a person picks: *Claude in Ghostty*, *Codex in herdr*. The first
profile is the **default**, what *Run Agent…* itself runs; all of them are the entries of
*Step ▸ Run Agent*. Both texts keep the meaning they had as single settings: a blank
agent command is the first harness, a blank terminal template is *Automatic*.

Stored per user, per machine (``user_config``), never in the plan: which terminal a
person prefers is not the project's business. **The two settings they replace are read
as the default profile** when no list has been stored yet, so a machine configured before
profiles existed keeps its choices without anybody retyping them — the same idea as a
harness carrying the command texts it shipped earlier.

**The list is seeded once, and the seed is every known pairing.** A person should not
have to build *Codex in herdr* by hand to find out it exists: :func:`seed_profiles` adds
one profile per harness and per terminal worth naming — Ghostty, herdr and the platform's
own default (*Automatic*) — skipping any pairing a stored profile already means, by its
choices rather than its name, so a hand-named *Claude in Ghostty* is never doubled. It
runs when the window is built and records that it has (``profiles_seeded``), so a
profile the person removes afterwards stays removed; whatever was the default before
stays the default.

**A name follows the choices until somebody types one.** :func:`suggested_name` words a
profile by its agent and terminal — *Claude Code in herdr* — and :func:`update_profile`
renames a profile whose name still reads as what its old choices suggested; a name that
reads as anything else is a person's and is kept. Names are unique among the profiles
either way, numbered rather than refused.
"""

import re
import sys
from dataclasses import dataclass, replace
from typing import Any

from dplanner.domain.agents import AgentHarness
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
from dplanner.modules.step_agent_instruction.launcher import (
    current_command,
    harness_of,
    terminals_for,
)

PROFILES_KEY = "profiles"
# Whether the known pairings have been added once — a person's later removals stand.
SEEDED_KEY = "profiles_seeded"
# The terminal rows the seed pairs every harness with, by label; "" is Automatic.
SEEDED_TERMINALS = ("Ghostty", "herdr", "")
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


def _first_word(command: str) -> str:
    words = command.split()
    return words[0] if words else ""


def suggested_name(
    profile: Profile, harnesses: tuple[AgentHarness, ...], platform: str = sys.platform
) -> str:
    """The name a profile's two choices suggest: *Claude Code in herdr*, or the agent's
    name alone when the terminal is Automatic. A command or template nothing here knows
    is named by its first word, which is usually the program."""
    harness = harness_of(profile.agent_command, harnesses)
    agent = harness.label if harness else _first_word(profile.agent_command) or "Agent"
    template = profile.launch_command.strip()
    if not template:
        return agent
    row = next((r for r in terminals_for(platform) if r.command == template), None)
    terminal = row.label.split(" (")[0] if row else _first_word(template)
    return f"{agent} in {terminal}" if terminal else agent


def follows_choices(
    profile: Profile, harnesses: tuple[AgentHarness, ...], platform: str = sys.platform
) -> bool:
    """Whether the name is the one its choices suggest, or that name numbered — a name
    nobody typed, free to follow the next change. Anything else is a person's word."""
    base = re.escape(suggested_name(profile, harnesses, platform))
    return re.fullmatch(rf"{base}( \d+)?", profile.name) is not None


def _choices(profile: Profile, harnesses: tuple[AgentHarness, ...]) -> tuple[str, str]:
    """What a profile means, for telling two apart: the harness command a text resolves
    to and the terminal template as typed."""
    return current_command(profile.agent_command, harnesses), profile.launch_command.strip()


def seed_profiles(
    harnesses: tuple[AgentHarness, ...], platform: str = sys.platform
) -> list[Profile]:
    """Once per user and machine: every harness in every terminal of
    :data:`SEEDED_TERMINALS`, appended after the profiles already stored.

    A pairing a stored profile already means is skipped, so the seed never doubles a
    profile a person named themselves; the stored default stays first. The flag is
    written with the list, so a seeded profile the person removes stays removed. With
    no harnesses there is nothing to seed and nothing is recorded. Returns what was
    added.
    """
    if not harnesses or get_global(MODULE_ID, SEEDED_KEY):
        return []
    rows = terminals_for(platform)
    templates = [
        next((row.command for row in rows if row.label == label), "") for label in SEEDED_TERMINALS
    ]
    profiles = read_profiles()
    if get_global(MODULE_ID, PROFILES_KEY) is None and profiles[0].name == DEFAULT_NAME:
        # The two old settings read as a profile nobody named: name it by its choices
        # now that it is written among named ones, rather than leave a *Default* row.
        profiles[0] = replace(profiles[0], name=suggested_name(profiles[0], harnesses, platform))
    known = {_choices(profile, harnesses) for profile in profiles}
    added: list[Profile] = []
    for harness in harnesses:
        for template in templates:
            candidate = Profile("", harness.command, template)
            if _choices(candidate, harnesses) in known:
                continue
            known.add(_choices(candidate, harnesses))
            name = suggested_name(candidate, harnesses, platform)
            names = [profile.name for profile in profiles + added]
            added.append(replace(candidate, name=unique_name(name, names)))
    write_profiles(profiles + added)
    set_global(MODULE_ID, SEEDED_KEY, True)
    return added


def update_profile(
    index: int,
    *,
    harnesses: tuple[AgentHarness, ...] = (),
    platform: str = sys.platform,
    **changes: str,
) -> None:
    """Fields of one stored profile changed; the rest kept as they are.

    A name that was never typed follows the choices: when the agent or the terminal
    changes and the name still reads as what the old choices suggested, it becomes what
    the new ones suggest. A name a person typed stays theirs. Either way the name ends up
    unique among the profiles — a typed duplicate is numbered rather than refused, since
    *Run Agent* and the default lookup both go by name.
    """
    profiles = read_profiles()
    if not 0 <= index < len(profiles):
        return
    before = profiles[index]
    after = replace(before, **changes)
    if "name" not in changes and after != before and follows_choices(before, harnesses, platform):
        after = replace(after, name=suggested_name(after, harnesses, platform))
    others = [p.name for i, p in enumerate(profiles) if i != index]
    profiles[index] = replace(after, name=unique_name(after.name, others))
    write_profiles(profiles)
