"""The live checker's logic, exercised against a simulated edge and origin.

The simulation encodes the documented contract. It proves the checker passes a
conforming deployment and names the exact check a drift breaks; the deployment itself is
only ever verified by running `ati-lab-perimeter` against production.
"""

from __future__ import annotations

from observation_lab.pf2.catalogue import ROUTE_STATUS
from observation_lab.pf2.perimeter import Check, run_checks

HOST = "https://observe.example"
ORIGIN = "https://origin.example"
MARKER = "owned-marker-a"
OTHER = "owned-marker-b"
ALLOWED = {MARKER, OTHER}


class SimulatedDeployment:
    def __init__(self, *, route_status: dict[str, int] | None = None,
                 ban_family_agent: str | None = None,
                 accept_query: bool = False) -> None:
        self.route_status = dict(ROUTE_STATUS, **(route_status or {}))
        self.ban_family_agent = ban_family_agent
        self.accept_query = accept_query
        self.issued = 0

    def __call__(self, method, url, headers, body):
        agent = headers.get("User-Agent", "")
        if agent.startswith("Python-urllib") or agent == self.ban_family_agent:
            return 403, {}, b"error code: 1010"
        if url.startswith(ORIGIN):
            path = url[len(ORIGIN):]
            if path == "/healthz":
                return 200, {}, b'{"status":"ok"}'
            return 503, {}, b'{"detail":"observation unavailable"}'
        path = url[len(HOST):]
        if method not in {"GET", "HEAD"}:
            return 400, {}, b""
        if ("?" in path and not self.accept_query) or "Cookie" in headers:
            return 400, {}, b""
        if "Authorization" in headers:
            return 400, {}, b""
        path = path.split("?", 1)[0]
        if path not in self.route_status:
            return 400, {}, b""
        marker = headers.get("X-ATI-Experiment-ID")
        if marker not in ALLOWED:
            return 403, {}, b""
        session = headers.get("X-ATI-Lab-Session")
        self.issued += 1
        response = {
            "x-ati-request-id": f"{self.issued:032x}",
            "cache-control": "no-store",
            "content-type": "text/html; charset=utf-8",
        }
        if path == "/lab/start":
            if session:
                return 403, {}, b""
            response["X-ATI-Lab-Session".lower()] = f"ati1.{marker}.sig"
            return 200, response, b"<main></main>"
        if session != f"ati1.{marker}.sig":
            return 403, {}, b""
        body_out = b"" if method == "HEAD" else b"<main></main>"
        return self.route_status[path], response, body_out


def results(deployment: SimulatedDeployment) -> dict[str, Check]:
    checks = run_checks(
        transport=deployment,
        marker=MARKER,
        other_marker=OTHER,
        host=HOST,
        origin=ORIGIN,
    )
    return {check.name: check for check in checks}


def test_a_conforming_deployment_passes_every_check() -> None:
    checks = results(SimulatedDeployment())

    failed = [name for name, check in checks.items() if not check.passed]
    assert failed == []
    assert len(checks) == 22
    # The controlled 404 is covered by the full-catalogue check, route by route.
    assert checks["every-catalogue-route-served-as-declared"].expected["/lab/missing"] == 404


def test_catalogue_drift_in_production_is_named_precisely() -> None:
    checks = results(SimulatedDeployment(route_status={"/lab/missing": 200}))

    failed = [name for name, check in checks.items() if not check.passed]
    assert failed == ["every-catalogue-route-served-as-declared"]


def test_an_edge_ban_on_a_declared_family_is_detected() -> None:
    checks = results(SimulatedDeployment(ban_family_agent="node"))

    failed = [name for name, check in checks.items() if not check.passed]
    assert failed == ["edge-reachability-by-executor-family"]


def test_a_worker_that_accepts_query_strings_is_detected() -> None:
    checks = results(SimulatedDeployment(accept_query=True))

    assert checks["query-string-refused"].passed is False
