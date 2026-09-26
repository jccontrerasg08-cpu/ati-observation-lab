from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_pf2_corpus import (
    CorpusError,
    build,
    load_exported_rows,
    load_session_records,
    main,
)

PLAN = (
    ("GET", "/lab/start"),
    ("GET", "/lab/page/landing"),
    ("GET", "/lab/page/catalog"),
    ("GET", "/lab/page/detail"),
    ("GET", "/lab/complete"),
)


def session_id(index: int) -> str:
    return "hmac-sha256:" + f"{index:064x}"


def request_id(session: int, step: int) -> str:
    return f"{session:016x}{step:016x}"


def session_record(
    index: int,
    *,
    automated: bool,
    task: str = "task-detail",
    window: str = "w1",
    excluded: bool = False,
    steps: int = len(PLAN),
) -> dict[str, object]:
    return {
        "marker": "owned-domain-2026-08-25-pf2-human-consented",
        "task": task,
        "pacing_variant": "scripted" if automated else "H1",
        "collection_window": window,
        "scenario_version": "ati-pf2-1.0",
        "controlled_automation": automated,
        "excluded": excluded,
        "exclusion_reason": "stopped" if excluded else None,
        "requests": [
            {
                "sequence": step + 1,
                "method": PLAN[step][0],
                "path": PLAN[step][1],
                "expected_status": 200,
                "status": 200,
                "request_id": request_id(index, step),
            }
            for step in range(steps)
        ],
    }


def exported_row(index: int, step: int) -> dict[str, object]:
    return {
        "request_id": request_id(index, step),
        "session_id": session_id(index),
        "request_method": PLAN[step][0],
        "request_uri": PLAN[step][1],
        "status": 200,
        "time_iso8601": f"2026-09-26T10:{index:02d}:{step:02d}+00:00",
        # Fields the corpus must not carry forward.
        "client_id": "blake2b:" + "0" * 32,
        "ua_provenance_bucket": "scripted-http",
        "ati_campaign_id": "owned-domain-2026-08-25-pf2-human-consented",
        "body_bytes_sent": 10,
        "server_protocol": "HTTP/1.1",
    }


def write_case(
    tmp_path: Path, records: list[dict[str, object]], *, indexes: list[int]
) -> tuple[Path, Path]:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    for position, record in enumerate(records):
        (session_dir / f"session-{position:02d}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
    export = tmp_path / "exported.jsonl"
    lines = [
        json.dumps(exported_row(index, step))
        for index in indexes
        for step in range(len(PLAN))
    ]
    export.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return session_dir, export


def two_class_case(tmp_path: Path) -> tuple[Path, Path]:
    records = [
        session_record(index, automated=index % 2 == 0, window="w1" if index < 4 else "w2")
        for index in range(8)
    ]
    return write_case(tmp_path, records, indexes=list(range(8)))


def test_builds_a_two_class_corpus_with_matching_local_maps(tmp_path: Path) -> None:
    session_dir, export = two_class_case(tmp_path)

    corpus, built = build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )

    summary = built["summary"]
    assert summary["reconciled_sessions"] == 8
    assert summary["corpus_rows"] == 8 * len(PLAN)
    assert summary["automated_sessions"] == 4
    assert summary["human_assisted_sessions"] == 4
    assert summary["both_classes_present"] is True
    assert summary["unmatched_request_ids"] == 0
    assert summary["excluded_sessions"] == []
    assert set(built["labels"]) == set(built["tasks"]) == set(built["windows"])
    assert summary["sessions_by_collection_window"] == {"w1": 4, "w2": 4}
    assert len(corpus) == len(built["labels"]) * len(PLAN)


def test_corpus_rows_carry_only_the_fields_the_preflight_reads(tmp_path: Path) -> None:
    session_dir, export = two_class_case(tmp_path)

    corpus, _ = build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )

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


def test_labels_come_from_the_executor_not_from_behaviour(tmp_path: Path) -> None:
    # Two sessions with byte-identical routes and differing only in the recorded label.
    records = [
        session_record(0, automated=True, window="w1"),
        session_record(1, automated=False, window="w2"),
    ]
    session_dir, export = write_case(tmp_path, records, indexes=[0, 1])

    _, built = build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )

    assert sorted(built["labels"].values()) == [False, True]


def test_session_excluded_by_the_executor_is_counted_not_dropped(tmp_path: Path) -> None:
    records = [
        session_record(0, automated=True),
        session_record(1, automated=False, excluded=True),
    ]
    session_dir, export = write_case(tmp_path, records, indexes=[0, 1])

    _, built = build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )

    summary = built["summary"]
    assert summary["reconciled_sessions"] == 1
    assert len(summary["excluded_sessions"]) == 1
    assert summary["excluded_sessions"][0]["reason"] == "stopped"
    assert summary["both_classes_present"] is False


def test_request_identifier_missing_from_the_export_excludes_the_session(
    tmp_path: Path,
) -> None:
    records = [session_record(0, automated=True), session_record(1, automated=False)]
    # Session 1 is absent from the export entirely.
    session_dir, export = write_case(tmp_path, records, indexes=[0])

    _, built = build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )

    summary = built["summary"]
    assert summary["reconciled_sessions"] == 1
    assert summary["unmatched_request_ids"] == len(PLAN)
    assert summary["excluded_sessions"][0]["reason"] == "request identifier missing from export"


def test_rows_spanning_two_sessions_exclude_the_session(tmp_path: Path) -> None:
    records = [session_record(0, automated=True)]
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    (session_dir / "s.json").write_text(json.dumps(records[0]), encoding="utf-8")
    rows = [exported_row(0, step) for step in range(len(PLAN))]
    rows[2]["session_id"] = session_id(99)
    export = tmp_path / "exported.jsonl"
    export.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    _, built = build(
        load_session_records(sorted(session_dir.glob("*.json"))),
        load_exported_rows(export),
    )

    assert built["summary"]["reconciled_sessions"] == 0
    assert built["summary"]["excluded_sessions"][0]["reason"] == "rows span more than one session"


def test_duplicate_request_identifier_in_the_export_fails_closed(tmp_path: Path) -> None:
    export = tmp_path / "exported.jsonl"
    row = json.dumps(exported_row(0, 0))
    export.write_text(row + "\n" + row + "\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="duplicated request identifiers"):
        load_exported_rows(export)


def test_transparent_session_identifier_in_the_export_fails_closed(tmp_path: Path) -> None:
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


def test_session_record_without_a_label_fails_closed(tmp_path: Path) -> None:
    record = session_record(0, automated=True)
    del record["controlled_automation"]
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    (session_dir / "s.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(CorpusError, match="missing the controlled_automation label"):
        load_session_records(sorted(session_dir.glob("*.json")))


def test_session_record_with_a_non_boolean_label_fails_closed(tmp_path: Path) -> None:
    record = session_record(0, automated=True)
    record["controlled_automation"] = "true"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    (session_dir / "s.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(CorpusError, match="must be a boolean"):
        load_session_records(sorted(session_dir.glob("*.json")))


def test_cli_writes_the_four_preflight_inputs(tmp_path: Path, capsys) -> None:
    session_dir, export = two_class_case(tmp_path)
    output = tmp_path / "corpus"

    code = main(
        [
            "--session-dir",
            str(session_dir),
            "--exported",
            str(export),
            "--output-dir",
            str(output),
        ]
    )

    assert code == 0
    for name in (
        "access.jsonl",
        "labels-by-session.json",
        "tasks-by-session.json",
        "collection-windows.json",
        "corpus-summary.json",
    ):
        assert (output / name).exists()
    summary = json.loads((output / "corpus-summary.json").read_text())
    assert summary["both_classes_present"] is True
    labels = json.loads((output / "labels-by-session.json").read_text())
    assert len(labels) == 8


def test_cli_warns_when_the_corpus_has_one_class(tmp_path: Path, capsys) -> None:
    records = [session_record(index, automated=True) for index in range(2)]
    session_dir, export = write_case(tmp_path, records, indexes=[0, 1])

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

    assert code == 0
    assert "one target class" in capsys.readouterr().err


def test_cli_refuses_an_existing_output_directory(tmp_path: Path, capsys) -> None:
    session_dir, export = two_class_case(tmp_path)
    output = tmp_path / "corpus"
    output.mkdir()

    code = main(
        [
            "--session-dir",
            str(session_dir),
            "--exported",
            str(export),
            "--output-dir",
            str(output),
        ]
    )

    assert code == 2
    assert "refusing to overwrite" in capsys.readouterr().err
