from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx

from observation_lab.app import create_app

_TRUSTED_PROXY_HEADERS = {
    "X-ATI-Proxy-Token": "test-origin-token",
    "X-ATI-Proxy-Client-ID": "hmac-sha256:" + "a" * 64,
}


def request(
    app: Any,
    method: str,
    path: str,
    *,
    client: tuple[str, int] = ("127.0.0.1", 123),
    via_trusted_proxy: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    if via_trusted_proxy:
        for name, value in _TRUSTED_PROXY_HEADERS.items():
            headers.setdefault(name, value)

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            return await http_client.request(method, path, headers=headers, **kwargs)

    return asyncio.run(send())


def configure_observation(monkeypatch, log_path: Path) -> None:
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    monkeypatch.setenv("ATI_TRUSTED_PROXY_TOKEN", "test-origin-token")


def test_observe_writes_privacy_safe_jsonl_for_allowlisted_campaign_marker(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
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
    assert "test-origin-token" not in serialized
    assert _TRUSTED_PROXY_HEADERS["X-ATI-Proxy-Client-ID"] not in serialized


def test_observe_writes_distinct_opaque_request_ids_for_label_correlation(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()

    first = request(app, "GET", "/observe")
    second = request(app, "GET", "/observe")

    assert first.status_code == 200
    assert second.status_code == 200
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    request_ids = [record["request_id"] for record in records]
    assert len(request_ids) == 2
    assert request_ids[0] != request_ids[1]
    assert all(re.fullmatch(r"[0-9a-f]{32}", request_id) for request_id in request_ids)


def test_healthz_does_not_create_an_observation_log(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()

    response = request(app, "GET", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not log_path.exists()


def test_observe_discards_invalid_campaign_marker_and_non_get_requests(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
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


def test_observe_supports_head_without_a_response_body(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()

    response = request(
        app,
        "HEAD",
        "/observe",
        headers={"X-ATI-Experiment-ID": "owned-shadow-2026-08-19-head"},
    )

    assert response.status_code == 200
    assert response.content == b""
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["request_method"] == "HEAD"
    assert record["ati_campaign_id"] == "owned-shadow-2026-08-19-head"


def test_observe_rate_limits_each_pseudonymous_client_without_logging_rejection(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
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
    configure_observation(monkeypatch, log_path)
    monkeypatch.setenv("ATI_RATE_LIMIT_PER_MINUTE", "1")
    app = create_app()

    first = request(
        app,
        "GET",
        "/observe",
        client=("10.0.0.1", 8000),
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    second = request(
        app,
        "GET",
        "/observe",
        client=("10.0.0.2", 8000),
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert log_path.read_text(encoding="utf-8").count("\n") == 1


def test_observe_rejects_direct_requests_even_when_xff_is_spoofed(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()

    response = request(
        app,
        "GET",
        "/observe",
        via_trusted_proxy=False,
        headers={
            "X-Forwarded-For": "198.51.100.7, 10.0.0.1",
            "X-ATI-Proxy-Client-ID": "hmac-sha256:" + "b" * 64,
        },
    )

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert not log_path.exists()


def test_observe_rejects_invalid_trusted_proxy_token_without_logging(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()

    response = request(
        app,
        "GET",
        "/observe",
        headers={"X-ATI-Proxy-Token": "wrong-origin-token"},
    )

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert not log_path.exists()


def test_observe_fails_closed_without_trusted_proxy_configuration(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.setenv("ATI_CLIENT_HASH_KEY", "test-client-hash-key")
    monkeypatch.delenv("ATI_TRUSTED_PROXY_TOKEN", raising=False)
    app = create_app()

    response = request(app, "GET", "/observe")

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert not log_path.exists()


def test_observe_fails_closed_without_client_hash_key(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("ATI_LOG_PATH", str(log_path))
    monkeypatch.delenv("ATI_CLIENT_HASH_KEY", raising=False)
    monkeypatch.setenv("ATI_TRUSTED_PROXY_TOKEN", "test-origin-token")
    app = create_app()

    response = request(app, "GET", "/observe")

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert not log_path.exists()


def test_railway_start_command_disables_uvicorn_access_logs() -> None:
    railway_config = Path("railway.toml").read_text(encoding="utf-8")

    assert "--no-access-log" in railway_config


def test_lab_page_requires_proxy_derived_session_and_logs_only_opaque_value(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()
    session_id = "hmac-sha256:" + "c" * 64

    rejected = request(app, "GET", "/lab/page/landing")
    accepted = request(
        app,
        "GET",
        "/lab/page/landing",
        headers={
            "X-ATI-Proxy-Session-ID": session_id,
            "X-ATI-Experiment-ID": "owned-general-2026-08-21-playwright",
        },
    )

    assert rejected.status_code == 403
    assert rejected.headers["Cache-Control"] == "no-store"
    assert accepted.status_code == 200
    assert accepted.headers["Content-Type"].startswith("text/html")
    assert 'href="/lab/page/catalog"' in accepted.text
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["request_uri"] == "/lab/page/landing"
    assert record["session_id"] == session_id
    assert record["ati_campaign_id"] == "owned-general-2026-08-21-playwright"
    assert "X-ATI-Proxy-Session-ID" not in log_path.read_text(encoding="utf-8")


def test_lab_assets_support_get_and_head_with_equivalent_metadata(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()
    headers = {"X-ATI-Proxy-Session-ID": "hmac-sha256:" + "d" * 64}

    get_response = request(app, "GET", "/lab/assets/site.css", headers=headers)
    head_response = request(app, "HEAD", "/lab/assets/site.css", headers=headers)

    assert get_response.status_code == 200
    assert head_response.status_code == 200
    assert get_response.headers["Content-Type"] == head_response.headers["Content-Type"]
    assert get_response.headers["Content-Length"] == head_response.headers["Content-Length"]
    assert get_response.content
    assert head_response.content == b""
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [record["request_method"] for record in records] == ["GET", "HEAD"]
    assert {record["session_id"] for record in records} == {headers["X-ATI-Proxy-Session-ID"]}


def test_lab_rejects_query_and_cookie_without_logging(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()
    headers = {
        "X-ATI-Proxy-Session-ID": "hmac-sha256:" + "e" * 64,
        "Cookie": "experiment=must-not-reach-lab",
    }

    response = request(app, "GET", "/lab/page/landing?token=must-not-log", headers=headers)

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert not log_path.exists()


def test_lab_start_accepts_proxy_derived_session_and_logs_only_opaque_value(
    tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "access.jsonl"
    configure_observation(monkeypatch, log_path)
    app = create_app()
    session_id = "hmac-sha256:" + "f" * 64

    response = request(
        app,
        "GET",
        "/lab/start",
        headers={
            "X-ATI-Proxy-Session-ID": session_id,
            "X-ATI-Experiment-ID": "owned-workersdev-2026-08-21-pilot",
        },
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert 'href="/lab/page/landing"' in response.text
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["request_uri"] == "/lab/start"
    assert record["session_id"] == session_id
    assert "X-ATI-Proxy-Session-ID" not in log_path.read_text(encoding="utf-8")
