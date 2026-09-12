"""The theme providers: the contract, the Omarchy mapping and its generator, and each
provider over a desktop of its own."""

import os
from pathlib import Path

import pytest
from scripts.import_omarchy_themes import OUT, collect, omarchy_version, render

from dplanner.modules.theme_omarchy.themes import OWN_THEMES, omarchy_provider
from dplanner.modules.theme_system.themes import DESKTOPS, system_provider, with_accent
from dplanner.theme.omarchy import is_light, read_colors, theme_from_colors
from dplanner.theme.providers import (
    BUILTIN,
    OMARCHY_THEMES,
    ThemeGroup,
    ThemeProvider,
    provider_by_id,
)
from dplanner.theme.themes import DARK, LIGHT, SEPIA

TOKYO_NIGHT = """\
mode = "dark"

accent = "#7aa2f7"
selection = "#292e42"
muted = "#414868"

background = "#1a1b26"
lighter_background = "#24283b"

foreground = "#a9b1d6"
bright_foreground = "#c0caf5"

red = "#f7768e"
blue = "#7aa2f7"
magenta = "#ad8ee6"
"""

LATTE = """\
mode = "light"
accent = "#1e66f5"
selection = "#ccd0da"
background = "#eff1f5"
foreground = "#4c4f69"
bright_foreground = "#4c4f69"
blue = "#1e66f5"
magenta = "#ea76cb"
"""


def colors(text: str) -> dict[str, str]:
    import tomllib

    return {key: value.lower() for key, value in tomllib.loads(text).items()}


# -- the contract ------------------------------------------------------------------------------


def test_capabilities_are_derived_from_the_record_never_declared():
    bare = ThemeProvider("x", "X")
    assert not bare.follows and bare.themes() == () and bare.capabilities() == ()
    following = ThemeProvider("y", "Y", current=lambda: DARK)
    assert following.follows and following.capabilities() == ("follows the desktop",)
    assert following.desktop() is DARK and bare.desktop() is None
    listing = ThemeProvider("z", "Z", groups=lambda: (ThemeGroup(None, (DARK, LIGHT)),))
    assert listing.capabilities() == ("2 themes",)
    assert listing.theme("light") is LIGHT and listing.theme("sepia") is None
    assert provider_by_id((bare, following), "y") is following
    assert provider_by_id((bare, following), "w") is None


def test_the_builtin_provider_offers_the_house_themes_flat_and_omarchys_under_a_title():
    groups = BUILTIN.groups()
    assert [group.title for group in groups] == [None, "Omarchy"]
    assert groups[0].themes == (DARK, LIGHT, SEPIA)
    assert BUILTIN.refusal() is None and not BUILTIN.follows
    assert BUILTIN.capabilities() == (f"{3 + len(OMARCHY_THEMES)} themes",)


def test_every_omarchy_default_is_generated_in():
    names = [theme.name for theme in OMARCHY_THEMES]
    assert names == sorted(names) and len(names) == 22
    assert {"tokyo-night", "catppuccin-latte", "solitude", "lupine", "last-horizon"} <= set(names)
    assert not next(theme for theme in OMARCHY_THEMES if theme.name == "lupine").is_dark


# -- the mapping -------------------------------------------------------------------------------


def test_the_mapping_takes_the_anchors_and_derives_the_ramp():
    theme = theme_from_colors("tokyo-night", colors(TOKYO_NIGHT))
    assert theme.is_dark
    assert (theme.bg_base, theme.text_primary, theme.accent) == ("#1a1b26", "#a9b1d6", "#7aa2f7")
    # Omarchy's own selection pair: its wash, and the bright foreground its terminals show.
    assert (theme.selection_bg, theme.selection_fg) == ("#292e42", "#c0caf5")
    assert (theme.link, theme.link_visited) == ("#7aa2f7", "#ad8ee6")
    # The ramp is derived, never the file's own shades.
    assert theme.bg_surface != theme.bg_base and theme.bg_elevated != "#24283b"
    assert theme.on_accent == theme.bg_base


def test_a_light_theme_reads_its_mode():
    theme = theme_from_colors("catppuccin-latte", colors(LATTE))
    assert not theme.is_dark and theme.on_accent == "#ffffff"
    assert theme.selection_bg == "#ccd0da"


def test_mode_falls_back_the_way_omarchy_does():
    """Every stock theme says ``mode``; a person's older theme may say ``theme_type`` or
    nothing, and then the background's brightness decides — ``r + g + b > 382`` is light."""
    assert is_light({"theme_type": "light", "background": "#000000"})
    assert is_light({"background": "#808080"})  # 384
    assert not is_light({"background": "#7f7f7f"})  # 381
    assert not is_light({})


def test_a_fallback_stands_in_for_each_missing_colour():
    theme = theme_from_colors("bare", {"background": "#101010", "foreground": "#e0e0e0"})
    assert theme.accent == "#e0e0e0" and theme.link == theme.accent
    assert theme.link_visited == theme.link and theme.selection_fg == "#e0e0e0"
    muted = theme_from_colors(
        "muted",
        {"background": "#101010", "foreground": "#e0e0e0", "muted": "#404040", "blue": "#3030ff"},
    )
    assert muted.selection_bg == "#404040" and muted.accent == "#3030ff"


def test_a_value_in_another_form_counts_as_absent():
    """Hyprland's ``rgba(…)`` strings ride along in a few files; an accent in that form
    falls through to blue rather than reaching the stylesheet."""
    theme = theme_from_colors(
        "odd",
        {
            "background": "#101010",
            "foreground": "#e0e0e0",
            "accent": "rgba(798186ee)",
            "blue": "#3030ff",
        },
    )
    assert theme.accent == "#3030ff"


def test_a_file_without_a_background_is_not_a_theme():
    with pytest.raises(ValueError, match="no background"):
        theme_from_colors("half", {"foreground": "#e0e0e0"})


def test_read_colors_lower_cases_and_keeps_only_strings(tmp_path):
    path = tmp_path / "colors.toml"
    path.write_text('mode = "Dark"\nforeground = "#FAFCFB"\nsize = 3\n', encoding="utf-8")
    assert read_colors(path) == {"mode": "dark", "foreground": "#fafcfb"}


def test_read_colors_answers_none_for_a_missing_or_broken_file(tmp_path):
    assert read_colors(tmp_path / "colors.toml") is None
    (tmp_path / "colors.toml").write_text("mode = \n", encoding="utf-8")
    assert read_colors(tmp_path / "colors.toml") is None


# -- the generator -----------------------------------------------------------------------------


def stage(root: Path, name: str, text: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "colors.toml").write_text(text, encoding="utf-8")
    return directory


def test_the_generator_renders_what_it_collects_and_the_result_imports(tmp_path):
    stage(tmp_path, "tokyo-night", TOKYO_NIGHT + 'hyprland_active_border = "rgba(7aa2f7ee)"\n')
    stage(tmp_path, "catppuccin-latte", LATTE)
    (tmp_path / "empty").mkdir()
    stage(tmp_path, "broken", "mode = \n")
    (tmp_path / "stray.txt").write_text("", encoding="utf-8")

    themes = collect(tmp_path)
    assert list(themes) == ["catppuccin-latte", "tokyo-night"]
    assert "hyprland_active_border" not in themes["tokyo-night"]
    assert list(themes["tokyo-night"])[:3] == ["accent", "background", "blue"]

    namespace: dict[str, object] = {}
    exec(render(themes, "4.0.0"), namespace)
    assert namespace["OMARCHY_COLORS"] == themes
    assert "Generated from Omarchy 4.0.0" in str(namespace["__doc__"])


def test_the_committed_table_is_what_the_generator_writes():
    """Regenerating over this machine's Omarchy reproduces the file byte for byte, so a
    hand edit or an upstream change cannot go unnoticed where Omarchy is installed."""
    themes_dir = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "themes"
    if not themes_dir.is_dir():
        pytest.skip("no Omarchy installation to compare with")
    expected = render(collect(themes_dir), omarchy_version(themes_dir))
    assert OUT.read_text(encoding="utf-8") == expected


# -- the Omarchy provider ----------------------------------------------------------------------


@pytest.fixture
def desktop(tmp_path):
    """An Omarchy state directory showing tokyo-night, and a themes directory of one's own."""
    state = tmp_path / "state" / "omarchy" / "current"
    stage(state, "theme", TOKYO_NIGHT)
    (state / "theme.name").write_text("tokyo-night\n", encoding="utf-8")
    own = tmp_path / "config" / "omarchy" / "themes"
    own.mkdir(parents=True)
    return state, own


def test_omarchy_refuses_a_machine_without_its_state(tmp_path):
    provider = omarchy_provider(tmp_path / "nowhere", tmp_path / "themes")
    reason = provider.refusal()
    assert reason is not None and "Omarchy 4" in reason and "colors.toml" in reason


def test_omarchy_reads_the_staged_theme_by_its_name(desktop):
    state, own = desktop
    provider = omarchy_provider(state, own)
    assert provider.refusal() is None and provider.follows
    theme = provider.desktop()
    assert theme is not None and theme.name == "tokyo-night" and theme.bg_base == "#1a1b26"


def test_omarchy_lists_the_persons_own_themes_and_skips_what_is_not_one(desktop):
    state, own = desktop
    stage(own, "aether", LATTE)
    (own / "half-made").mkdir()
    stage(own, "older", "background = \n")
    provider = omarchy_provider(state, own)
    (group,) = provider.groups()
    assert group.title == OWN_THEMES
    assert [theme.name for theme in group.themes] == ["aether"]
    assert provider.capabilities() == ("follows the desktop", "1 theme")


def test_omarchy_lists_nothing_when_there_is_nothing_of_ones_own(desktop):
    state, own = desktop
    assert omarchy_provider(state, own).groups() == ()
    assert omarchy_provider(state, own / "missing").groups() == ()


def test_omarchy_answers_nothing_while_the_theme_is_being_replaced(desktop):
    """``omarchy-theme-set`` removes the theme directory, moves the next one in, then
    writes ``theme.name``; a read in between says nothing rather than something wrong."""
    state, own = desktop
    provider = omarchy_provider(state, own)
    (state / "theme" / "colors.toml").unlink()
    assert provider.desktop() is None
    (state / "theme" / "colors.toml").write_text(LATTE, encoding="utf-8")
    (state / "theme.name").write_text("", encoding="utf-8")
    theme = provider.desktop()
    assert theme is not None and theme.name == "omarchy" and not theme.is_dark


# -- the desktop's own -------------------------------------------------------------------------


def desktop_provider(platform: str, at_start: str = "dark", now: str = "dark") -> ThemeProvider:
    return system_provider(
        platform, scheme_at_start=lambda: at_start, scheme=lambda: now, accent=lambda: None
    )


def test_the_desktop_provider_refuses_where_it_cannot_read_a_scheme():
    assert desktop_provider("plan9").refusal() == "Not supported on plan9"
    unknown = desktop_provider("linux", at_start="unknown")
    assert unknown.refusal() == "This desktop does not report a colour scheme"
    for platform, label in DESKTOPS.items():
        provider = desktop_provider(platform)
        assert provider.refusal() is None and provider.label == label
        assert provider.follows and provider.groups() == ()


def test_the_desktop_provider_follows_the_scheme_it_is_handed():
    scheme = ["dark"]
    provider = system_provider(
        "darwin", scheme_at_start=lambda: "dark", scheme=lambda: scheme[0], accent=lambda: None
    )
    assert provider.desktop() == DARK
    scheme[0] = "light"
    assert provider.desktop() == LIGHT


def test_the_desktop_provider_wears_the_desktops_accent():
    provider = system_provider(
        "win32", scheme_at_start=lambda: "dark", scheme=lambda: "dark", accent=lambda: "#0078d4"
    )
    theme = provider.desktop()
    assert theme is not None and theme.accent == "#0078d4" and theme.on_accent == "#ffffff"
    assert theme.accent_hover != theme.accent and theme.bg_base == DARK.bg_base
    pale = with_accent(LIGHT, "#f0c674")
    assert pale.on_accent == LIGHT.on_accent
