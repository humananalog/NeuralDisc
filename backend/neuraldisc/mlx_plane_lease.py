"""ViniMidas peer MLX plane lease client.

NeuralDisc must hold a short-TTL lease (via ViniMidas MCP HTTP) before loading
in-process mlx-vlm onto Metal. Peers never write ``runtime_plane_holds`` and
never bind/kill ViniMidas ``:8088``.

Auth: ``Authorization: Bearer <VINIMIDAS_MCP_HTTP_SECRET>``
Tools: acquire / renew / release / get_mlx_plane_lease
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

PEER_ID_DEFAULT = "neuraldisc"
DEFAULT_MCP_URL = "http://127.0.0.1:3100"
DEFAULT_TTL_MS = 600_000
DEFAULT_RENEW_MS = 300_000
DEFAULT_MAX_WAIT_MS = 120_000


class MlxPlaneLeaseError(RuntimeError):
    """Raised when the peer lease cannot be acquired or is lost."""

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        blocker: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.blocker = blocker
        self.status = status


@dataclass
class LeaseState:
    lease_token: str
    holder_id: str
    purpose: str
    expires_at: str | None = None
    mlx_host: str | None = None
    acquired_at: float = field(default_factory=time.time)


# Process-wide holder id (stable across jobs in this API process)
_PROCESS_HOLDER_ID = f"neuraldisc-pid-{os.getpid()}-{uuid.uuid4().hex[:8]}"

_state_lock = threading.RLock()
_current: LeaseState | None = None
_renew_stop = threading.Event()
_renew_thread: threading.Thread | None = None
_session_depth = 0


def process_holder_id() -> str:
    return _PROCESS_HOLDER_ID


def mcp_http_url() -> str:
    return (
        os.environ.get("VINIMIDAS_MCP_HTTP_URL")
        or os.environ.get("NEURALDISC_VINIMIDAS_MCP_HTTP_URL")
        or DEFAULT_MCP_URL
    ).rstrip("/")


def mcp_http_secret() -> str:
    return (
        os.environ.get("VINIMIDAS_MCP_HTTP_SECRET")
        or os.environ.get("NEURALDISC_VINIMIDAS_MCP_HTTP_SECRET")
        or ""
    ).strip()


def peer_id() -> str:
    return (
        os.environ.get("NEURALDISC_MLX_PEER_ID")
        or PEER_ID_DEFAULT
    ).strip() or PEER_ID_DEFAULT


def lease_ttl_ms() -> int:
    raw = os.environ.get("NEURALDISC_MLX_LEASE_TTL_MS")
    try:
        return max(30_000, int(raw)) if raw else DEFAULT_TTL_MS
    except ValueError:
        return DEFAULT_TTL_MS


def lease_renew_interval_ms() -> int:
    raw = os.environ.get("NEURALDISC_MLX_LEASE_RENEW_INTERVAL_MS")
    try:
        return max(5_000, int(raw)) if raw else DEFAULT_RENEW_MS
    except ValueError:
        return DEFAULT_RENEW_MS


def lease_max_wait_ms() -> int:
    raw = os.environ.get("NEURALDISC_MLX_LEASE_MAX_WAIT_MS")
    try:
        return max(0, int(raw)) if raw else DEFAULT_MAX_WAIT_MS
    except ValueError:
        return DEFAULT_MAX_WAIT_MS


def lease_configured() -> bool:
    return bool(mcp_http_secret())


def lease_required(*, vlm_enabled: bool) -> bool:
    """Whether Metal/VLM work must hold a peer lease.

    - Explicit ``NEURALDISC_MLX_LEASE_REQUIRED=0`` → never (tests / solo Mac).
    - Explicit ``=1`` → always when VLM enabled (fail closed without secret).
    - Default: required when VLM enabled **and** MCP secret is configured.
    """
    if not vlm_enabled:
        return False
    flag = os.environ.get("NEURALDISC_MLX_LEASE_REQUIRED", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return lease_configured()


def current_lease() -> LeaseState | None:
    with _state_lock:
        return _current


def parse_tool_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize MCP HTTP tool JSON (flat or nested ``result``)."""
    if not isinstance(payload, dict):
        return {}
    if "result" in payload and isinstance(payload["result"], dict):
        merged = {**payload, **payload["result"]}
        return merged
    return payload


def call_mcp_tool(tool: str, body: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    """POST ``{base}/tools/{tool}`` with Bearer auth. Returns parsed JSON."""
    import json

    secret = mcp_http_secret()
    if not secret:
        raise MlxPlaneLeaseError(
            "VINIMIDAS_MCP_HTTP_SECRET is not set",
            reason="not_configured",
        )
    url = f"{mcp_http_url()}/tools/{tool}"
    data = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise MlxPlaneLeaseError(
            f"MCP {tool} HTTP {exc.code}: {err_body or exc.reason}",
            reason="http_error",
            status=exc.code,
        ) from exc
    except URLError as exc:
        raise MlxPlaneLeaseError(
            f"MCP {tool} unreachable: {exc.reason}",
            reason="unreachable",
        ) from exc

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise MlxPlaneLeaseError(
            f"MCP {tool} returned invalid JSON",
            reason="bad_json",
            status=status,
        ) from exc
    return parse_tool_response(payload)


def acquire(
    holder_id: str | None = None,
    *,
    purpose: str = "vlm_batch",
    ttl_ms: int | None = None,
    max_wait_ms: int | None = None,
    wait_for_idle_slot: bool = True,
) -> LeaseState:
    """Acquire a peer MLX plane lease (blocks up to max_wait_ms)."""
    hid = holder_id or process_holder_id()
    ttl = ttl_ms if ttl_ms is not None else lease_ttl_ms()
    wait = max_wait_ms if max_wait_ms is not None else lease_max_wait_ms()
    # HTTP timeout must exceed wait (server may block)
    timeout_s = max(30.0, (wait / 1000.0) + 30.0)

    body = {
        "peer_id": peer_id(),
        "holder_id": hid,
        "purpose": purpose,
        "ttl_ms": ttl,
        "max_wait_ms": wait,
        "wait_for_idle_slot": wait_for_idle_slot,
    }
    log.info(
        "mlx_lease_acquire_start",
        peer_id=peer_id(),
        holder_id=hid,
        purpose=purpose,
        ttl_ms=ttl,
        max_wait_ms=wait,
    )
    payload = call_mcp_tool("acquire_mlx_plane_lease", body, timeout_s=timeout_s)
    token = payload.get("lease_token")
    acquired = bool(payload.get("acquired")) or (
        bool(payload.get("ok")) and bool(token)
    )
    if not acquired or not token:
        reason = str(payload.get("reason") or "plane_held")
        blocker = payload.get("blocker")
        raise MlxPlaneLeaseError(
            f"MLX plane lease not acquired ({reason})"
            + (f": {blocker}" if blocker else ""),
            reason=reason,
            blocker=str(blocker) if blocker else None,
        )

    state = LeaseState(
        lease_token=str(token),
        holder_id=hid,
        purpose=purpose,
        expires_at=str(payload["expires_at"]) if payload.get("expires_at") else None,
        mlx_host=str(payload["mlx_host"]) if payload.get("mlx_host") else None,
    )
    global _current
    with _state_lock:
        _current = state
    _start_renew_loop()
    log.info(
        "mlx_lease_acquired",
        holder_id=hid,
        lease_token=state.lease_token[:8] + "…",
        expires_at=state.expires_at,
        mlx_host=state.mlx_host,
    )
    return state


def renew(
    lease_token: str | None = None,
    *,
    holder_id: str | None = None,
    ttl_ms: int | None = None,
) -> dict[str, Any]:
    with _state_lock:
        state = _current
    token = lease_token or (state.lease_token if state else None)
    hid = holder_id or (state.holder_id if state else process_holder_id())
    if not token:
        raise MlxPlaneLeaseError("No lease_token to renew", reason="no_lease")
    ttl = ttl_ms if ttl_ms is not None else lease_ttl_ms()
    payload = call_mcp_tool(
        "renew_mlx_plane_lease",
        {
            "peer_id": peer_id(),
            "holder_id": hid,
            "lease_token": token,
            "ttl_ms": ttl,
        },
        timeout_s=30.0,
    )
    ok = payload.get("ok", True)
    if ok is False or payload.get("reason") in (
        "lease_token_mismatch",
        "not_active",
        "stolen",
    ):
        raise MlxPlaneLeaseError(
            f"Lease renew failed: {payload.get('reason') or payload}",
            reason=str(payload.get("reason") or "renew_failed"),
            blocker=str(payload.get("blocker")) if payload.get("blocker") else None,
        )
    expires = payload.get("expires_at")
    with _state_lock:
        if _current and _current.lease_token == token:
            if expires:
                _current.expires_at = str(expires)
    log.debug("mlx_lease_renewed", expires_at=expires)
    return payload


def release(
    lease_token: str | None = None,
    *,
    holder_id: str | None = None,
) -> dict[str, Any]:
    """Release scoped peer lease; clears local state. Idempotent."""
    global _current
    _stop_renew_loop()
    with _state_lock:
        state = _current
        token = lease_token or (state.lease_token if state else None)
        hid = holder_id or (state.holder_id if state else process_holder_id())
        _current = None

    if not token:
        return {"released": False, "reason": "no_lease"}

    try:
        payload = call_mcp_tool(
            "release_mlx_plane_lease",
            {
                "peer_id": peer_id(),
                "holder_id": hid,
                "lease_token": token,
            },
            timeout_s=30.0,
        )
    except MlxPlaneLeaseError as exc:
        log.warning("mlx_lease_release_failed", error=str(exc), reason=exc.reason)
        return {"released": False, "reason": exc.reason, "error": str(exc)}

    log.info(
        "mlx_lease_released",
        holder_id=hid,
        lease_token=token[:8] + "…",
        payload_ok=payload.get("ok", payload.get("released")),
    )
    return {"released": True, **{k: v for k, v in payload.items() if k != "released"}}


def get_lease(*, peer: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    pid = peer or peer_id()
    if pid:
        body["peer_id"] = pid
    return call_mcp_tool("get_mlx_plane_lease", body, timeout_s=15.0)


def lease_still_ours() -> bool:
    """True if get_mlx_plane_lease shows our peer hold (best-effort)."""
    with _state_lock:
        state = _current
    if not state:
        return False
    try:
        info = get_lease()
    except MlxPlaneLeaseError:
        return False
    if not info.get("active", True) and info.get("active") is not None:
        # some payloads use active=false when free
        if info.get("active") is False:
            return False
    # Match token or peer holder
    remote_token = info.get("lease_token")
    if remote_token and remote_token != state.lease_token:
        return False
    holder_type = info.get("holder_type")
    if holder_type and holder_type != "peer_app":
        return False
    remote_peer = info.get("peer_id") or info.get("holder_id")
    if remote_peer and remote_peer not in (peer_id(), state.holder_id):
        # holder_id match is enough
        if info.get("holder_id") != state.holder_id:
            return False
    return True


def _start_renew_loop() -> None:
    global _renew_thread
    _stop_renew_loop()
    _renew_stop.clear()
    interval = lease_renew_interval_ms() / 1000.0

    def _loop() -> None:
        global _current
        while not _renew_stop.wait(interval):
            with _state_lock:
                state = _current
            if not state:
                break
            try:
                renew(state.lease_token, holder_id=state.holder_id)
            except MlxPlaneLeaseError as exc:
                log.warning(
                    "mlx_lease_renew_lost",
                    reason=exc.reason,
                    error=str(exc),
                )
                # Signal loss — clear local lease; callers unload via ensure_lease
                with _state_lock:
                    if _current and _current.lease_token == state.lease_token:
                        _current = None
                try:
                    from neuraldisc.ai.vlm import release_vlm

                    release_vlm(force=True, release_plane_lease=False)
                except Exception as unload_exc:  # noqa: BLE001
                    log.warning("mlx_unload_after_lease_loss_failed", error=str(unload_exc))
                break

    _renew_thread = threading.Thread(
        target=_loop, name="mlx-plane-lease-renew", daemon=True
    )
    _renew_thread.start()


def _stop_renew_loop() -> None:
    global _renew_thread
    _renew_stop.set()
    t = _renew_thread
    _renew_thread = None
    if t and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=2.0)


def ensure_lease_held(
    *,
    vlm_enabled: bool,
    purpose: str = "vlm_batch",
    holder_id: str | None = None,
) -> LeaseState | None:
    """Acquire if required and missing; raise MlxPlaneLeaseError on failure."""
    if not lease_required(vlm_enabled=vlm_enabled):
        return current_lease()
    with _state_lock:
        state = _current
    if state is not None:
        return state
    if not lease_configured():
        raise MlxPlaneLeaseError(
            "MLX lease required but VINIMIDAS_MCP_HTTP_SECRET is unset",
            reason="not_configured",
        )
    return acquire(holder_id, purpose=purpose)


@contextmanager
def mlx_plane_lease(
    *,
    holder_id: str | None = None,
    purpose: str = "vlm_batch",
    vlm_enabled: bool = True,
) -> Generator[LeaseState | None, None, None]:
    """Acquire lease on enter (when required); always release in ``finally``."""
    global _session_depth
    with _state_lock:
        _session_depth += 1
        is_outer = _session_depth == 1
    acquired_here = False
    try:
        state: LeaseState | None = current_lease()
        if lease_required(vlm_enabled=vlm_enabled):
            if state is None:
                state = acquire(holder_id, purpose=purpose)
                acquired_here = True
        yield state
    finally:
        with _state_lock:
            _session_depth = max(0, _session_depth - 1)
            left = _session_depth
        # Outermost session always drops the lease in finally
        if is_outer and left == 0 and (acquired_here or current_lease() is not None):
            release()


def lease_status(*, vlm_enabled: bool = True) -> dict[str, Any]:
    with _state_lock:
        state = _current
        depth = _session_depth
    return {
        "required": lease_required(vlm_enabled=vlm_enabled),
        "configured": lease_configured(),
        "peer_id": peer_id(),
        "holder_id": state.holder_id if state else process_holder_id(),
        "held": state is not None,
        "lease_token_prefix": (state.lease_token[:8] + "…") if state else None,
        "expires_at": state.expires_at if state else None,
        "purpose": state.purpose if state else None,
        "session_depth": depth,
        "mcp_url": mcp_http_url(),
    }
