from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from collections import OrderedDict, deque
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WRITE_LOCK = threading.Lock()


class _RateLimiter:
    def __init__(self, *, per_minute: int, max_clients: int = 10_000) -> None:
        self._per_minute = per_minute
        self._max_clients = max_clients
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, client_id: str) -> bool:
        now = monotonic()
        with self._lock:
            history = self._requests.get(client_id)
            if history is None:
                if len(self._requests) >= self._max_clients:
                    return False
                history = deque()
                self._requests[client_id] = history
            else:
                self._requests.move_to_end(client_id)
            while history and now - history[0] >= 60:
                history.popleft()
            if len(history) >= self._per_minute:
                return False
            history.append(now)
            return True


def _positive_environment_integer(name: str, default: int) -> int:
    value = os.environ.get(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


def _client_id(raw_address: str) -> str:
    key = os.environ.get("ATI_CLIENT_HASH_KEY", "").encode("utf-8")
    if not key:
        raise RuntimeError("ATI_CLIENT_HASH_KEY must be configured")
    return "blake2b:" + hashlib.blake2b(
        raw_address.encode("utf-8"), key=key, digest_size=16, person=b"ati-client-v0"
    ).hexdigest()


def _trusted_proxy_client_id(request: Request) -> str:
    expected_token = os.environ.get("ATI_TRUSTED_PROXY_TOKEN", "")
    provided_token = request.headers.get("X-ATI-Proxy-Token", "")
    client_id = request.headers.get("X-ATI-Proxy-Client-ID", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        raise RuntimeError("trusted proxy authentication failed")
    if not re.fullmatch(r"hmac-sha256:[0-9a-f]{64}", client_id):
        raise RuntimeError("trusted proxy client identifier is invalid")
    return client_id


def _observation_client_id(request: Request) -> str:
    return _client_id(_trusted_proxy_client_id(request))


def _campaign_marker(request: Request) -> str | None:
    marker = request.headers.get("X-ATI-Experiment-ID")
    if marker and _CAMPAIGN_ID.fullmatch(marker):
        return marker
    return None


def _record(request: Request, response: Response, client_id: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "request_id": secrets.token_hex(16),
        "time_iso8601": datetime.now(UTC).isoformat(),
        "client_id": client_id,
        "request_method": request.method,
        "request_uri": request.url.path,
        "status": response.status_code,
        "body_bytes_sent": int(response.headers.get("content-length", "0")),
        "server_protocol": f"HTTP/{request.scope.get('http_version', 'unknown')}",
        "http_user_agent": request.headers.get("user-agent", "")[:512],
    }
    marker = _campaign_marker(request)
    if marker:
        record["ati_campaign_id"] = marker
    return record


def _emit(record: dict[str, Any]) -> None:
    serialized = json.dumps(record, separators=(",", ":"), sort_keys=True)
    log_path = os.environ.get("ATI_LOG_PATH")
    with _WRITE_LOCK:
        print(serialized, flush=True)
        if log_path:
            with Path(log_path).open("a", encoding="utf-8") as stream:
                stream.write(serialized + "\n")


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    limiter = _RateLimiter(
        per_minute=_positive_environment_integer("ATI_RATE_LIMIT_PER_MINUTE", 30)
    )

    @app.middleware("http")
    async def observe(request: Request, call_next):  # type: ignore[no-untyped-def]
        should_observe = request.method in {"GET", "HEAD"} and request.url.path != "/healthz"
        if should_observe:
            try:
                client_id = _observation_client_id(request)
                if not limiter.allow(client_id):
                    return JSONResponse(
                        {"detail": "rate limit exceeded"},
                        status_code=429,
                        headers={"Retry-After": "60", "Cache-Control": "no-store"},
                    )
            except RuntimeError:
                return JSONResponse(
                    {"detail": "observation unavailable"},
                    status_code=503,
                    headers={"Cache-Control": "no-store"},
                )
        response = await call_next(request)
        if should_observe:
            _emit(_record(request, response, client_id))
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(
            "<main><h1>ATI Observation Lab</h1>"
            "<p>Controlled traffic observation endpoint.</p></main>",
            headers={"Cache-Control": "no-store"},
        )

    @app.api_route("/observe", methods=["GET", "HEAD"], response_class=JSONResponse)
    async def observe_endpoint() -> JSONResponse:
        return JSONResponse(
            {"status": "observed"}, headers={"Cache-Control": "no-store"}
        )

    @app.get("/healthz", response_class=JSONResponse)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    return app


app = create_app()
