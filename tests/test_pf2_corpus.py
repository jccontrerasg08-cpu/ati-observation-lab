from __future__ import annotations

import json
from pathlib import Path

import pytest

from observation_lab.pf2.corpus import (
    CorpusError,
    build,
    load_exported_rows,
    load_session_records,
    main,
)

PLAN = (
    "/lab/start",
    "/lab/page/landing",
    "/lab/page/catalog",
    "/lab/page/detail",
    "/lab/complete",
)


def session_id(index: int) -> str:
    return "hmac-sha256:" + f"{index:064x}"


def request_id(session: int, step: int) -> str:
    return f"{session:016x}{step:016x}"


def record(
    index: int,
    *,
    automated: bool,
    pacing: str = "H1",
    window: str = "w1",
    executor: str = "ati-lab-executor/1.0",
    excluded: bool = False,
    participant: str | None = None,
) -> dict[str, object]:
    return {
        "participant": participant,
        "marker": "owned-domain-2026-08-25-pf2-human-consented",
        "cohort": "automated" if automated else "human-consented",
        "controlled_automation": automated,
        "task": "task-detail",
        "pacing_variant": pacing,
        "collection_window": window,
        "executor": executor,
        "scenario_version": "ati-pf2-1.0",
        "catalogue_version": "ati-pf2-catalogue-1",
        "excluded": excluded,
        "exclusion_reason": "stopped" if excluded else None,
        "requests": [
            {
                "sequence": step + 1,
                "method": "GET",
                "path": path,
                "expected_status": 200,
                "status": 200,
                "request_id": request_id(index, step),
            }
            for step, path in enumerate(PLAN)
        ],
    }


def exported_row(index: int, step: int, *, path: str | None = None) -> dict[str, object]:
    return {
        "request_id": request_id(index, step),
        "session_id": session_id(index),
        "request_method": "GET",
        "request_uri": path or PLAN[step],
        "status": 200,
        "time_iso8601": f"2026-09-26T10:{index:02d}:{step:02d}+00:00",
        # Fields the corpus must never carry forward.
        "client_id": "blake2b:" + "0" * 32,
        "ua_provenance_bucket": "other",
        "ati_campaign_id": "owned-domain-2026-08-25-pf2-human-consented",
    }


def write_case(
    tmp_path: Path,
    records: list[dict[str, object]],
    rows: list[dict[str, object]] | None = None,
) -> tuple[Path, Path]:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    for position, payload in enumerate(records):
        (session_dir / f"session-{position:02d}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    if rows is None:
        rows = [
            exported_row(index, step)
            for index in range(len(records))
            for step in range(len(PLAN))
        ]
    export = tmp_path / "exported.jsonl"
    export.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return session_dir, export


def matched_design() -> list[dict[str, object]]:
    """Both cohorts through one executor, sharing every pacing regime and window."""

    records = []
    for index in range(12):
        records.append(
            record(
                index,
                automated=index % 2 == 0,
                pacing=("H1", "H2", "H3")[(index // 2) % 3],
                window="w1" if index < 6 else "w2",
                participant=None if index % 2 == 0 else f"p{index % 3:02d}",
            )
        )
    return records


def built(tmp_path: Path, records: list[dict[str, object]], rows=None):
    session_dir, export = write_case(tmp_path, records, rows)
    return build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )


def test_matched_executor_design_is_fitting_ready(tmp_path: Path) -> None:
    corpus, result = built(tmp_path, matched_design())

    summary = result["summary"]
    assert summary["fitting_ready"] is True
    assert summary["fitting_blockers"] == []
    assert summary["class_confounded_audit_dimensions"] == {}
    assert summary["reconciled_sessions"] == 12
    assert summary["automated_sessions"] == summary["human_assisted_sessions"] == 6
    assert len(corpus) == 12 * len(PLAN)


def test_a_pacing_regime_used_by_one_class_only_blocks_fitting(tmp_path: Path) -> None:
    records = matched_design()
    for payload in records:
        if payload["controlled_automation"]:
            payload["pacing_variant"] = "burst"

    _, result = built(tmp_path, records)

    summary = result["summary"]
    assert summary["fitting_ready"] is False
    assert "burst" in summary["class_confounded_audit_dimensions"]["pacing_variant"]
    assert any("pacing_variant" in blocker for blocker in summary["fitting_blockers"])


def test_an_executor_used_by_one_class_only_blocks_fitting(tmp_path: Path) -> None:
    records = matched_design()
    for payload in records:
        if payload["controlled_automation"]:
            payload["executor"] = "curl/8.5.0"

    _, result = built(tmp_path, records)

    confounded = result["summary"]["class_confounded_audit_dimensions"]
    assert set(confounded["executor"]) == {"curl/8.5.0", "ati-lab-executor/1.0"}


def test_single_class_corpus_is_not_fitting_ready(tmp_path: Path) -> None:
    records = [record(index, automated=True) for index in range(3)]

    _, result = built(tmp_path, records)

    summary = result["summary"]
    assert summary["fitting_ready"] is False
    assert summary["fitting_blockers"] == ["corpus has one target class"]


def test_corpus_rows_carry_only_the_fields_the_preflight_reads(tmp_path: Path) -> None:
    corpus, _ = built(tmp_path, matched_design())

    for row in corpus:
        assert set(row) == {
            "session_id",
            "request_uri",
            "request_method",
            "status",
            "time_iso8601",
        }
    serialized = json.dumps(corpus)
    for prohibited in ("client_id", "ua_provenance_bucket", "ati_campaign_id", "request_id"):
        assert prohibited not in serialized


def test_labels_come_from_the_recorded_cohort_not_from_behaviour(tmp_path: Path) -> None:
    # Byte-identical routes and pacing; only the recorded cohort differs.
    records = [
        record(0, automated=True, window="w1"),
        record(1, automated=False, window="w1"),
    ]

    _, result = built(tmp_path, records)

    assert sorted(result["labels"].values()) == [False, True]


def test_cohort_that_disagrees_with_the_label_fails_closed(tmp_path: Path) -> None:
    payload = record(0, automated=True)
    payload["cohort"] = "human-consented"
    session_dir, _ = write_case(tmp_path, [payload])

    with pytest.raises(CorpusError, match="cohort disagrees"):
        load_session_records(sorted(session_dir.glob("*.json")))


def test_session_excluded_by_the_executor_is_counted_not_dropped(tmp_path: Path) -> None:
    records = [record(0, automated=True), record(1, automated=False, excluded=True)]

    _, result = built(tmp_path, records)

    summary = result["summary"]
    assert summary["reconciled_sessions"] == 1
    assert summary["excluded_sessions"] == [{"source": "session-01.json", "reason": "stopped"}]


def test_identifier_missing_from_the_export_excludes_the_session(tmp_path: Path) -> None:
    records = [record(0, automated=True), record(1, automated=False)]
    rows = [exported_row(0, step) for step in range(len(PLAN))]

    _, result = built(tmp_path, records, rows)

    summary = result["summary"]
    assert summary["reconciled_sessions"] == 1
    assert summary["unmatched_request_ids"] == len(PLAN)
    assert summary["excluded_sessions"][0]["reason"] == "request identifier missing from export"


def test_rows_spanning_two_sessions_exclude_the_session(tmp_path: Path) -> None:
    rows = [exported_row(0, step) for step in range(len(PLAN))]
    rows[2]["session_id"] = session_id(99)

    _, result = built(tmp_path, [record(0, automated=True)], rows)

    assert result["summary"]["excluded_sessions"][0]["reason"] == (
        "rows span more than one session"
    )


def test_an_ineligible_route_excludes_the_session(tmp_path: Path) -> None:
    rows = [exported_row(0, step) for step in range(len(PLAN))]
    rows[-1] = exported_row(0, len(PLAN) - 1, path="/lab/missing")

    _, result = built(tmp_path, [record(0, automated=True)], rows)

    assert result["summary"]["excluded_sessions"][0]["reason"] == (
        "row is not an ATI-PF-2-eligible route"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_uri", "/lab/page/related"),
        ("request_method", "HEAD"),
        ("status", 404),
    ],
)
def test_a_joined_row_that_disagrees_with_the_local_request_excludes_the_session(
    tmp_path: Path, field: str, value: object
) -> None:
    # Every value here is individually valid; only the pairing is wrong.
    rows = [exported_row(0, step) for step in range(len(PLAN))]
    rows[3][field] = value

    _, result = built(tmp_path, [record(0, automated=True)], rows)

    summary = result["summary"]
    assert summary["reconciled_sessions"] == 0
    assert summary["excluded_sessions"][0]["reason"] == (
        "joined row disagrees with the local request"
    )


def test_a_local_request_with_an_unexpected_status_excludes_the_session(
    tmp_path: Path,
) -> None:
    payload = record(0, automated=True)
    payload["requests"][2]["status"] = 403
    rows = [exported_row(0, step) for step in range(len(PLAN))]
    rows[2]["status"] = 403

    _, result = built(tmp_path, [payload], rows)

    assert result["summary"]["excluded_sessions"][0]["reason"] == (
        "local request did not receive its expected status"
    )


@pytest.mark.parametrize(
    "dimension", ["pacing_variant", "executor", "scenario_version", "catalogue_version"]
)
@pytest.mark.parametrize("value", [None, "", "  "])
def test_a_missing_audit_dimension_fails_closed(
    tmp_path: Path, dimension: str, value: object
) -> None:
    # Defaulting it would make both classes share one invented value and hide a confound.
    payload = record(0, automated=True)
    if value is None:
        del payload[dimension]
    else:
        payload[dimension] = value
    session_dir, _ = write_case(tmp_path, [payload])

    with pytest.raises(CorpusError, match=f"must record '{dimension}'"):
        load_session_records(sorted(session_dir.glob("*.json")))


def test_a_request_entry_that_is_not_an_object_fails_closed(tmp_path: Path) -> None:
    payload = record(0, automated=True)
    payload["requests"].append("not-a-request")
    session_dir, _ = write_case(tmp_path, [payload])

    with pytest.raises(CorpusError, match="list of request objects"):
        load_session_records(sorted(session_dir.glob("*.json")))


@pytest.mark.parametrize("line", ["[1, 2]", '"text"', "7", "null"])
def test_a_non_object_export_line_fails_closed(tmp_path: Path, line: str) -> None:
    export = tmp_path / "exported.jsonl"
    export.write_text(json.dumps(exported_row(0, 0)) + "\n" + line + "\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="line 2 is not a JSON object"):
        load_exported_rows(export)


def test_cli_reports_a_non_object_export_line_without_a_traceback(
    tmp_path: Path, capsys
) -> None:
    session_dir, export = write_case(tmp_path, matched_design())
    export.write_text("[]\n", encoding="utf-8")

    code = main(
        [
            "--session-dir",
            str(session_dir),
            "--exported",
            str(export),
            "--output-dir",
            str(tmp_path / "corpus"),
        ]
    )

    assert code == 2
    assert "is not a JSON object" in capsys.readouterr().err


def test_duplicate_request_identifier_in_the_export_fails_closed(tmp_path: Path) -> None:
    export = tmp_path / "exported.jsonl"
    row = json.dumps(exported_row(0, 0))
    export.write_text(row + "\n" + row + "\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="duplicated request identifiers"):
        load_exported_rows(export)


def test_transparent_session_identifier_fails_closed(tmp_path: Path) -> None:
    row = exported_row(0, 0)
    row["session_id"] = "192.0.2.10"
    export = tmp_path / "exported.jsonl"
    export.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="invalid session pseudonym"):
        load_exported_rows(export)


def test_export_missing_a_required_field_fails_closed(tmp_path: Path) -> None:
    row = exported_row(0, 0)
    del row["time_iso8601"]
    export = tmp_path / "exported.jsonl"
    export.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="missing 'time_iso8601'"):
        load_exported_rows(export)


def test_non_boolean_label_fails_closed(tmp_path: Path) -> None:
    payload = record(0, automated=True)
    payload["controlled_automation"] = "true"
    session_dir, _ = write_case(tmp_path, [payload])

    with pytest.raises(CorpusError, match="must be a boolean"):
        load_session_records(sorted(session_dir.glob("*.json")))


def cli(tmp_path: Path, records, *extra: str) -> tuple[int, Path]:
    session_dir, export = write_case(tmp_path, records)
    output = tmp_path / "corpus"
    code = main(
        [
            "--session-dir",
            str(session_dir),
            "--exported",
            str(export),
            "--output-dir",
            str(output),
            *extra,
        ]
    )
    return code, output


def test_cli_writes_the_preflight_inputs_for_a_ready_corpus(tmp_path: Path) -> None:
    code, output = cli(tmp_path, matched_design())

    assert code == 0
    for name in (
        "access.jsonl",
        "labels-by-session.json",
        "tasks-by-session.json",
        "collection-windows.json",
        "groups-by-session.json",
        "corpus-summary.json",
    ):
        assert (output / name).exists()


def test_cli_refuses_a_corpus_that_is_not_fitting_ready(tmp_path: Path, capsys) -> None:
    code, output = cli(tmp_path, [record(index, automated=True) for index in range(2)])

    assert code == 2
    assert "not fitting-ready" in capsys.readouterr().err
    assert not output.exists()


def test_cli_diagnostic_mode_writes_a_corpus_that_is_not_ready(tmp_path: Path) -> None:
    code, output = cli(
        tmp_path, [record(index, automated=True) for index in range(2)], "--diagnostic"
    )

    assert code == 0
    summary = json.loads((output / "corpus-summary.json").read_text())
    assert summary["fitting_ready"] is False


def test_cli_refuses_an_existing_output_directory(tmp_path: Path, capsys) -> None:
    (tmp_path / "corpus").mkdir()

    code, _ = cli(tmp_path, matched_design())

    assert code == 2
    assert "refusing to overwrite" in capsys.readouterr().err


def test_groups_keep_a_participant_together_and_automated_sessions_apart(
    tmp_path: Path,
) -> None:
    _, result = built(tmp_path, matched_design())

    groups, labels = result["groups"], result["labels"]
    human = {groups[session] for session, automated in labels.items() if not automated}
    automated = [groups[session] for session, is_automated in labels.items() if is_automated]
    assert human == {"p00", "p01", "p02"}
    assert len(set(automated)) == len(automated)
    assert result["summary"]["participants"] == 3


def test_a_consented_session_without_a_participant_code_blocks_fitting(
    tmp_path: Path,
) -> None:
    records = matched_design()
    records[1]["participant"] = None

    _, result = built(tmp_path, records)

    assert result["summary"]["fitting_ready"] is False
    assert "1 consented session(s) carry no participant code" in result["summary"][
        "fitting_blockers"
    ]


def test_a_single_participant_cannot_be_held_out_and_still_trained_on(tmp_path: Path) -> None:
    records = matched_design()
    for payload in records:
        if not payload["controlled_automation"]:
            payload["participant"] = "p01"

    _, result = built(tmp_path, records)

    assert "fewer than two coded participants in the consented cohort" in result["summary"][
        "fitting_blockers"
    ]


def test_a_participant_value_that_is_not_an_opaque_code_fails_closed(tmp_path: Path) -> None:
    records = matched_design()
    records[1]["participant"] = "Alice"

    with pytest.raises(CorpusError, match="opaque code"):
        built(tmp_path, records)
