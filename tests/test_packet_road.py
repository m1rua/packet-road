import subprocess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packet_road import api, core


def test_invalid_target():
    with pytest.raises(core.PolicyError):
        core.normalize_target("example.com; touch /tmp/injected")


def test_mixed_dns_rebinding_blocked():
    with patch.object(core, "resolve", return_value=["93.184.216.34", "127.0.0.1"]):
        with patch.object(core, "connect") as connect:
            with pytest.raises(core.PolicyError):
                core.diagnose("example.com")
            connect.assert_not_called()


def test_partial_result():
    with patch.object(core, "resolve", return_value=["93.184.216.34"]), \
         patch.object(core, "route", side_effect=FileNotFoundError("ip")), \
         patch.object(core, "trace", return_value={"hops": []}), \
         patch.object(core, "tcp", return_value={"connected": True}), \
         patch.object(core, "tls_probe", return_value={"version": "TLSv1.3"}), \
         patch.object(core, "http_probe", side_effect=TimeoutError("HTTP")):
        result = core.diagnose("example.com")
    assert result["stages"]["route"]["status"] == "error"
    assert result["stages"]["tcp"]["status"] == "ok"
    assert result["stages"]["tls"]["data"]["version"] == "TLSv1.3"
    assert result["stages"]["http"]["status"] == "error"


def test_command_timeout_and_no_shell():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ip", 3)) as run:
        with pytest.raises(subprocess.TimeoutExpired):
            core.command(["ip", "-j", "route"])
        assert run.call_args.kwargs["timeout"] == 3
        assert not run.call_args.kwargs.get("shell", False)


def test_trace_parser():
    with patch.object(core, "command", return_value=
                      "traceroute to test\n 1  10.0.0.1  1.23 ms\n 2  *\n"):
        result = core.trace("93.184.216.34", 2)
    assert result["hops"][0]["rtt_ms"] == 1.23
    assert result["hops"][1]["address"] is None
    assert not result["reached"]


def test_api_access_and_allowlist(monkeypatch):
    monkeypatch.setenv("PACKET_ROAD_TOKEN", "x" * 32)
    monkeypatch.setenv("PACKET_ROAD_TARGETS", "example.com")
    with TestClient(api.app) as client:
        assert client.post("/v1/diagnostics", json={"target": "example.com"}).status_code == 401
        headers = {"Authorization": "Bearer " + "x" * 32}
        assert client.post("/v1/diagnostics", headers=headers,
                           json={"target": "other.com"}).status_code == 403
        with patch.object(api, "diagnose", return_value={"stages": {}}):
            assert client.post("/v1/diagnostics", headers=headers,
                               json={"target": "example.com"}).status_code == 200


def test_api_concurrency_limit(monkeypatch):
    monkeypatch.setenv("PACKET_ROAD_TOKEN", "x" * 32)
    monkeypatch.setenv("PACKET_ROAD_TARGETS", "example.com")
    api.ACTIVE.acquire()
    api.ACTIVE.acquire()
    try:
        with TestClient(api.app) as client:
            assert client.post("/v1/diagnostics", json={"target": "example.com"},
                               headers={"Authorization": "Bearer " + "x" * 32}
                               ).status_code == 429
    finally:
        api.ACTIVE.release()
        api.ACTIVE.release()


def test_api_rate_limit(monkeypatch):
    monkeypatch.setenv("PACKET_ROAD_TOKEN", "x" * 32)
    monkeypatch.setenv("PACKET_ROAD_TARGETS", "example.com")
    import time
    api.STARTS.clear()
    api.STARTS.extend([time.monotonic()] * 10)
    try:
        with TestClient(api.app) as client:
            assert client.post("/v1/diagnostics", json={"target": "example.com"},
                               headers={"Authorization": "Bearer " + "x" * 32}
                               ).status_code == 429
    finally:
        api.STARTS.clear()


def test_dns_failure_stops_connections():
    with patch.object(core, "resolve", side_effect=TimeoutError("DNS")), \
         patch.object(core, "connect") as connect:
        result = core.diagnose("example.com")
        assert list(result["stages"]) == ["dns"]
        assert result["stages"]["dns"]["status"] == "error"
        connect.assert_not_called()
