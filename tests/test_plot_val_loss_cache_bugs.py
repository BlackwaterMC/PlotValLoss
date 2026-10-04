"""Bug-hunt tests for plot_val_loss: the /api/data cache and scan boundaries."""
import os

import pytest

import plot_val_loss
from test_plot_val_loss import plotvalloss_client, create_mock_loss_db  # noqa: F401


@pytest.fixture(autouse=True)
def _fresh_cache():
    plot_val_loss.CACHED_DATA = {"runs": [], "output_dir": "", "filters": [], "metric": ""}
    yield
    plot_val_loss.CACHED_DATA = {"runs": [], "output_dir": "", "filters": [], "metric": ""}


def _two_runs(output_dir):
    create_mock_loss_db(os.path.join(output_dir, "alpha", "loss_log.db"),
                        [(1, "val/loss", 0.3, 10.0), (1, "train/loss", 0.9, 10.0)])
    create_mock_loss_db(os.path.join(output_dir, "beta", "loss_log.db"),
                        [(1, "val/loss", 0.4, 20.0), (1, "train/loss", 0.8, 20.0)])


def test_changing_metric_is_not_served_from_stale_cache(plotvalloss_client):
    client, _, output_dir = plotvalloss_client
    _two_runs(output_dir)
    first = client.get("/api/data?metric=val/loss").get_json()["data"]["runs"]
    second = client.get("/api/data?metric=train/loss").get_json()["data"]["runs"]
    assert {r["max_value"] for r in first} == {0.3, 0.4}
    assert {r["max_value"] for r in second} == {0.9, 0.8}


def test_changing_filters_is_not_served_from_stale_cache(plotvalloss_client):
    client, _, output_dir = plotvalloss_client
    _two_runs(output_dir)
    client.get("/api/data")
    runs = client.get("/api/data?filter=beta").get_json()["data"]["runs"]
    assert [r["name"] for r in runs] == ["beta"]


def test_blank_output_dir_falls_back_to_default(plotvalloss_client):
    client, _, output_dir = plotvalloss_client
    _two_runs(output_dir)
    runs = client.get("/api/data?output_dir=&refresh=1").get_json()["data"]["runs"]
    assert len(runs) == 2


def test_nan_value_does_not_make_visibility_order_dependent(plotvalloss_client):
    client, _, output_dir = plotvalloss_client
    nan = float("nan")
    create_mock_loss_db(os.path.join(output_dir, "a", "loss_log.db"),
                        [(1, "val/loss", 0.5, 1.0), (2, "val/loss", nan, 2.0)])
    create_mock_loss_db(os.path.join(output_dir, "b", "loss_log.db"),
                        [(1, "val/loss", nan, 1.0), (2, "val/loss", 0.5, 2.0)])
    runs = {r["name"]: r for r in
            client.get("/api/data?refresh=1").get_json()["data"]["runs"]}
    if runs:  # loader may legitimately drop NaN rows; either way both runs must agree
        assert runs["a"]["default_visible"] == runs["b"]["default_visible"]
        assert runs["a"]["max_value"] == runs["b"]["max_value"]
