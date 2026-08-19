from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from observation_lab.app import create_app


def request(
    app: Any,
    method: str,
    path: str,
    *,
    client: tuple[str, int] = ("127.0.0.1", 123),
    **kwargs: Any,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            return await http_client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_observe_writes_privacy_safe_jsonl_for_allowlisted_campaign_marker(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    app = create_app()

    response = request(
        app,
        "GET",
        "/observe",
        headers={
            "User-Agent": "ControlledAgent/1.0",
            "X-ATI-Experiment-ID": "owned-shadow-2026-08-19-a",
            "Authorization": "Bearer never-log-this",
            "Cookie": "session=do-not-log",
        },
        params={"token": "never-log-this", "email": "private@example.com"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["ati_campaign_id"] == "owned-shadow-2026-08-19-a"
    assert record["request_method"] == "GET"
    assert record["request_uri"] == "/observe"
    assert record["http_user_agent"] == "ControlledAgent/1.0"
    assert record["client_id"].startswith("blake2b:")
    serialized = log_path.read_text(encoding="utf-8")
    assert "never-log-this" not in serialized
    assert "private@example.com" not in serialized
    assert "do-not-log" not in serialized
    assert "Authorization" not in serialized


def test_healthz_does_not_create_an_observation_log(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    app = create_app()

    response = request(app, "GET", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not log_path.exists()


def test_observe_discards_invalid_campaign_marker_and_non_get_requests(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    app = create_app()

    invalid_marker_response = request(
        app, "GET", "/observe", headers={"X-ATI-Experiment-ID": "private@example.com"}
    )
    rejected_method_response = request(app, "POST", "/observe")

    assert invalid_marker_response.status_code == 200
    assert rejected_method_response.status_code == 405
    serialized = log_path.read_text(encoding="utf-8")
    assert "ati_campaign_id" not in serialized
    assert "private@example.com" not in serialized
    assert serialized.count("\n") == 1


def test_observe_rate_limits_each_pseudonymous_client_without_logging_rejection(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    monkeypatch.setenv("ATI_RATE_LIMIT_PER_MINUTE", "1")
    app = create_app()

    first = request(app, "GET", "/observe")
    second = request(app, "GET", "/observe")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert log_path.read_text(encoding="utf-8").count("\n") == 1


def test_observe_rate_limits_trusted_proxy_client_across_rotating_peers(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    monkeypatch.setenv("ATI_RATE_LIMIT_PER_MINUTE", "1")
    app = create_app()
    headers = {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}

    first = request(
        app, "GET", "/observe", client=("10.0.0.1", 8000), headers=headers
    )
    second = request(
        app, "GET", "/observe", client=("10.0.0.2", 8000), headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert log_path.read_text(encoding="utf-8").count("\n") == 1


def test_observe_fails_closed_without_client_hash_key(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.delenv("ATI_CLIENT_HASH_KEY", raising=False)
    app = create_app()

    response = request(app, "GET", "/observe")

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert not log_path.exists()


def test_railway_start_command_disables_uvicorn_access_logs() -> None:
    railway_config = Path("railway.toml").read_text(encoding="utf-8")

    assert "--no-access-log" in railway_config
