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
) -> dict[str, object]:
    return {
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


def test_cli_writes_the_four_preflight_inputs_for_a_ready_corpus(tmp_path: Path) -> None:
    code, output = cli(tmp_path, matched_design())

    assert code == 0
    for name in (
        "access.jsonl",
        "labels-by-session.json",
        "tasks-by-session.json",
        "collection-windows.json",
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
