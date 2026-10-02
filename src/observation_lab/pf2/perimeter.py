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


@dataclass(frozen=True, slots=True)
class _Probe:
    """Sends one request to the edge, or to the origin when `to_origin` is set."""

    transport: Transport
    host: str
    origin: str

    def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        *,
        method: str = "GET",
        to_origin: bool = False,
        body: bytes | None = None,
    ) -> Response:
        base = self.origin if to_origin else self.host
        return self.transport(method, f"{base}{path}", headers or {}, body)

    def status(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        *,
        method: str = "GET",
        to_origin: bool = False,
        body: bytes | None = None,
    ) -> int:
        return self.get(path, headers, method=method, to_origin=to_origin, body=body)[0]


def run_checks(
    *,
    transport: Transport,
    marker: str,
    other_marker: str,
    host: str = DEFAULT_HOST,
    origin: str = DEFAULT_ORIGIN,
) -> list[Check]:
    """Run every conformance probe and return one result per check, in a fixed order."""

    probe = _Probe(transport, host, origin)
    marked = {"X-ATI-Experiment-ID": marker}
    # Probe order is part of the contract: each group runs only after the previous one.
    checks = _edge_refusal_checks(probe, marked)
    binding_checks, session = _session_binding_checks(probe, marked, other_marker)
    checks += binding_checks
    checks += _response_contract_checks(probe, session)
    checks += _origin_isolation_checks(probe)
    checks.append(_edge_reachability_check(probe))
    return checks


def _edge_refusal_checks(probe: _Probe, marked: dict[str, str]) -> list[Check]:
    """The Worker refuses anything outside the closed, marker-gated contract."""

    return [
        Check("lab-start-without-marker", 403, probe.status("/lab/start")),
        Check(
            "lab-start-unknown-marker",
            403,
            probe.status("/lab/start", {"X-ATI-Experiment-ID": "not-an-allowlisted-marker"}),
        ),
        Check(
            "lab-start-malformed-marker",
            403,
            probe.status("/lab/start", {"X-ATI-Experiment-ID": "bad marker with spaces"}),
        ),
        Check("route-outside-catalogue", 400, probe.status("/lab/not-a-route", marked)),
        Check("healthz-not-proxied", 400, probe.status("/healthz")),
        Check("query-string-refused", 400, probe.status("/lab/start?x=1", marked)),
        Check("cookie-refused", 400, probe.status("/lab/start", {**marked, "Cookie": "a=b"})),
        Check(
            "authorization-refused",
            400,
            probe.status("/lab/start", {**marked, "Authorization": "Bearer synthetic"}),
        ),
        Check("post-refused", 400, probe.status("/lab/start", marked, method="POST", body=b"")),
    ]


def _session_binding_checks(
    probe: _Probe, marked: dict[str, str], other_marker: str
) -> tuple[list[Check], dict[str, str]]:
    """A signed session is issued once, bound to one campaign, and cannot be forged."""

    start_status, start_headers, _ = probe.get("/lab/start", marked)
    token = start_headers.get("x-ati-lab-session", "")
    first_id = start_headers.get("x-ati-request-id", "")
    session = {**marked, "X-ATI-Lab-Session": token}
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    checks = [
        Check(
            "lab-start-issues-session",
            (200, True, True),
            (start_status, token.startswith("ati1.") and token.count(".") == 2, bool(first_id)),
        ),
        Check("continuation-without-session", 403, probe.status("/lab/page/landing", marked)),
        Check(
            "tampered-session-refused",
            403,
            probe.status("/lab/page/landing", {**marked, "X-ATI-Lab-Session": tampered}),
        ),
        Check(
            "cross-campaign-session-refused",
            403,
            probe.status(
                "/lab/page/landing",
                {"X-ATI-Experiment-ID": other_marker, "X-ATI-Lab-Session": token},
            ),
        ),
    ]
    continued_status, continued_headers, _ = probe.get("/lab/page/landing", session)
    continued_id = continued_headers.get("x-ati-request-id", "")
    checks += [
        Check(
            "bound-session-continues",
            (200, True, True),
            (continued_status, bool(continued_id), continued_id != first_id),
        ),
        Check("lab-start-rejects-existing-session", 403, probe.status("/lab/start", session)),
    ]
    return checks, session


def _response_contract_checks(probe: _Probe, session: dict[str, str]) -> list[Check]:
    """Responses are uncacheable, cookieless, HEAD-consistent and match the catalogue."""

    get_status, get_headers, get_body = probe.get("/lab/page/catalog", session)
    head_status, head_headers, head_body = probe.get(
        "/lab/page/catalog", session, method="HEAD"
    )
    _, landing_headers, _ = probe.get("/lab/page/landing", session)
    declared = {path: code for path, code in ROUTE_STATUS.items() if path != "/lab/start"}
    return [
        Check(
            "head-matches-get-without-body",
            (get_status, get_headers.get("content-type"), 0, True),
            (head_status, head_headers.get("content-type"), len(head_body), bool(get_body)),
        ),
        Check(
            "no-store-and-no-cookie",
            ("no-store", False),
            (landing_headers.get("cache-control"), "set-cookie" in landing_headers),
        ),
        Check(
            "every-catalogue-route-served-as-declared",
            declared,
            {path: probe.status(path, session) for path in declared},
        ),
    ]


def _origin_isolation_checks(probe: _Probe) -> list[Check]:
    """The origin observes only traffic the Worker vouches for."""

    direct_status, _, direct_body = probe.get("/lab/start", to_origin=True)
    health_status, _, health_body = probe.get("/healthz", to_origin=True)
    forged_context = {
        "X-ATI-Proxy-Client-ID": "hmac-sha256:" + "0" * 64,
        "X-ATI-UA-Provenance-Bucket": "scripted-http",
        "X-ATI-Proxy-Session-ID": "hmac-sha256:" + "0" * 64,
    }
    return [
        Check(
            "origin-refuses-direct-observation",
            (503, True),
            (direct_status, b"observation unavailable" in direct_body),
        ),
        Check(
            "origin-healthz-available",
            (200, True),
            (health_status, b'"ok"' in health_body),
        ),
        Check(
            "origin-refuses-forged-proxy-context",
            503,
            probe.status("/lab/start", forged_context, to_origin=True),
        ),
    ]


def _edge_reachability_check(probe: _Probe) -> Check:
    """Every declared executor family reaches the Worker; only the stdlib UA is banned."""

    stdlib_status, _, stdlib_body = probe.get("/healthz", {"User-Agent": _STDLIB_USER_AGENT})
    reachable = {
        family: probe.status("/healthz", {"User-Agent": agent})
        for family, agent in _FAMILY_USER_AGENTS.items()
    }
    return Check(
        "edge-reachability-by-executor-family",
        {"stdlib-denied-by-edge": True, **dict.fromkeys(_FAMILY_USER_AGENTS, 400)},
        {"stdlib-denied-by-edge": stdlib_status == 403 and b"1010" in stdlib_body, **reachable},
    )


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
