"""Reconcile local ATI-PF-2 session records against exported origin rows.

The executor never sees the origin's opaque session pseudonym; it only sees the random
`X-ATI-Request-ID` returned per request. This script joins the two through those opaque
identifiers and writes the four local inputs `ati pf2-preflight` reads.

It fails a session closed rather than repairing it. A session is excluded when the
executor already marked it excluded, when any of its request identifiers is missing from
the export, when one identifier matches more than one exported row, or when its rows do
not all carry a single session pseudonym. Exclusions are counted, never silently dropped.

Labels come from the executor's `controlled_automation` field, which records what actually
ran. This script never infers a label from a route, a pacing variant, a User-Agent or a
provenance bucket.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_SESSION_ID = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
# Only the fields the ATI-PF-2 preflight reads are copied into the corpus.
_PF2_FIELDS = ("session_id", "request_uri", "request_method", "status", "time_iso8601")


class CorpusError(ValueError):
    """Raised when a corpus cannot be built without breaking the split firewall."""


def load_session_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CorpusError(f"{path} does not contain one session record object")
        for field in ("task", "pacing_variant", "collection_window", "requests"):
            if field not in payload:
                raise CorpusError(f"{path} is missing the {field!r} field")
        if "controlled_automation" not in payload:
            raise CorpusError(f"{path} is missing the controlled_automation label")
        if not isinstance(payload["controlled_automation"], bool):
            raise CorpusError(f"{path} controlled_automation must be a boolean")
        payload["_source"] = path.name
        records.append(payload)
    if not records:
        raise CorpusError("no session records were supplied")
    return records


def load_exported_rows(path: Path) -> dict[str, dict[str, Any]]:
    """Index exported origin rows by opaque request identifier."""

    rows: dict[str, dict[str, Any]] = {}
    duplicates = 0
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise CorpusError(f"invalid JSON in export at line {number}") from error
            request_id = row.get("request_id")
            if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
                raise CorpusError(f"invalid opaque request id in export at line {number}")
            session_id = row.get("session_id")
            if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
                raise CorpusError(f"invalid session pseudonym in export at line {number}")
            missing = [field for field in _PF2_FIELDS if field not in row]
            if missing:
                raise CorpusError(f"export line {number} is missing {missing[0]!r}")
            if request_id in rows:
                duplicates += 1
                continue
            rows[request_id] = row
    if duplicates:
        raise CorpusError(f"export contains {duplicates} duplicated request identifiers")
    if not rows:
        raise CorpusError("export contains no usable rows")
    return rows


def build(
    records: list[dict[str, Any]], exported: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return corpus rows plus the local label, task and window maps."""

    corpus: list[dict[str, Any]] = []
    labels: dict[str, bool] = {}
    tasks: dict[str, str] = {}
    windows: dict[str, str] = {}
    excluded: list[dict[str, str]] = []
    matched = unmatched = 0

    for record in records:
        source = str(record["_source"])
        if record.get("excluded"):
            excluded.append(
                {"source": source, "reason": str(record.get("exclusion_reason") or "executor")}
            )
            continue
        request_ids = [
            str(entry.get("request_id", ""))
            for entry in record["requests"]
            if isinstance(entry, dict)
        ]
        if not request_ids or not all(_REQUEST_ID.fullmatch(value) for value in request_ids):
            excluded.append({"source": source, "reason": "invalid local request identifier"})
            continue
        if len(set(request_ids)) != len(request_ids):
            excluded.append({"source": source, "reason": "duplicate local request identifier"})
            continue
        rows = [exported[value] for value in request_ids if value in exported]
        unmatched += len(request_ids) - len(rows)
        if len(rows) != len(request_ids):
            excluded.append({"source": source, "reason": "request identifier missing from export"})
            continue
        session_ids = {str(row["session_id"]) for row in rows}
        if len(session_ids) != 1:
            excluded.append({"source": source, "reason": "rows span more than one session"})
            continue
        session_id = session_ids.pop()
        if session_id in labels:
            excluded.append({"source": source, "reason": "session pseudonym already claimed"})
            continue
        matched += len(rows)
        labels[session_id] = bool(record["controlled_automation"])
        tasks[session_id] = str(record["task"])
        windows[session_id] = str(record["collection_window"])
        for row in rows:
            corpus.append({field: row[field] for field in _PF2_FIELDS})

    corpus.sort(key=lambda row: (str(row["session_id"]), str(row["time_iso8601"])))
    automated = sum(labels.values())
    summary: dict[str, Any] = {
        "session_records": len(records),
        "reconciled_sessions": len(labels),
        "excluded_sessions": excluded,
        "matched_request_ids": matched,
        "unmatched_request_ids": unmatched,
        "corpus_rows": len(corpus),
        "automated_sessions": automated,
        "human_assisted_sessions": len(labels) - automated,
        "sessions_by_task": dict(sorted(Counter(tasks.values()).items())),
        "sessions_by_collection_window": dict(sorted(Counter(windows.values()).items())),
        "both_classes_present": len(set(labels.values())) == 2,
    }
    return corpus, {
        "labels": labels,
        "tasks": tasks,
        "windows": windows,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session-dir",
        type=Path,
        required=True,
        help="Directory of local session records written by lab_session.py.",
    )
    parser.add_argument(
        "--exported",
        type=Path,
        required=True,
        help="JSONL of privacy-safe rows exported from the origin's captured output.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.output_dir.exists():
            raise CorpusError(f"refusing to overwrite {args.output_dir}")
        records = load_session_records(sorted(args.session_dir.glob("*.json")))
        exported = load_exported_rows(args.exported)
        corpus, built = build(records, exported)
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "access.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in corpus),
            encoding="utf-8",
        )
        for name, payload in (
            ("labels-by-session.json", built["labels"]),
            ("tasks-by-session.json", built["tasks"]),
            ("collection-windows.json", built["windows"]),
        ):
            (args.output_dir / name).write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
        (args.output_dir / "corpus-summary.json").write_text(
            json.dumps(built["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (CorpusError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    summary = built["summary"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["both_classes_present"]:
        print(
            "note: this corpus has one target class, so ati pf2-preflight will refuse "
            "it. A two-class corpus needs the consented human cohort.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
