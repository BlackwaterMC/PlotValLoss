"""Tests for web_support: the local-only request guard, heartbeat routes, error handler."""

import pytest

import plot_val_loss
from web_support import create_app, api_success, api_error


@pytest.fixture
def client():
    plot_val_loss.app.config["TESTING"] = True
    with plot_val_loss.app.test_client() as c:
        yield c


def test_foreign_host_header_is_refused(client):
    res = client.get("/api/config", headers={"Host": "evil.example.com"})
    assert res.status_code == 403
    assert res.get_json()["status"] == "error"


def test_localhost_hosts_are_accepted(client):
    for host in ("127.0.0.1:5006", "localhost:5006", "localhost"):
        assert client.get("/api/scan_progress", headers={"Host": host}).status_code == 200


def test_cross_origin_post_is_refused_but_same_origin_and_no_origin_pass(client):
    host = "127.0.0.1:5006"
    bad = client.post("/api/scan_cancel", headers={"Host": host, "Origin": "http://evil.example.com"})
    assert bad.status_code == 403
    good = client.post("/api/scan_cancel", headers={"Host": host, "Origin": f"http://{host}"})
    assert good.status_code == 200
    assert client.post("/api/scan_cancel", headers={"Host": host}).status_code == 200


def test_heartbeat_and_client_leave_routes(client):
    res = client.post("/api/heartbeat", json={"client_id": "tab-1"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "alive"
    leave = client.post("/api/client_leave", json={"client_id": "tab-1"})
    assert leave.status_code == 200
    assert leave.get_json()["status"] == "ok"


def test_unexpected_route_error_becomes_json_500_outside_test_mode():
    app, _ = create_app("err_probe_app")

    @app.route("/boom")
    def boom():
        raise RuntimeError("kaboom")

    app.config["TESTING"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    res = app.test_client().get("/boom")
    assert res.status_code == 500
    assert res.get_json()["status"] == "error"
    assert "kaboom" in res.get_json()["message"]


def test_envelopes_are_plain_tuples_outside_an_app_context():
    assert api_success(data={"a": 1}) == ({"status": "success", "data": {"a": 1}}, 200)
    assert api_error("nope", code=404) == ({"status": "error", "message": "nope"}, 404)
