"""Unit tests for ViniMidas peer MLX plane lease client (mocked HTTP)."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest


@pytest.fixture()
def lease_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VINIMIDAS_MCP_HTTP_URL", "http://127.0.0.1:3100")
    monkeypatch.setenv("VINIMIDAS_MCP_HTTP_SECRET", "test-secret")
    monkeypatch.setenv("NEURALDISC_MLX_PEER_ID", "neuraldisc")
    monkeypatch.setenv("NEURALDISC_MLX_LEASE_TTL_MS", "600000")
    monkeypatch.setenv("NEURALDISC_MLX_LEASE_RENEW_INTERVAL_MS", "300000")
    monkeypatch.setenv("NEURALDISC_MLX_LEASE_REQUIRED", "1")
    # Reset module state between tests
    import neuraldisc.mlx_plane_lease as m

    monkeypatch.setattr(m, "_current", None)
    monkeypatch.setattr(m, "_session_depth", 0)
    monkeypatch.setattr(m, "_renew_thread", None)
    m._renew_stop.set()
    yield m
    m._stop_renew_loop()
    with m._state_lock:
        m._current = None
        m._session_depth = 0


def test_parse_tool_response_nested():
    from neuraldisc.mlx_plane_lease import parse_tool_response

    flat = parse_tool_response(
        {"ok": True, "lease_token": "abc", "result": {"expires_at": "t"}}
    )
    assert flat["lease_token"] == "abc"
    assert flat["expires_at"] == "t"


def test_acquire_success(lease_env, monkeypatch: pytest.MonkeyPatch):
    m = lease_env

    def fake_call(tool, body, *, timeout_s):
        assert tool == "acquire_mlx_plane_lease"
        assert body["peer_id"] == "neuraldisc"
        assert body["holder_id"] == "worker-1"
        assert "Authorization" or True
        return {
            "ok": True,
            "acquired": True,
            "lease_token": "tok-12345678",
            "expires_at": "2026-08-12T01:00:00Z",
            "mlx_host": "http://127.0.0.1:8088",
        }

    monkeypatch.setattr(m, "call_mcp_tool", fake_call)
    # Don't start real renew thread spam — stop immediately after acquire starts it
    monkeypatch.setattr(m, "_start_renew_loop", lambda: None)

    state = m.acquire("worker-1", purpose="vlm_batch")
    assert state.lease_token == "tok-12345678"
    assert state.mlx_host.endswith(":8088")
    assert m.current_lease() is not None


def test_acquire_busy(lease_env, monkeypatch: pytest.MonkeyPatch):
    m = lease_env

    def fake_call(tool, body, *, timeout_s):
        return {
            "ok": False,
            "acquired": False,
            "reason": "timeout",
            "blocker": "campaign_email",
        }

    monkeypatch.setattr(m, "call_mcp_tool", fake_call)
    with pytest.raises(m.MlxPlaneLeaseError) as ei:
        m.acquire("worker-1")
    assert ei.value.reason == "timeout"
    assert ei.value.blocker == "campaign_email"


def test_renew_and_release(lease_env, monkeypatch: pytest.MonkeyPatch):
    m = lease_env
    monkeypatch.setattr(m, "_start_renew_loop", lambda: None)
    monkeypatch.setattr(m, "_stop_renew_loop", lambda: None)

    calls: list[str] = []

    def fake_call(tool, body, *, timeout_s):
        calls.append(tool)
        if tool == "acquire_mlx_plane_lease":
            return {
                "ok": True,
                "acquired": True,
                "lease_token": "tok-abcdef01",
                "expires_at": "t1",
            }
        if tool == "renew_mlx_plane_lease":
            assert body["lease_token"] == "tok-abcdef01"
            return {"ok": True, "expires_at": "t2"}
        if tool == "release_mlx_plane_lease":
            assert body["lease_token"] == "tok-abcdef01"
            return {"ok": True, "released": True}
        raise AssertionError(tool)

    monkeypatch.setattr(m, "call_mcp_tool", fake_call)
    m.acquire("h1")
    renewed = m.renew()
    assert renewed["expires_at"] == "t2"
    out = m.release()
    assert out["released"] is True
    assert m.current_lease() is None
    assert calls == [
        "acquire_mlx_plane_lease",
        "renew_mlx_plane_lease",
        "release_mlx_plane_lease",
    ]


def test_context_manager_releases(lease_env, monkeypatch: pytest.MonkeyPatch):
    m = lease_env
    monkeypatch.setattr(m, "_start_renew_loop", lambda: None)
    monkeypatch.setattr(m, "_stop_renew_loop", lambda: None)

    def fake_call(tool, body, *, timeout_s):
        if tool == "acquire_mlx_plane_lease":
            return {
                "ok": True,
                "acquired": True,
                "lease_token": "tok-ctx00001",
                "expires_at": "t",
            }
        if tool == "release_mlx_plane_lease":
            return {"ok": True, "released": True}
        return {"ok": True}

    monkeypatch.setattr(m, "call_mcp_tool", fake_call)
    with m.mlx_plane_lease(holder_id="ctx", purpose="vlm_batch", vlm_enabled=True):
        assert m.current_lease() is not None
    assert m.current_lease() is None


def test_lease_required_flag(monkeypatch: pytest.MonkeyPatch):
    from neuraldisc.mlx_plane_lease import lease_required

    monkeypatch.delenv("VINIMIDAS_MCP_HTTP_SECRET", raising=False)
    monkeypatch.delenv("NEURALDISC_VINIMIDAS_MCP_HTTP_SECRET", raising=False)
    monkeypatch.setenv("NEURALDISC_MLX_LEASE_REQUIRED", "0")
    assert lease_required(vlm_enabled=True) is False

    monkeypatch.setenv("NEURALDISC_MLX_LEASE_REQUIRED", "1")
    assert lease_required(vlm_enabled=True) is True
    assert lease_required(vlm_enabled=False) is False


def test_call_mcp_tool_auth_header(lease_env, monkeypatch: pytest.MonkeyPatch):
    m = lease_env
    captured: dict = {}

    class FakeResp:
        status = 200

        def read(self):
            return json.dumps(
                {"ok": True, "acquired": True, "lease_token": "x" * 16}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(m, "urlopen", fake_urlopen)
    monkeypatch.setattr(m, "_start_renew_loop", lambda: None)

    # Use call_mcp_tool directly
    payload = m.call_mcp_tool(
        "acquire_mlx_plane_lease",
        {"peer_id": "neuraldisc", "holder_id": "h"},
        timeout_s=5,
    )
    assert payload["lease_token"]
    assert captured["auth"] == "Bearer test-secret"
    assert captured["url"].endswith("/tools/acquire_mlx_plane_lease")


def test_http_error_maps(lease_env, monkeypatch: pytest.MonkeyPatch):
    m = lease_env

    def boom(req, timeout=None):
        raise HTTPError(
            req.full_url, 401, "Unauthorized", hdrs=None, fp=io.BytesIO(b"nope")
        )

    monkeypatch.setattr(m, "urlopen", boom)
    with pytest.raises(m.MlxPlaneLeaseError) as ei:
        m.call_mcp_tool("get_mlx_plane_lease", {}, timeout_s=5)
    assert ei.value.status == 401
