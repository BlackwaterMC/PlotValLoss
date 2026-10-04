"""Tests for loss_reader: the loss-log / job-date readers and AI-Toolkit folder lookup."""

import datetime
import os
import sqlite3

import pytest

import loss_reader
from conftest import init_mock_loss_db


def _mk_loss_db(db_path, rows):
    """rows: list of (step, key, value_real, wall_time). One steps row per unique step."""
    conn = init_mock_loss_db(db_path)
    cur = conn.cursor()
    seen_steps = set()
    for step, key, val, wt in rows:
        cur.execute("INSERT INTO metrics (step, key, value_real) VALUES (?, ?, ?)", (step, key, val))
        if step not in seen_steps:
            cur.execute("INSERT INTO steps (step, wall_time) VALUES (?, ?)", (step, wt))
            seen_steps.add(step)
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# load_series_from_db
# --------------------------------------------------------------------------- #

def test_load_series_orders_by_step_and_filters_metric(tmp_path):
    db = str(tmp_path / "run" / "loss_log.db")
    _mk_loss_db(db, [
        (30, "val/loss", 0.30, 1030.0),
        (10, "val/loss", 0.50, 1010.0),
        (20, "val/loss", 0.40, 1020.0),
        (10, "train/loss", 9.9, 1010.0),   # different key, must be ignored
        (40, "val/loss", None, 1040.0),    # null value_real, must be dropped
    ])
    steps, values, wall_times = loss_reader.load_series_from_db(db, metric_key="val/loss")
    assert steps == [10, 20, 30]
    assert values == [0.50, 0.40, 0.30]
    assert wall_times == [1010.0, 1020.0, 1030.0]


def test_load_series_empty_when_metric_absent(tmp_path):
    db = str(tmp_path / "run" / "loss_log.db")
    _mk_loss_db(db, [(10, "train/loss", 1.0, 1010.0)])
    assert loss_reader.load_series_from_db(db, metric_key="val/loss") == ([], [], [])


def test_load_series_missing_file_raises(tmp_path):
    missing = str(tmp_path / "nope" / "loss_log.db")
    # Opening a missing file read-only raises; the caller guards with os.path.exists.
    with pytest.raises(sqlite3.OperationalError):
        loss_reader.load_series_from_db(missing)


def test_load_series_empty_when_tables_not_created_yet(tmp_path):
    """A run can create loss_log.db before writing its metrics/steps tables."""
    db = str(tmp_path / "run" / "loss_log.db")
    os.makedirs(os.path.dirname(db))
    sqlite3.connect(db).close()          # file exists, no schema
    assert loss_reader.load_series_from_db(db, metric_key="val/loss") == ([], [], [])


# --------------------------------------------------------------------------- #
# get_job_dates_map
# --------------------------------------------------------------------------- #

def test_get_job_dates_map_reads_job_table(tmp_path):
    aitk_root = tmp_path / "AI-Toolkit"
    (aitk_root / "output").mkdir(parents=True)
    db = str(aitk_root / "aitk_db.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Job (name TEXT, created_at TEXT)")
    conn.execute("INSERT INTO Job (name, created_at) VALUES (?, ?)", ("pb__x__r00", "2026-08-29T18:04:11.123"))
    conn.execute("INSERT INTO Job (name, created_at) VALUES (?, ?)", ("", "2026-01-01T00:00:00"))  # skipped
    conn.commit()
    conn.close()

    m = loss_reader.get_job_dates_map(str(aitk_root / "output"))
    assert m.get("pb__x__r00") == "2026-08-29 18:04:11"
    assert "" not in m


def test_get_job_dates_map_missing_db_returns_empty(tmp_path):
    assert loss_reader.get_job_dates_map(
        str(tmp_path / "output"), fallback_db=str(tmp_path / "nonexistent.db")) == {}


def test_get_job_dates_map_uses_fallback_db(tmp_path):
    db = str(tmp_path / "elsewhere.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Job (name TEXT, created_at TEXT)")
    conn.execute("INSERT INTO Job (name, created_at) VALUES (?, ?)", ("job1", "2026-02-03 04:05:06"))
    conn.commit()
    conn.close()
    assert loss_reader.get_job_dates_map(str(tmp_path / "output"), fallback_db=db) == {"job1": "2026-02-03 04:05:06"}


# --------------------------------------------------------------------------- #
# get_run_date fallback chain
# --------------------------------------------------------------------------- #

def test_get_run_date_prefers_job_dates_then_falls_back(tmp_path):
    folder = tmp_path / "pb__x__r00"
    folder.mkdir()
    db = folder / "loss_log.db"
    db.write_bytes(b"x")

    assert loss_reader.get_run_date(str(folder), "pb__x__r00", str(db),
                                    {"pb__x__r00": "2026-08-29 18:04"}) == "2026-08-29 18:04"
    got = loss_reader.get_run_date(str(folder), "pb__x__r00", str(db), {})
    assert len(got) == 16 and got[4] == "-" and got[13] == ":"


def test_get_run_date_unknown_when_nothing_exists(tmp_path):
    assert loss_reader.get_run_date(str(tmp_path / "gone"), "gone", str(tmp_path / "gone" / "x.db"), {}) == "Unknown"


# --------------------------------------------------------------------------- #
# _coerce_job_timestamp
# --------------------------------------------------------------------------- #

def test_epoch_seconds():
    ts = datetime.datetime(2024, 1, 2, 3, 4, 0).timestamp()
    assert loss_reader._coerce_job_timestamp(ts) == "2024-01-02 03:04"


def test_epoch_milliseconds_detected_by_1e11_threshold():
    ms = datetime.datetime(2024, 1, 2, 3, 4, 0).timestamp() * 1000.0
    assert ms > 1e11
    assert loss_reader._coerce_job_timestamp(ms) == "2024-01-02 03:04"


def test_iso_string_is_split_on_dot_and_t():
    # Characterization: the string branch keeps seconds, the numeric branch does not.
    assert loss_reader._coerce_job_timestamp("2024-01-02T03:04:05.123456") == "2024-01-02 03:04:05"


def test_iso_string_without_fraction_or_t():
    assert loss_reader._coerce_job_timestamp("2024-01-02 03:04:05") == "2024-01-02 03:04:05"


def test_none_and_unsupported_types_return_none():
    assert loss_reader._coerce_job_timestamp(None) is None
    assert loss_reader._coerce_job_timestamp([]) is None
    assert loss_reader._coerce_job_timestamp({}) is None


def test_out_of_range_number_returns_none_not_raises():
    assert loss_reader._coerce_job_timestamp(10**18) is None


# --------------------------------------------------------------------------- #
# metrics_db_for
# --------------------------------------------------------------------------- #

def test_metrics_db_prefers_loss_log_db(tmp_path):
    run = tmp_path / "out" / "r1"
    run.mkdir(parents=True)
    (run / "a_other.db").write_bytes(b"x")
    (run / "loss_log.db").write_bytes(b"x")
    assert loss_reader.metrics_db_for(str(tmp_path / "out"), "r1") == str(run / "loss_log.db")


def test_metrics_db_falls_back_to_first_db_alphabetically(tmp_path):
    run = tmp_path / "out" / "r1"
    run.mkdir(parents=True)
    (run / "b.db").write_bytes(b"x")
    (run / "a.db").write_bytes(b"x")
    (run / "notes.txt").write_text("hi")
    assert loss_reader.metrics_db_for(str(tmp_path / "out"), "r1") == str(run / "a.db")


def test_metrics_db_none_when_no_db_or_no_folder(tmp_path):
    (tmp_path / "out" / "empty").mkdir(parents=True)
    assert loss_reader.metrics_db_for(str(tmp_path / "out"), "empty") is None
    assert loss_reader.metrics_db_for(str(tmp_path / "out"), "missing") is None


# --------------------------------------------------------------------------- #
# AI-Toolkit root resolution
# --------------------------------------------------------------------------- #

def test_resolve_root_prefers_env_var(monkeypatch, tmp_path):
    cfg = tmp_path / "plotvalloss_config.json"
    cfg.write_text('{"aitk_root": "C:/from/config"}', encoding="utf-8")
    monkeypatch.setattr(loss_reader, "config_path_for", lambda name: str(cfg))
    monkeypatch.setenv("AITK_ROOT", str(tmp_path / "envroot"))
    assert loss_reader.resolve_aitk_root() == os.path.normpath(str(tmp_path / "envroot"))


def test_resolve_root_falls_back_to_config_then_blank(monkeypatch, tmp_path):
    cfg = tmp_path / "plotvalloss_config.json"
    monkeypatch.setattr(loss_reader, "config_path_for", lambda name: str(cfg))
    monkeypatch.delenv("AITK_ROOT", raising=False)
    assert loss_reader.resolve_aitk_root() == ""          # nothing configured
    cfg.write_text('{"aitk_root": "C:/AI-Toolkit"}', encoding="utf-8")
    assert loss_reader.resolve_aitk_root() == os.path.normpath("C:/AI-Toolkit")


def test_default_output_dir_is_root_output():
    assert loss_reader.default_output_dir("C:/AI-Toolkit") == os.path.join("C:/AI-Toolkit", "output")
