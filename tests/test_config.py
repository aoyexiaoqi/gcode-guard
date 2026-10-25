"""Config loading: defaults, JSON files, unknown-key rejection."""

import json

import pytest

from gcode_guard import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.x_max is None and cfg.z_min is None
    assert cfg.safe_z == 5.0
    assert cfg.arc_tolerance == 0.05


def test_config_from_dict_coerces_numbers():
    cfg = Config.from_dict({"x_max": 100, "safe_z": "2.5"})
    assert cfg.x_max == 100.0
    assert cfg.safe_z == 2.5


def test_config_from_json_file(tmp_path):
    path = tmp_path / "limits.json"
    path.write_text(json.dumps({"x_min": -100, "x_max": 100, "z_max": 50}))
    cfg = Config.from_json(path)
    assert cfg.x_min == -100.0
    assert cfg.x_max == 100.0
    assert cfg.z_max == 50.0
    assert cfg.y_max is None


def test_config_unknown_key_rejected():
    with pytest.raises(ValueError):
        Config.from_dict({"x_mx": 100})
