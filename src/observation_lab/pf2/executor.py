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
import math
import random
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from observation_lab.pf2.catalogue import (
    CATALOGUE_VERSION,
    HUMAN_PACING_VARIANTS,
    PACING_VARIANTS,
    PAGE_CONTENT,
    PF2_ROUTE_CATEGORIES,
    READING_LOAD,
    TASK_BRANCHES,
    Step,
    plan_session,
)

SCENARIO_VERSION = "ati-pf2-1.0"
"""The keypress scenario: every step, assets included, waits for a pause or a keypress."""
READING_SCENARIO_VERSION = "ati-pf2-1.1"
"""The reading scenario: assets follow their page at once, and a participant reads each page
before moving on."""
SCENARIO_VERSIONS = (SCENARIO_VERSION, READING_SCENARIO_VERSION)
DEFAULT_HOST = "https://observe.ati-observation-lab.com"
EXECUTOR_ID = "ati-lab-executor/1.0"
"""Declared User-Agent and executor version, shared by both cohorts.

The edge's managed browser-integrity rule answers 403 (error 1010) for the Python
standard library's default User-Agent, so the executor must declare its own.
"""
COHORTS = ("automated", "human-consented")
AUTOMATION_PACINGS = ("timer", "imitate", "imitate-content")
"""How the automated cohort chooses its pauses (spec 003).

`timer` draws each pause uniformly inside the regime. `imitate` draws person-like pauses
from a persona the session samples for itself, and places them without regard to the
page. `imitate-content` also stretches each pause by the reading load of the page it
leaves, as a reading person would. Both mirror the adversaries of ATI's `pf2-simulate`.
"""
LOAD_FACTOR: MappingProxyType[str, float] = MappingProxyType(
    {"short": 0.8, "long": 1.6}
)
"""How much a page's reading load stretches a reader's pause; pinned to ATI's simulator."""
_PERSONAL_PACE_SPREAD = 0.25
_IRREGULARITY = (0.25, 0.55)
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
    automation_pacing: str | None = None
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
            "automation_pacing": self.automation_pacing,
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
    scenario_version: str = SCENARIO_VERSION,
    automation_pacing: str | None = None,
) -> None:
    if automation_pacing is not None:
        if cohort != "automated":
            raise LabSessionError(
                "automation_pacing applies to the automated cohort only"
            )
        if automation_pacing not in AUTOMATION_PACINGS:
            raise LabSessionError(
                f"automation_pacing must be one of {list(AUTOMATION_PACINGS)}"
            )
        if (
            automation_pacing == "imitate-content"
            and scenario_version != READING_SCENARIO_VERSION
        ):
            raise LabSessionError(
                "imitate-content needs the reading scenario, whose pages carry text"
            )
    if scenario_version not in SCENARIO_VERSIONS:
        raise LabSessionError(f"scenario_version must be one of {list(SCENARIO_VERSIONS)}")
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
    scenario_version: str = SCENARIO_VERSION,
    automation_pacing: str | None = None,
    prompt: Callable[[str], object] = input,
    display: Callable[[str], object] = print,
    sleep: Callable[[float], object] | None = None,
    rng: random.Random | None = None,
) -> SessionRecord:
    """Execute one closed-catalogue session and return only approved audit fields.

    In the reading scenario an asset is fetched right after its page, as a browser would,
    for both cohorts; and a consenting participant is shown each page's text and decides
    when to move on. The text shown is the catalogue's, which is also what the origin
    serves.
    """

    _validate(
        marker=marker,
        cohort=cohort,
        task=task,
        pacing_variant=pacing_variant,
        collection_window=collection_window,
        participant=participant,
        scenario_version=scenario_version,
        automation_pacing=automation_pacing,
    )
    steps = plan_session(task, fetch_assets=fetch_assets)
    reading = scenario_version == READING_SCENARIO_VERSION
    human = cohort == "human-consented"
    generator = rng or random.Random()
    sleep = sleep or time.sleep
    low, high = PACING_VARIANTS[pacing_variant]
    pacing = None if human else (automation_pacing or "timer")
    pause = (
        _Pacer(pacing, steps, generator, low, high, reading=reading) if pacing else None
    )
    record = SessionRecord(
        marker=marker,
        cohort=cohort,
        task=task,
        pacing_variant=pacing_variant,
        collection_window=collection_window,
        participant=participant,
        scenario_version=scenario_version,
        automation_pacing=pacing,
    )
    session_header: str | None = None

    page: str | None = None
    for sequence, step in enumerate(steps, start=1):
        is_asset = PF2_ROUTE_CATEGORIES[step.path] == "asset"
        if sequence > 1 and not (reading and is_asset):
            if human and reading:
                assert page is not None
                display(_page_text(page))
                prompt("  Press Enter when you have read this page: ")
            elif human:
                prompt(
                    f"  [{sequence}/{len(steps)}] press Enter when ready for {step.path}: "
                )
            else:
                assert pause is not None
                sleep(pause.next(page))
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
        if not is_asset:
            page = step.path
    if human and reading and page is not None:
        display(_page_text(page))
    return record


class _Pacer:
    """Choose each automated pause, before navigations, for one session."""

    def __init__(
        self,
        pacing: str,
        steps: Sequence[Step],
        generator: random.Random,
        low: float,
        high: float,
        *,
        reading: bool,
    ) -> None:
        self._pacing = pacing
        self._generator = generator
        self._low, self._high = low, high
        self._reading = reading
        self._misplaced: list[str] = []
        if pacing == "timer":
            # The timer draws nothing else, so its pauses are exactly those of before.
            return
        # A persona of the session's own: never a participant's traits.
        self._pace = math.exp(generator.gauss(0.0, _PERSONAL_PACE_SPREAD))
        self._irregularity = generator.uniform(*_IRREGULARITY)
        # The content-blind mimic spends the session's loads in a shuffled order.
        pages = [
            str(step.path)
            for step in steps
            if PF2_ROUTE_CATEGORIES[str(step.path)] != "asset"
        ]
        self._misplaced = [READING_LOAD[path] for path in pages[:-1]]
        generator.shuffle(self._misplaced)

    def next(self, page: str | None) -> float:
        if self._pacing == "timer":
            return self._generator.uniform(self._low, self._high)
        middle = self._pace * (self._low + self._high) / 2
        pause = math.exp(self._generator.gauss(math.log(middle), self._irregularity))
        if not self._reading:
            return pause
        if self._pacing == "imitate-content":
            assert page is not None
            return pause * LOAD_FACTOR[READING_LOAD[page]]
        load = self._misplaced.pop(0) if self._misplaced else "short"
        return pause * LOAD_FACTOR[load]


def _page_text(path: str) -> str:
    content = PAGE_CONTENT[path]
    paragraphs = [textwrap.fill(paragraph, width=78) for paragraph in content.paragraphs]
    return "\n\n".join(["", f"== {content.title} ==", *paragraphs, ""])


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
        "--scenario-version",
        choices=SCENARIO_VERSIONS,
        default=SCENARIO_VERSION,
        help="ati-pf2-1.1 shows a participant each page and fetches assets with their page.",
    )
    parser.add_argument(
        "--automation-pacing",
        choices=AUTOMATION_PACINGS,
        help=(
            "Automated cohort only: timer (default), imitate (person-like pauses placed "
            "without regard to the page) or imitate-content (placed by reading load)."
        ),
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
            scenario_version=args.scenario_version,
            automation_pacing=args.automation_pacing,
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
