"""The per-user configuration directory, and the one variable that moves it whole."""

from dplanner.core.config_dir import OVERRIDE_ENV, config_dir


def test_the_override_names_the_directory_itself(monkeypatch, tmp_path):
    monkeypatch.setenv(OVERRIDE_ENV, str(tmp_path / "mine"))
    assert config_dir() == tmp_path / "mine"


def test_without_it_the_platform_rule_holds(monkeypatch, tmp_path):
    monkeypatch.delenv(OVERRIDE_ENV)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config_dir().name == "dplanner"
