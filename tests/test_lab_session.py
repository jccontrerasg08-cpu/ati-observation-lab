from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lab_session import (
    DEFAULT_USER_AGENT,
    SCENARIO_VERSION,
    LabSessionError,
    check_reachability,
    lowercase_headers,
    plan_session,
    run_session,
)

MARKER = "owned-domain-2026-08-25-pf2-human-consented"


def request_id(index: int) -> str:
    return f"{index:032x}"


class FakeEdge:
    """A trusted-edge stand-in that mirrors the deployed header casing."""

    def __init__(
        self,
        *,
        status_overrides: dict[str, int] | None = None,
        omit_session: bool = False,
        omit_request_id: bool = False,
        lowercase_session: bool = False,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.status_overrides = status_overrides or {}
        self.omit_session = omit_session
        self.omit_request_id = omit_request_id
        self.lowercase_session = lowercase_session

    def __call__(
        self, method: str, url: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, str]]:
        self.calls.append((method, url, dict(headers)))
        path = url.split("observe.example", 1)[-1]
        if path == "/healthz":
            return 400, {}
        response: dict[str, str] = {}
        if not self.omit_request_id:
            # The origin's correlation header reaches clients lowercased.
            response["x-ati-request-id"] = request_id(len(self.calls))
        if path == "/lab/start" and not self.omit_session:
            # The Worker keeps its own casing on the header it adds itself.
            name = "x-ati-lab-session" if self.lowercase_session else "X-ATI-Lab-Session"
            response[name] = "ati1.payload.signature"
        return self.status_overrides.get(path, 200), lowercase_headers(response)


def run(edge: FakeEdge, **kwargs: object) -> object:
    options: dict[str, object] = {
        "marker": MARKER,
        "task": "task-detail",
        "pacing_variant": "H1",
        "collection_window": "2026-09-26-block-1",
        "responder": edge,
        "host": "https://observe.example",
    }
    options.update(kwargs)
    return run_session(**options)  # type: ignore[arg-type]


def test_route_plan_follows_the_pf2_task_graph_and_ends_at_completion() -> None:
    steps = plan_session("task-detail", fetch_assets=True)

    assert [step.path for step in steps] == [
        "/lab/start",
        "/lab/page/landing",
        "/lab/assets/site.css",
        "/lab/page/catalog",
        "/lab/assets/pixel.svg",
        "/lab/page/detail",
        "/lab/complete",
    ]
    assert all(step.expected_status == 200 for step in steps)


def test_route_plan_never_includes_the_integrity_only_error_route() -> None:
    for task in ("task-detail", "task-related"):
        for assets in (True, False):
            paths = [step.path for step in plan_session(task, fetch_assets=assets)]
            # /lab/missing is rejected by the PF-2 preflight and would be a class proxy
            # if it appeared in only one cohort.
            assert "/lab/missing" not in paths
            assert paths[-1] == "/lab/complete"


def test_both_branches_produce_the_same_shape_for_either_cohort() -> None:
    detail = [step.path for step in plan_session("task-detail", fetch_assets=True)]
    related = [step.path for step in plan_session("task-related", fetch_assets=True)]

    assert len(detail) == len(related)
    assert detail.index("/lab/page/detail") == related.index("/lab/page/related")


def test_unknown_task_is_refused() -> None:
    with pytest.raises(LabSessionError, match="task must be one of"):
        plan_session("task-missing", fetch_assets=True)


def test_session_carries_the_marker_everywhere_and_the_session_after_start() -> None:
    edge = FakeEdge()

    record = run(edge)

    assert record.excluded is False
    assert len(record.requests) == 7
    lab_calls = [call for call in edge.calls if "/lab/" in call[1]]
    assert all(call[2]["X-ATI-Experiment-ID"] == MARKER for call in lab_calls)
    assert "X-ATI-Lab-Session" not in lab_calls[0][2]
    assert all("X-ATI-Lab-Session" in call[2] for call in lab_calls[1:])


def test_record_holds_only_approved_audit_fields() -> None:
    edge = FakeEdge()

    payload = run(edge).to_dict()

    assert set(payload) == {
        "marker",
        "task",
        "pacing_variant",
        "collection_window",
        "scenario_version",
        "controlled_automation",
        "excluded",
        "exclusion_reason",
        "request_count",
        "requests",
    }
    assert payload["scenario_version"] == SCENARIO_VERSION
    assert payload["controlled_automation"] is False
    for entry in payload["requests"]:
        assert set(entry) == {
            "sequence",
            "method",
            "path",
            "expected_status",
            "status",
            "request_id",
        }
    serialized = json.dumps(payload)
    # The signed session token, and anything resembling it, never reaches the record.
    assert "ati1." not in serialized
    assert "signature" not in serialized
    for forbidden in ("user-agent", "cookie", "authorization", "remote_addr", "client_id"):
        assert forbidden not in serialized.lower()


def test_scripted_variant_marks_the_session_as_controlled_automation() -> None:
    edge = FakeEdge()

    record = run(edge, pacing_variant="scripted", delay_seconds=0.0)

    assert record.controlled_automation is True
    assert record.pacing_variant == "scripted"


def test_human_variants_are_never_marked_as_controlled_automation() -> None:
    for variant in ("H1", "H2", "H3"):
        record = run(FakeEdge(), pacing_variant=variant)
        assert record.controlled_automation is False


def test_interactive_mode_defers_each_request_to_the_participant() -> None:
    edge = FakeEdge()
    prompts: list[str] = []

    record = run(edge, interactive=True, prompt=lambda text: prompts.append(text) or "")

    assert record.excluded is False
    # One prompt per request after the session-issuing first step.
    assert len(prompts) == len(record.requests) - 1
    assert "/lab/complete" in prompts[-1]


def test_interactive_mode_records_no_delay_vector() -> None:
    record = run(FakeEdge(), interactive=True, prompt=lambda _text: "")

    serialized = json.dumps(record.to_dict())
    assert "delay" not in serialized
    assert "timestamp" not in serialized
    assert "time" not in serialized


def test_scripted_mode_sleeps_between_requests_without_recording_the_delays() -> None:
    slept: list[float] = []

    record = run(
        FakeEdge(),
        pacing_variant="scripted",
        delay_seconds=0.25,
        sleep=slept.append,
    )

    assert slept == [0.25] * (len(record.requests) - 1)
    assert "0.25" not in json.dumps(record.to_dict())


def test_unexpected_status_stops_and_excludes_the_session() -> None:
    edge = FakeEdge(status_overrides={"/lab/page/catalog": 403})

    record = run(edge)

    assert record.excluded is True
    assert "expected 200" in str(record.exclusion_reason)
    # The run stops at the failing step rather than continuing the plan.
    assert record.requests[-1]["path"] == "/lab/page/catalog"
    assert all(entry["path"] != "/lab/complete" for entry in record.requests)


def test_missing_signed_session_excludes_the_session() -> None:
    record = run(FakeEdge(omit_session=True))

    assert record.excluded is True
    assert record.exclusion_reason == "the edge issued no signed lab session"


def test_missing_request_identifier_excludes_the_session() -> None:
    record = run(FakeEdge(omit_request_id=True))

    assert record.excluded is True
    assert "opaque request identifier" in str(record.exclusion_reason)


def test_session_header_is_read_case_insensitively() -> None:
    # Whichever casing the edge uses, the executor must still continue the session.
    for lowercase in (False, True):
        record = run(FakeEdge(lowercase_session=lowercase))
        assert record.excluded is False
        assert len(record.requests) == 7


def test_lowercase_headers_normalizes_every_name() -> None:
    assert lowercase_headers({"X-ATI-Request-ID": "a", "x-ati-lab-session": "b"}) == {
        "x-ati-request-id": "a",
        "x-ati-lab-session": "b",
    }


@pytest.mark.parametrize(
    "marker",
    ["", "bad marker", "-leading-dash", "x" * 65, "marker/with/slash"],
)
def test_invalid_marker_is_refused(marker: str) -> None:
    with pytest.raises(LabSessionError, match="strict opaque marker format"):
        run(FakeEdge(), marker=marker)


def test_invalid_pacing_variant_is_refused() -> None:
    with pytest.raises(LabSessionError, match="pacing_variant must be one of"):
        run(FakeEdge(), pacing_variant="H9")


def test_reachability_check_rejects_an_edge_denial_before_the_worker() -> None:
    def denied(method: str, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        return 403, {}

    with pytest.raises(LabSessionError, match="blocked by a managed rule"):
        check_reachability("https://observe.example", denied)


def test_reachability_check_accepts_the_worker_route_refusal() -> None:
    check_reachability("https://observe.example", FakeEdge())


def test_reachability_check_rejects_an_unexpected_status() -> None:
    def odd(method: str, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        return 200, {}

    with pytest.raises(LabSessionError, match="unexpected reachability status 200"):
        check_reachability("https://observe.example", odd)


def test_executor_declares_a_user_agent_that_is_not_the_stdlib_default() -> None:
    # The edge's managed rule answers 403 for the standard library's default agent.
    assert "urllib" not in DEFAULT_USER_AGENT.lower()
    assert "python" not in DEFAULT_USER_AGENT.lower()
