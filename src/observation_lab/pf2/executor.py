"""Run one controlled ATI-PF-2 laboratory session against the trusted edge.

This is the approved local executor the consent procedure requires, and it is meant to
run **both** cohorts. A standard browser cannot replay the transient signed session
header on its next navigation, so a carrier is needed; using the same carrier for the
automated and the consented human cohort keeps the executor, its User-Agent, its header
handling, the route plan and the pacing regimes identical across classes. The only thing
left to differ is who decides when each request happens — the behavior being measured.

The cohort is the label and the pacing variant is the regime; they are independent
inputs. An automated session may follow any regime, including the human ones, so no
regime can occur in one target class only. A consented human session is always
interactive and may follow only the human regimes.

The executor carries only the allowlisted campaign marker and the transient session
header, and records only the locally approved audit fields. It never writes the signed
session token, a raw address, a cookie, a query string, an Authorization value, a request
body, a full User-Agent, a delay, or any arbitrary header.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from observation_lab.pf2.catalogue import (
    CATALOGUE_VERSION,
    HUMAN_PACING_VARIANTS,
    PACING_VARIANTS,
    TASK_BRANCHES,
    plan_session,
)

SCENARIO_VERSION = "ati-pf2-1.0"
DEFAULT_HOST = "https://observe.ati-observation-lab.com"
EXECUTOR_ID = "ati-lab-executor/1.0"
"""Declared User-Agent and executor version, shared by both cohorts.

The edge's managed browser-integrity rule answers 403 (error 1010) for the Python
standard library's default User-Agent, so the executor must declare its own.
"""
COHORTS = ("automated", "human-consented")
_MARKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
# An operator-assigned code such as p01. It groups one person's sessions so evaluation can
# keep them on one side of a split; it must never be a name or any other identifier.
PARTICIPANT_CODE = re.compile(r"^p[0-9]{2,4}$")


class LabSessionError(RuntimeError):
    """Raised when a session cannot be run without breaking the collection contract."""


class Responder(Protocol):
    """Performs one request and returns status plus lowercased response headers."""

    def __call__(
        self, method: str, url: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, str]]: ...


@dataclass
class SessionRecord:
    """Locally approved audit fields for one controlled session."""

    marker: str
    cohort: str
    task: str
    pacing_variant: str
    collection_window: str
    participant: str | None = None
    executor: str = EXECUTOR_ID
    scenario_version: str = SCENARIO_VERSION
    catalogue_version: str = CATALOGUE_VERSION
    excluded: bool = False
    exclusion_reason: str | None = None
    requests: list[dict[str, object]] = field(default_factory=list)

    @property
    def controlled_automation(self) -> bool:
        return self.cohort == "automated"

    def to_dict(self) -> dict[str, object]:
        return {
            "marker": self.marker,
            "cohort": self.cohort,
            "controlled_automation": self.controlled_automation,
            "task": self.task,
            "pacing_variant": self.pacing_variant,
            "collection_window": self.collection_window,
            "participant": self.participant,
            "executor": self.executor,
            "scenario_version": self.scenario_version,
            "catalogue_version": self.catalogue_version,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "request_count": len(self.requests),
            "requests": self.requests,
        }


def lowercase_headers(headers: dict[str, str]) -> dict[str, str]:
    """Normalize header names.

    The Worker keeps its own header casing while the origin's correlation header
    arrives lowercased, so a case-sensitive read silently loses the request id.
    """

    return {name.lower(): value for name, value in headers.items()}


def urllib_responder(user_agent: str = EXECUTOR_ID) -> Responder:
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

    A client that trips the edge's managed rules is silently absent from the corpus
    instead of failing visibly, which biases composition by executor.
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


def _validate(
    *,
    marker: str,
    cohort: str,
    task: str,
    pacing_variant: str,
    collection_window: str,
    participant: str | None,
) -> None:
    if not _MARKER.fullmatch(marker):
        raise LabSessionError("marker must match the strict opaque marker format")
    if cohort not in COHORTS:
        raise LabSessionError(f"cohort must be one of {list(COHORTS)}")
    if task not in TASK_BRANCHES:
        raise LabSessionError(f"task must be one of {sorted(TASK_BRANCHES)}")
    if pacing_variant not in PACING_VARIANTS:
        raise LabSessionError(f"pacing_variant must be one of {sorted(PACING_VARIANTS)}")
    if cohort == "human-consented" and pacing_variant not in HUMAN_PACING_VARIANTS:
        raise LabSessionError(
            f"a consented participant can only follow {sorted(HUMAN_PACING_VARIANTS)}"
        )
    if not collection_window.strip():
        raise LabSessionError("collection_window must be a non-empty audit label")
    if cohort == "human-consented":
        if participant is None or not PARTICIPANT_CODE.fullmatch(participant):
            raise LabSessionError(
                "a consented session needs an opaque participant code such as p01"
            )
    elif participant is not None:
        raise LabSessionError("only a consented session carries a participant code")


def run_session(
    *,
    marker: str,
    cohort: str,
    task: str,
    pacing_variant: str,
    collection_window: str,
    responder: Responder,
    participant: str | None = None,
    host: str = DEFAULT_HOST,
    fetch_assets: bool = True,
    prompt: Callable[[str], object] = input,
    sleep: Callable[[float], object] = time.sleep,
    rng: random.Random | None = None,
) -> SessionRecord:
    """Execute one closed-catalogue session and return only approved audit fields."""

    _validate(
        marker=marker,
        cohort=cohort,
        task=task,
        pacing_variant=pacing_variant,
        collection_window=collection_window,
        participant=participant,
    )
    steps = plan_session(task, fetch_assets=fetch_assets)
    generator = rng or random.Random()
    low, high = PACING_VARIANTS[pacing_variant]
    record = SessionRecord(
        marker=marker,
        cohort=cohort,
        task=task,
        pacing_variant=pacing_variant,
        collection_window=collection_window,
        participant=participant,
    )
    session_header: str | None = None

    for sequence, step in enumerate(steps, start=1):
        if sequence > 1:
            if cohort == "human-consented":
                prompt(
                    f"  [{sequence}/{len(steps)}] press Enter when ready for {step.path}: "
                )
            else:
                sleep(generator.uniform(low, high))
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
    parser = argparse.ArgumentParser(
        prog="ati-lab-session",
        description="Run one controlled ATI-PF-2 session through the trusted edge.",
    )
    parser.add_argument("--marker", required=True, help="Allowlisted opaque marker.")
    parser.add_argument(
        "--cohort",
        required=True,
        choices=COHORTS,
        help="The label. human-consented runs interactively and needs a consent record.",
    )
    parser.add_argument("--task", required=True, choices=sorted(TASK_BRANCHES))
    parser.add_argument(
        "--pacing-variant",
        required=True,
        choices=sorted(PACING_VARIANTS),
        help="The regime. Use the H variants for both cohorts in a fitting corpus.",
    )
    parser.add_argument(
        "--collection-window",
        required=True,
        help="Coarse collection-order label used only for the temporal holdout.",
    )
    parser.add_argument(
        "--participant",
        help="Opaque code for a consenting participant, such as p01. Never a name.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--no-assets", action="store_true", help="Skip the two static asset requests."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.output.exists():
        print(f"error: refusing to overwrite {args.output}", file=sys.stderr)
        return 2
    responder = urllib_responder()
    try:
        check_reachability(args.host, responder)
        if args.cohort == "human-consented":
            low, high = PACING_VARIANTS[args.pacing_variant]
            print(
                f"Pacing guidance {args.pacing_variant}: pause about {low:g}-{high:g} s "
                "between steps, choosing each pause yourself. You may stop at any time."
            )
        record = run_session(
            marker=args.marker,
            cohort=args.cohort,
            task=args.task,
            pacing_variant=args.pacing_variant,
            collection_window=args.collection_window,
            responder=responder,
            participant=args.participant,
            host=args.host,
            fetch_assets=not args.no_assets,
        )
    except (LabSessionError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
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
