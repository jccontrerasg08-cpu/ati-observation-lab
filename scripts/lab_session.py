"""Run one controlled ATI-PF-2 laboratory session against the trusted edge.

This is the approved local executor the consent procedure requires. A standard browser
cannot replay the transient signed session header on its next navigation, so a carrier is
needed; this script carries only the allowlisted campaign marker and that transient
header, and it records only the locally approved audit fields.

In `interactive` mode the participant decides when each request happens and which branch
to take, so pacing and navigation come from the person and not from this script. Only the
declared pacing variant code is recorded, never a delay vector.

It never writes the signed session token, a raw address, a cookie, a query string, an
Authorization value, a request body, a full User-Agent, or any arbitrary header.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SCENARIO_VERSION = "ati-pf2-1.0"
DEFAULT_HOST = "https://observe.ati-observation-lab.com"
# The edge's managed browser-integrity rule answers 403 (error 1010) for the Python
# standard library's default User-Agent, so the executor must declare its own.
DEFAULT_USER_AGENT = "ati-lab-executor/1.0"
_MARKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_PACING_VARIANTS = ("H1", "H2", "H3", "scripted")
_TASK_BRANCH = {
    "task-detail": "/lab/page/detail",
    "task-related": "/lab/page/related",
}
# The ATI-PF-2 shared task graph. `/lab/missing` is deliberately absent: it is a
# protocol-integrity control that the PF-2 preflight rejects as an ineligible route, and
# a route category present in only one cohort would act as a class proxy.
_CLOSED_CATALOGUE = frozenset(
    {
        "/lab/start",
        "/lab/page/landing",
        "/lab/page/catalog",
        "/lab/page/detail",
        "/lab/page/related",
        "/lab/complete",
        "/lab/assets/site.css",
        "/lab/assets/pixel.svg",
    }
)


class LabSessionError(RuntimeError):
    """Raised when a session cannot be run without breaking the privacy contract."""


class Responder(Protocol):
    """Performs one request and returns status plus case-insensitive headers."""

    def __call__(
        self, method: str, url: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, str]]: ...


@dataclass(frozen=True, slots=True)
class Step:
    """One planned request in the closed catalogue."""

    method: str
    path: str
    expected_status: int = 200


@dataclass
class SessionRecord:
    """Locally approved audit fields for one controlled session."""

    marker: str
    task: str
    pacing_variant: str
    collection_window: str
    scenario_version: str = SCENARIO_VERSION
    controlled_automation: bool = False
    excluded: bool = False
    exclusion_reason: str | None = None
    requests: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "marker": self.marker,
            "task": self.task,
            "pacing_variant": self.pacing_variant,
            "collection_window": self.collection_window,
            "scenario_version": self.scenario_version,
            "controlled_automation": self.controlled_automation,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "request_count": len(self.requests),
            "requests": self.requests,
        }


def plan_session(task: str, *, fetch_assets: bool) -> tuple[Step, ...]:
    """Build the ATI-PF-2 route plan, identical in shape for every cohort."""

    branch = _TASK_BRANCH.get(task)
    if branch is None:
        raise LabSessionError(f"task must be one of {sorted(_TASK_BRANCH)}")
    steps = [Step("GET", "/lab/start"), Step("GET", "/lab/page/landing")]
    if fetch_assets:
        steps.append(Step("GET", "/lab/assets/site.css"))
    steps.append(Step("GET", "/lab/page/catalog"))
    if fetch_assets:
        steps.append(Step("GET", "/lab/assets/pixel.svg"))
    steps.extend([Step("GET", branch), Step("GET", "/lab/complete")])
    for step in steps:
        if step.path not in _CLOSED_CATALOGUE:
            raise LabSessionError(f"route outside the closed catalogue: {step.path}")
    return tuple(steps)


def lowercase_headers(headers: dict[str, str]) -> dict[str, str]:
    """Normalize header names.

    The Worker keeps its own header casing while the origin's correlation header
    arrives lowercased, so a case-sensitive read silently loses the request id.
    """

    return {name.lower(): value for name, value in headers.items()}


def urllib_responder(user_agent: str) -> Responder:
    """Build a standard-library responder that always declares a User-Agent."""

    def respond(
        method: str, url: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, str]]:
        request = urllib.request.Request(url, method=method)
        for name, value in {**headers, "User-Agent": user_agent}.items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, lowercase_headers(dict(response.headers))
        except urllib.error.HTTPError as error:
            return error.code, lowercase_headers(dict(error.headers))

    return respond


def check_reachability(host: str, responder: Responder) -> None:
    """Confirm this executor reaches the Worker rather than an edge denial.

    A family whose client trips the edge's managed rules is silently absent from the
    corpus instead of failing visibly, which biases composition by executor family.
    """

    status, _ = responder("GET", f"{host}/healthz", {})
    if status == 403:
        raise LabSessionError(
            "the edge refused this executor before the Worker ran; its User-Agent is "
            "blocked by a managed rule, so the session would never be observed"
        )
    if status != 400:
        raise LabSessionError(
            f"unexpected reachability status {status}; expected 400 from the Worker "
            "for a route outside the closed catalogue"
        )


def _confirm(prompt: str) -> str:
    return input(prompt)


def run_session(
    *,
    marker: str,
    task: str,
    pacing_variant: str,
    collection_window: str,
    responder: Responder,
    host: str = DEFAULT_HOST,
    fetch_assets: bool = True,
    delay_seconds: float = 0.0,
    interactive: bool = False,
    prompt: object = _confirm,
    sleep: object = time.sleep,
) -> SessionRecord:
    """Execute one closed-catalogue session and return only approved audit fields."""

    if not _MARKER.fullmatch(marker):
        raise LabSessionError("marker must match the strict opaque marker format")
    if pacing_variant not in _PACING_VARIANTS:
        raise LabSessionError(f"pacing_variant must be one of {list(_PACING_VARIANTS)}")
    if not collection_window.strip():
        raise LabSessionError("collection_window must be a non-empty audit label")
    steps = plan_session(task, fetch_assets=fetch_assets)
    record = SessionRecord(
        marker=marker,
        task=task,
        pacing_variant=pacing_variant,
        collection_window=collection_window,
        controlled_automation=pacing_variant == "scripted",
    )
    session_header: str | None = None

    for sequence, step in enumerate(steps, start=1):
        if sequence > 1:
            if interactive:
                prompt(f"  [{sequence}/{len(steps)}] press Enter for {step.path}: ")  # type: ignore[operator]
            elif delay_seconds:
                sleep(delay_seconds)  # type: ignore[operator]
        headers = {"X-ATI-Experiment-ID": marker}
        if session_header is not None:
            headers["X-ATI-Lab-Session"] = session_header
        status, response_headers = responder(step.method, f"{host}{step.path}", headers)
        request_id = response_headers.get("x-ati-request-id", "")
        record.requests.append(
            {
                "sequence": sequence,
                "method": step.method,
                "path": step.path,
                "expected_status": step.expected_status,
                "status": status,
                "request_id": request_id,
            }
        )
        if status != step.expected_status:
            record.excluded = True
            record.exclusion_reason = (
                f"step {sequence} returned {status}, expected {step.expected_status}"
            )
            return record
        if not _REQUEST_ID.fullmatch(request_id):
            record.excluded = True
            record.exclusion_reason = (
                f"step {sequence} returned no usable opaque request identifier"
            )
            return record
        if step.path == "/lab/start":
            session_header = response_headers.get("x-ati-lab-session")
            if not session_header:
                record.excluded = True
                record.exclusion_reason = "the edge issued no signed lab session"
                return record
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker", required=True, help="Allowlisted opaque marker.")
    parser.add_argument("--task", required=True, choices=sorted(_TASK_BRANCH))
    parser.add_argument(
        "--pacing-variant",
        required=True,
        choices=list(_PACING_VARIANTS),
        help="Declared pacing variant code; 'scripted' marks an automated family.",
    )
    parser.add_argument(
        "--mode",
        default="interactive",
        choices=["interactive", "scripted"],
        help="interactive lets the participant decide when each request happens.",
    )
    parser.add_argument(
        "--collection-window",
        required=True,
        help="Coarse collection-order label used only for the temporal holdout.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--delay-seconds", type=float, default=0.3)
    parser.add_argument(
        "--no-assets", action="store_true", help="Skip the two static asset requests."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.output.exists():
        print(f"error: refusing to overwrite {args.output}", file=sys.stderr)
        return 2
    responder = urllib_responder(args.user_agent)
    try:
        check_reachability(args.host, responder)
        record = run_session(
            marker=args.marker,
            task=args.task,
            pacing_variant=args.pacing_variant,
            collection_window=args.collection_window,
            responder=responder,
            host=args.host,
            fetch_assets=not args.no_assets,
            delay_seconds=args.delay_seconds,
            interactive=args.mode == "interactive",
        )
    except (LabSessionError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    args.output.write_text(
        json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "excluded": record.excluded,
                "exclusion_reason": record.exclusion_reason,
                "request_count": len(record.requests),
            },
            sort_keys=True,
        )
    )
    return 1 if record.excluded else 0


if __name__ == "__main__":
    raise SystemExit(main())
