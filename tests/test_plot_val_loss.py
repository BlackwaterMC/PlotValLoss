import os
import json
import sqlite3
import pytest
from unittest.mock import patch

import plot_val_loss


@pytest.fixture
def plotvalloss_client(tmp_path):
    """Fixture providing Flask test client and temporary config / output dir."""
    config_file = str(tmp_path / "plotvalloss_config.json")
    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)

    with patch.object(plot_val_loss, "CONFIG_FILE", config_file), \
         patch.object(plot_val_loss, "DEFAULT_OUTPUT_DIR", output_dir):
        plot_val_loss.app.config["TESTING"] = True
        with plot_val_loss.app.test_client() as client:
            yield client, config_file, output_dir


def create_mock_loss_db(db_path: str, rows: list[tuple]):
    """Helper to create a loss_log.db file with metrics table."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE metrics (
            step INTEGER,
            key TEXT,
            value_real REAL
        )
    """)
    cur.execute("""
        CREATE TABLE steps (
            step INTEGER,
            wall_time REAL
        )
    """)
    for step, key, val, wall_time in rows:
        cur.execute("INSERT INTO metrics (step, key, value_real) VALUES (?, ?, ?)", (step, key, val))
        cur.execute("INSERT INTO steps (step, wall_time) VALUES (?, ?)", (step, wall_time))
    conn.commit()
    conn.close()


# --- Tests: Config Persistence & Endpoints ---

def test_api_config_get_and_post(plotvalloss_client):
    client, config_file, _ = plotvalloss_client

    # GET when config file does not exist returns empty dict
    res = client.get("/api/config")
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data["status"] == "success"
    assert json_data["data"] == {}

    # POST to update config
    post_res = client.post("/api/config", json={"filter1": "Krea2", "filter2": "Dana"})
    assert post_res.status_code == 200
    assert post_res.get_json()["data"] == {"filter1": "Krea2", "filter2": "Dana"}

    # Verify config was written to file
    assert os.path.exists(config_file)
    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == {"filter1": "Krea2", "filter2": "Dana"}

    # Subsequent GET returns saved config
    get_res2 = client.get("/api/config")
    assert get_res2.get_json()["data"] == {"filter1": "Krea2", "filter2": "Dana"}


def test_api_config_post_keeps_other_keys_and_ignores_unlisted_ones(plotvalloss_client):
    client, config_file, _ = plotvalloss_client
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump({"aitk_root": "C:/AI-Toolkit"}, f)

    res = client.post("/api/config", json={"filter1": "x", "aitk_root": "C:/hijack", "other": 1})
    assert res.get_json()["data"] == {"aitk_root": "C:/AI-Toolkit", "filter1": "x"}


def test_api_data_scans_all_runs_without_hardcoded_filters(plotvalloss_client):
    client, _, output_dir = plotvalloss_client

    # Create mock run folders
    run1_dir = os.path.join(output_dir, "Krea2_Dana_run1")
    run2_dir = os.path.join(output_dir, "SDXL_Anime_run1")
    run3_high_loss = os.path.join(output_dir, "Krea2_Test_high")

    create_mock_loss_db(
        os.path.join(run1_dir, "loss_log.db"),
        [(1, "val/loss", 0.35, 1000.0), (2, "val/loss", 0.28, 1060.0)]
    )
    create_mock_loss_db(
        os.path.join(run2_dir, "loss_log.db"),
        [(1, "val/loss", 0.42, 2000.0), (2, "val/loss", 0.38, 2060.0)]
    )
    create_mock_loss_db(
        os.path.join(run3_high_loss, "loss_log.db"),
        [(1, "val/loss", 1.50, 3000.0), (2, "val/loss", 1.20, 3060.0)]
    )

    # API data call should return ALL runs
    res = client.get("/api/data?refresh=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    runs = data["data"]["runs"]

    run_names = [r["name"] for r in runs]
    assert "Krea2_Dana_run1" in run_names
    assert "SDXL_Anime_run1" in run_names
    assert "Krea2_Test_high" in run_names

    # Check high loss visibility rule
    high_run = next(r for r in runs if r["name"] == "Krea2_Test_high")
    assert high_run["default_visible"] is False
    assert high_run["max_value"] == 1.50

    low_run = next(r for r in runs if r["name"] == "Krea2_Dana_run1")
    assert low_run["default_visible"] is True
    assert low_run["max_value"] == 0.35


def test_api_data_async_and_progress(plotvalloss_client):
    client, _, output_dir = plotvalloss_client
    # Initiate async scan
    res = client.post("/api/data?async=1&refresh=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data.get("started") is True or data.get("data", {}).get("started") is True

    # Check progress endpoint
    prog = client.get("/api/scan_progress")
    assert prog.status_code == 200
    pdata = prog.get_json()
    assert "percent" in pdata
    assert "status" in pdata
