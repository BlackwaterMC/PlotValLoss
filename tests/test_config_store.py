"""Tests for config_store: atomic JSON settings save/load with a .bak safety copy."""

import json
import os

import config_store


def test_missing_file_loads_empty(tmp_path):
    assert config_store.load_config(str(tmp_path / "none.json")) == {}


def test_round_trip(tmp_path):
    path = str(tmp_path / "c.json")
    config_store.save_config(path, {"filter1": "a", "n": 3})
    assert config_store.load_config(path) == {"filter1": "a", "n": 3}


def test_second_save_keeps_previous_as_bak(tmp_path):
    path = str(tmp_path / "c.json")
    config_store.save_config(path, {"v": 1})
    config_store.save_config(path, {"v": 2})
    with open(path + ".bak", encoding="utf-8") as f:
        assert json.load(f) == {"v": 1}
    assert config_store.load_config(path) == {"v": 2}


def test_corrupt_file_falls_back_to_backup(tmp_path):
    path = str(tmp_path / "c.json")
    config_store.save_config(path, {"v": 1})
    config_store.save_config(path, {"v": 2})
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert config_store.load_config(path) == {"v": 1}


def test_corrupt_file_without_backup_is_empty_and_set_aside_on_save(tmp_path):
    path = str(tmp_path / "c.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert config_store.load_config(path) == {}
    config_store.save_config(path, {"v": 9})
    assert os.path.exists(path + ".corrupt")
    assert config_store.load_config(path) == {"v": 9}


def test_unserializable_value_leaves_old_file_untouched(tmp_path):
    path = str(tmp_path / "c.json")
    config_store.save_config(path, {"v": 1})
    config_store.save_config(path, {"v": object()})      # cannot be JSON; error is logged, not raised
    assert config_store.load_config(path) == {"v": 1}


def test_natural_sort_key_orders_numbers_numerically():
    names = ["run10", "run2", "Run1"]
    assert sorted(names, key=config_store.natural_sort_key) == ["Run1", "run2", "run10"]
