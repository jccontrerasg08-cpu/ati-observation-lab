"""Live conformance checks for the deployed Worker and Railway origin.

This command talks to production. It is opt-in, is never run by CI, and should be run
after every Worker or origin deploy. Each probe is anonymous or carries only an
allowlisted marker; none carries a credential, cookie, body or personal data.

Probes that reach the origin do produce privacy-safe origin records, but they are never
part of a corpus: `ati-lab-corpus` joins only request identifiers recorded by the local
executor, and no probe writes a session record.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from observation_lab.pf2.catalogue import ROUTE_STATUS
from observation_lab.pf2.executor import DEFAULT_HOST, EXECUTOR_ID

DEFAULT_ORIGIN = "https://ati-observation-lab-production.up.railway.app"
_STDLIB_USER_AGENT = "Python-urllib/3.11"
_FAMILY_USER_AGENTS = {
    "curl": "curl/8.5.0",
    "wget": "Wget/1.21.4",
    "requests": "python-requests/2.34.2",
    "httpx": "python-httpx/0.28.1",
    "node-fetch": "node",
    "ati-lab-executor": EXECUTOR_ID,
    "playwright-chromium": "Mozilla/5.0 HeadlessChrome/140.0.0.0 Safari/537.36",
}

Response = tuple[int, dict[str, str], bytes]
Transport = Callable[[str, str, dict[str, str], bytes | None], Response]


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> Response:
    """Send one request with an explicit User-Agent and lowercased response headers."""

    request = urllib.request.Request(url, method=method, data=body)
    for name, value in {"User-Agent": EXECUTOR_ID, **headers}.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            lowered = {name.lower(): value for name, value in response.headers.items()}
            return response.status, lowered, response.read()
    except urllib.error.HTTPError as error:
        lowered = {name.lower(): value for name, value in error.headers.items()}
        return error.code, lowered, error.read()


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    expected: object
    observed: object

    @property
    def passed(self) -> bool:
        return self.expected == self.observed


def run_checks(
    *,
    transport: Transport,
    marker: str,
    other_marker: str,
    host: str = DEFAULT_HOST,
    origin: str = DEFAULT_ORIGIN,
) -> list[Check]:
    """Run every conformance probe and return one result per check."""

    checks: list[Check] = []

    def get(
        path: str,
        headers: dict[str, str] | None = None,
        *,
        method: str = "GET",
        base: str = host,
        body: bytes | None = None,
    ) -> Response:
        return transport(method, f"{base}{path}", headers or {}, body)

    def status(
        path: str,
        headers: dict[str, str] | None = None,
        *,
        method: str = "GET",
        base: str = host,
        body: bytes | None = None,
    ) -> int:
        return get(path, headers, method=method, base=base, body=body)[0]

    def add(name: str, expected: object, observed: object) -> None:
        checks.append(Check(name, expected, observed))

    marked = {"X-ATI-Experiment-ID": marker}
    add("lab-start-without-marker", 403, status("/lab/start"))
    add(
        "lab-start-unknown-marker",
        403,
        status("/lab/start", {"X-ATI-Experiment-ID": "not-an-allowlisted-marker"}),
    )
    add(
        "lab-start-malformed-marker",
        403,
        status("/lab/start", {"X-ATI-Experiment-ID": "bad marker with spaces"}),
    )
    add("route-outside-catalogue", 400, status("/lab/not-a-route", marked))
    add("healthz-not-proxied", 400, status("/healthz"))
    add("query-string-refused", 400, status("/lab/start?x=1", marked))
    add("cookie-refused", 400, status("/lab/start", {**marked, "Cookie": "a=b"}))
    add(
        "authorization-refused",
        400,
        status("/lab/start", {**marked, "Authorization": "Bearer synthetic"}),
    )
    add("post-refused", 400, status("/lab/start", marked, method="POST", body=b""))

    start_status, start_headers, _ = get("/lab/start", marked)
    token = start_headers.get("x-ati-lab-session", "")
    first_id = start_headers.get("x-ati-request-id", "")
    add(
        "lab-start-issues-session",
        (200, True, True),
        (
            start_status,
            token.startswith("ati1.") and token.count(".") == 2,
            bool(first_id),
        ),
    )
    session = {**marked, "X-ATI-Lab-Session": token}
    add("continuation-without-session", 403, status("/lab/page/landing", marked))
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    add(
        "tampered-session-refused",
        403,
        status("/lab/page/landing", {**marked, "X-ATI-Lab-Session": tampered}),
    )
    add(
        "cross-campaign-session-refused",
        403,
        status(
            "/lab/page/landing",
            {"X-ATI-Experiment-ID": other_marker, "X-ATI-Lab-Session": token},
        ),
    )
    continued_status, continued_headers, _ = get("/lab/page/landing", session)
    continued_id = continued_headers.get("x-ati-request-id", "")
    add(
        "bound-session-continues",
        (200, True, True),
        (continued_status, bool(continued_id), continued_id != first_id),
    )
    add("lab-start-rejects-existing-session", 403, status("/lab/start", session))

    get_status, get_headers, get_body = get("/lab/page/catalog", session)
    head_status, head_headers, head_body = get("/lab/page/catalog", session, method="HEAD")
    add(
        "head-matches-get-without-body",
        (get_status, get_headers.get("content-type"), 0, True),
        (head_status, head_headers.get("content-type"), len(head_body), bool(get_body)),
    )
    _, landing_headers, _ = get("/lab/page/landing", session)
    add(
        "no-store-and-no-cookie",
        ("no-store", False),
        (landing_headers.get("cache-control"), "set-cookie" in landing_headers),
    )
    served = {path: status(path, session) for path in ROUTE_STATUS if path != "/lab/start"}
    add(
        "every-catalogue-route-served-as-declared",
        {path: code for path, code in ROUTE_STATUS.items() if path != "/lab/start"},
        served,
    )

    direct_status, _, direct_body = get("/lab/start", base=origin)
    add(
        "origin-refuses-direct-observation",
        (503, True),
        (direct_status, b"observation unavailable" in direct_body),
    )
    health_status, _, health_body = get("/healthz", base=origin)
    add("origin-healthz-available", (200, True), (health_status, b'"ok"' in health_body))
    add(
        "origin-refuses-forged-proxy-context",
        503,
        status(
            "/lab/start",
            {
                "X-ATI-Proxy-Client-ID": "hmac-sha256:" + "0" * 64,
                "X-ATI-UA-Provenance-Bucket": "scripted-http",
                "X-ATI-Proxy-Session-ID": "hmac-sha256:" + "0" * 64,
            },
            base=origin,
        ),
    )

    stdlib_status, _, stdlib_body = get("/healthz", {"User-Agent": _STDLIB_USER_AGENT})
    reachable = {
        family: status("/healthz", {"User-Agent": agent})
        for family, agent in _FAMILY_USER_AGENTS.items()
    }
    add(
        "edge-reachability-by-executor-family",
        {"stdlib-denied-by-edge": True, **dict.fromkeys(_FAMILY_USER_AGENTS, 400)},
        {
            "stdlib-denied-by-edge": stdlib_status == 403 and b"1010" in stdlib_body,
            **reachable,
        },
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ati-lab-perimeter",
        description="Opt-in live conformance checks for the deployed Worker and origin.",
    )
    parser.add_argument("--marker", required=True, help="An allowlisted opaque marker.")
    parser.add_argument(
        "--other-marker",
        required=True,
        help="A second allowlisted marker, used to prove sessions are campaign-bound.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--output", type=Path, help="Optional JSON results path.")
    args = parser.parse_args(argv)
    if args.marker == args.other_marker:
        print("error: --other-marker must differ from --marker", file=sys.stderr)
        return 2

    checks = run_checks(
        transport=urllib_transport,
        marker=args.marker,
        other_marker=args.other_marker,
        host=args.host,
        origin=args.origin,
    )
    for check in checks:
        verdict = "PASS" if check.passed else "FAIL"
        detail = (
            "" if check.passed else f" expected={check.expected} observed={check.observed}"
        )
        print(f"[{verdict}] {check.name}{detail}")
    failed = [check.name for check in checks if not check.passed]
    summary = {"total": len(checks), "passed": len(checks) - len(failed), "failed": failed}
    print(json.dumps(summary, sort_keys=True))
    if args.output:
        args.output.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "checks": [
                        {
                            "name": check.name,
                            "passed": check.passed,
                            "expected": check.expected,
                            "observed": check.observed,
                        }
                        for check in checks
                    ],
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
