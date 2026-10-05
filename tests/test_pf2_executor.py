from __future__ import annotations

import json
import random

import pytest

from observation_lab.pf2.catalogue import CATALOGUE_VERSION, PACING_VARIANTS
from observation_lab.pf2.executor import (
    EXECUTOR_ID,
    SCENARIO_VERSION,
    LabSessionError,
    SessionRecord,
    check_reachability,
    lowercase_headers,
    run_session,
)

MARKER = "owned-domain-2026-08-25-pf2-human-consented"


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
            response["x-ati-request-id"] = f"{len(self.calls):032x}"
        if path == "/lab/start" and not self.omit_session:
            # The Worker keeps its own casing on the header it adds itself.
            name = "x-ati-lab-session" if self.lowercase_session else "X-ATI-Lab-Session"
            response[name] = "ati1.payload.signature"
        return self.status_overrides.get(path, 200), lowercase_headers(response)


def run(edge: FakeEdge | None = None, **overrides: object) -> SessionRecord:
    options: dict[str, object] = {
        "marker": MARKER,
        "cohort": "automated",
        "task": "task-detail",
        "pacing_variant": "H1",
        "collection_window": "2026-09-26-block-1",
        "responder": edge or FakeEdge(),
        "host": "https://observe.example",
        "prompt": lambda _text: "",
        "sleep": lambda _seconds: None,
        "rng": random.Random(0),
    }
    options.update(overrides)
    if options["cohort"] == "human-consented":
        options.setdefault("participant", "p01")
    return run_session(**options)  # type: ignore[arg-type]


def test_session_carries_the_marker_everywhere_and_the_session_after_start() -> None:
    edge = FakeEdge()

    record = run(edge)

    assert record.excluded is False
    assert len(record.requests) == 7
    calls = [call for call in edge.calls if "/lab/" in call[1]]
    assert all(call[2]["X-ATI-Experiment-ID"] == MARKER for call in calls)
    assert "X-ATI-Lab-Session" not in calls[0][2]
    assert all("X-ATI-Lab-Session" in call[2] for call in calls[1:])


def test_label_follows_the_cohort_and_not_the_pacing_regime() -> None:
    # The same regime for both classes: pacing can never stand in for the label.
    for variant in ("H1", "H2", "H3"):
        automated = run(cohort="automated", pacing_variant=variant)
        human = run(cohort="human-consented", pacing_variant=variant)
        assert automated.controlled_automation is True
        assert human.controlled_automation is False
        assert automated.pacing_variant == human.pacing_variant == variant


def test_both_cohorts_share_executor_scenario_and_catalogue_versions() -> None:
    automated = run(cohort="automated").to_dict()
    human = run(cohort="human-consented").to_dict()

    for field in ("executor", "scenario_version", "catalogue_version"):
        assert automated[field] == human[field]
    assert automated["executor"] == EXECUTOR_ID
    assert automated["scenario_version"] == SCENARIO_VERSION
    assert automated["catalogue_version"] == CATALOGUE_VERSION


def test_a_consented_participant_cannot_follow_the_burst_regime() -> None:
    with pytest.raises(LabSessionError, match="consented participant can only follow"):
        run(cohort="human-consented", pacing_variant="burst")


def test_automated_cohort_may_follow_the_burst_regime() -> None:
    assert run(cohort="automated", pacing_variant="burst").excluded is False


def test_human_cohort_defers_every_request_to_the_participant() -> None:
    prompts: list[str] = []
    slept: list[float] = []

    record = run(
        cohort="human-consented",
        prompt=prompts.append,
        sleep=slept.append,
    )

    assert len(prompts) == len(record.requests) - 1
    assert "/lab/complete" in prompts[-1]
    assert slept == []


@pytest.mark.parametrize("variant", sorted(PACING_VARIANTS))
def test_automated_delays_stay_inside_the_declared_regime(variant: str) -> None:
    slept: list[float] = []

    record = run(cohort="automated", pacing_variant=variant, sleep=slept.append)

    low, high = PACING_VARIANTS[variant]
    assert len(slept) == len(record.requests) - 1
    assert all(low <= delay <= high for delay in slept)


def test_record_holds_only_approved_audit_fields_and_no_delay() -> None:
    slept: list[float] = []

    payload = run(sleep=slept.append).to_dict()

    assert set(payload) == {
        "marker",
        "cohort",
        "controlled_automation",
        "task",
        "pacing_variant",
        "collection_window",
        "participant",
        "executor",
        "scenario_version",
        "catalogue_version",
        "excluded",
        "exclusion_reason",
        "request_count",
        "requests",
    }
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
    assert "ati1." not in serialized
    assert "signature" not in serialized
    assert all(f"{delay}" not in serialized for delay in slept)
    for forbidden in ("user-agent", "cookie", "authorization", "remote_addr", "client_id"):
        assert forbidden not in serialized.lower()


def test_unexpected_status_stops_and_excludes_the_session() -> None:
    record = run(FakeEdge(status_overrides={"/lab/page/catalog": 403}))

    assert record.excluded is True
    assert "expected 200" in str(record.exclusion_reason)
    assert record.requests[-1]["path"] == "/lab/page/catalog"


def test_missing_signed_session_excludes_the_session() -> None:
    record = run(FakeEdge(omit_session=True))

    assert record.excluded is True
    assert record.exclusion_reason == "the edge issued no signed lab session"


def test_missing_request_identifier_excludes_the_session() -> None:
    record = run(FakeEdge(omit_request_id=True))

    assert record.excluded is True
    assert "opaque request identifier" in str(record.exclusion_reason)


@pytest.mark.parametrize("lowercase", [False, True])
def test_session_header_is_read_case_insensitively(lowercase: bool) -> None:
    record = run(FakeEdge(lowercase_session=lowercase))

    assert record.excluded is False
    assert len(record.requests) == 7


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"marker": "bad marker"}, "strict opaque marker format"),
        ({"marker": "-leading-dash"}, "strict opaque marker format"),
        ({"marker": "x" * 65}, "strict opaque marker format"),
        ({"cohort": "human"}, "cohort must be one of"),
        ({"task": "task-missing"}, "task must be one of"),
        ({"pacing_variant": "H9"}, "pacing_variant must be one of"),
        ({"collection_window": "  "}, "non-empty audit label"),
    ],
)
def test_invalid_inputs_are_refused(overrides: dict[str, str], message: str) -> None:
    with pytest.raises(LabSessionError, match=message):
        run(**overrides)


def test_reachability_check_rejects_an_edge_denial_before_the_worker() -> None:
    with pytest.raises(LabSessionError, match="blocked by a managed rule"):
        check_reachability("https://observe.example", lambda *_args: (403, {}))


def test_reachability_check_accepts_the_worker_route_refusal() -> None:
    check_reachability("https://observe.example", FakeEdge())


def test_reachability_check_rejects_an_unexpected_status() -> None:
    with pytest.raises(LabSessionError, match="unexpected reachability status 200"):
        check_reachability("https://observe.example", lambda *_args: (200, {}))


def test_executor_declares_a_user_agent_the_edge_does_not_ban() -> None:
    assert "urllib" not in EXECUTOR_ID.lower()
    assert "python" not in EXECUTOR_ID.lower()


def test_a_consented_session_records_its_participant_code() -> None:
    assert run(cohort="human-consented", participant="p07").to_dict()["participant"] == "p07"
    assert run(cohort="automated").to_dict()["participant"] is None


@pytest.mark.parametrize("code", [None, "", "alice", "P01", "p1", "p01 ", "p12345"])
def test_a_consented_session_needs_an_opaque_participant_code(code: str | None) -> None:
    with pytest.raises(LabSessionError, match="opaque participant code"):
        run(cohort="human-consented", participant=code)


def test_an_automated_session_never_carries_a_participant_code() -> None:
    with pytest.raises(LabSessionError, match="only a consented session"):
        run(cohort="automated", participant="p01")
