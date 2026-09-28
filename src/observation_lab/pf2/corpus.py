"""Reconcile local ATI-PF-2 session records against exported origin rows.

The executor never sees the origin's opaque session pseudonym; it only sees the random
`X-ATI-Request-ID` returned per request. This module joins the two through those opaque
identifiers and writes the four local inputs `ati pf2-preflight` reads.

It fails a session closed rather than repairing it: a session is excluded when the
executor already excluded it, when any of its identifiers is missing from the export,
when one identifier matches more than one row, when its rows span more than one session
pseudonym, when a row is not an ATI-PF-2-eligible route, or when a joined row disagrees
with the local request it claims to be on path, method or status. Exclusions are counted,
never silently dropped.

It also checks what `ati pf2-preflight` cannot see. Pacing variant, executor, scenario
version and catalogue version are local audit metadata that never reach ATI, so only this
step can detect that one of them occurs in a single target class — which the shared task
graph declares invalid for model fitting. Such a corpus is refused unless it is built
explicitly as a diagnostic.

Labels come from the executor's recorded cohort. Nothing here infers a label from a
route, a pacing variant, a User-Agent or a provenance bucket.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from observation_lab.pf2.catalogue import PF2_ROUTE_CATEGORIES

_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_SESSION_ID = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
# Only the fields the ATI-PF-2 preflight reads are copied into the corpus.
_PF2_FIELDS = ("session_id", "request_uri", "request_method", "status", "time_iso8601")
# Audit-only dimensions invisible to ATI that must be shared by both classes.
_SHARED_AUDIT_DIMENSIONS = (
    "pacing_variant",
    "executor",
    "scenario_version",
    "catalogue_version",
)
_COHORT_LABEL = {"automated": True, "human-consented": False}


class CorpusError(ValueError):
    """Raised when a corpus cannot be built without breaking the split firewall."""


def _label(payload: dict[str, Any], source: str) -> bool:
    label = payload.get("controlled_automation")
    if not isinstance(label, bool):
        raise CorpusError(f"{source} controlled_automation must be a boolean")
    cohort = payload.get("cohort")
    if cohort is not None and _COHORT_LABEL.get(cohort) is not label:
        raise CorpusError(f"{source} cohort disagrees with controlled_automation")
    return label


def load_session_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CorpusError(f"{path.name} does not contain one session record object")
        for name in ("task", "collection_window", "requests"):
            if name not in payload:
                raise CorpusError(f"{path.name} is missing the {name!r} field")
        # A missing audit dimension would otherwise read as one shared value and hide
        # exactly the class confound this step exists to catch.
        for name in _SHARED_AUDIT_DIMENSIONS:
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                raise CorpusError(f"{path.name} must record {name!r} as a non-empty string")
        if not isinstance(payload["requests"], list) or not all(
            isinstance(entry, dict) for entry in payload["requests"]
        ):
            raise CorpusError(f"{path.name} requests must be a list of request objects")
        if "controlled_automation" not in payload:
            raise CorpusError(f"{path.name} is missing the controlled_automation label")
        payload["_label"] = _label(payload, path.name)
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
            if not isinstance(row, dict):
                raise CorpusError(f"export line {number} is not a JSON object")
            request_id = row.get("request_id")
            if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
                raise CorpusError(f"invalid opaque request id in export at line {number}")
            session_id = row.get("session_id")
            if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
                raise CorpusError(f"invalid session pseudonym in export at line {number}")
            missing = [name for name in _PF2_FIELDS if name not in row]
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


def _exclusion(record: dict[str, Any], exported: dict[str, dict[str, Any]]) -> str | None:
    if record.get("excluded"):
        return str(record.get("exclusion_reason") or "excluded by the executor")
    request_ids = [str(entry.get("request_id", "")) for entry in record["requests"]]
    if not request_ids or not all(_REQUEST_ID.fullmatch(value) for value in request_ids):
        return "invalid local request identifier"
    if len(set(request_ids)) != len(request_ids):
        return "duplicate local request identifier"
    if any(value not in exported for value in request_ids):
        return "request identifier missing from export"
    rows = [exported[value] for value in request_ids]
    if len({str(row["session_id"]) for row in rows}) != 1:
        return "rows span more than one session"
    if any(str(row["request_uri"]) not in PF2_ROUTE_CATEGORIES for row in rows):
        return "row is not an ATI-PF-2-eligible route"
    for entry, row in zip(record["requests"], rows, strict=True):
        if str(entry.get("status")) != str(entry.get("expected_status")):
            return "local request did not receive its expected status"
        if (
            entry.get("path") != row["request_uri"]
            or entry.get("method") != row["request_method"]
            or str(entry.get("status")) != str(row["status"])
        ):
            return "joined row disagrees with the local request"
    return None


def confounded_dimensions(accepted: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return audit values that occur in only one target class, per dimension."""

    confounded: dict[str, list[str]] = {}
    for dimension in _SHARED_AUDIT_DIMENSIONS:
        classes: dict[str, set[bool]] = defaultdict(set)
        for record in accepted:
            classes[str(record[dimension])].add(bool(record["_label"]))
        single = sorted(value for value, labels in classes.items() if len(labels) == 1)
        if single:
            confounded[dimension] = single
    return confounded


def build(
    records: list[dict[str, Any]], exported: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return corpus rows plus the local label, task and window maps and a summary."""

    corpus: list[dict[str, Any]] = []
    labels: dict[str, bool] = {}
    tasks: dict[str, str] = {}
    windows: dict[str, str] = {}
    excluded: list[dict[str, str]] = []
    accepted: list[dict[str, Any]] = []
    matched = unmatched = 0

    for record in records:
        source = str(record["_source"])
        request_ids = [str(entry.get("request_id", "")) for entry in record["requests"]]
        unmatched += sum(value not in exported for value in request_ids)
        reason = _exclusion(record, exported)
        if reason is not None:
            excluded.append({"source": source, "reason": reason})
            continue
        rows = [exported[value] for value in request_ids]
        session_id = str(rows[0]["session_id"])
        if session_id in labels:
            excluded.append({"source": source, "reason": "session pseudonym already claimed"})
            continue
        matched += len(rows)
        accepted.append(record)
        labels[session_id] = bool(record["_label"])
        tasks[session_id] = str(record["task"])
        windows[session_id] = str(record["collection_window"])
        corpus.extend({name: row[name] for name in _PF2_FIELDS} for row in rows)

    corpus.sort(key=lambda row: (str(row["session_id"]), str(row["time_iso8601"])))
    automated = sum(labels.values())
    both_classes = len(set(labels.values())) == 2
    confounded = confounded_dimensions(accepted) if both_classes else {}
    blockers: list[str] = []
    if not both_classes:
        blockers.append("corpus has one target class")
    blockers.extend(
        f"{dimension} value(s) {values} occur in one target class only"
        for dimension, values in confounded.items()
    )
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
        "both_classes_present": both_classes,
        "class_confounded_audit_dimensions": confounded,
        "fitting_ready": not blockers,
        "fitting_blockers": blockers,
    }
    return corpus, {"labels": labels, "tasks": tasks, "windows": windows, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ati-lab-corpus",
        description="Reconcile ATI-PF-2 session records into local preflight inputs.",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        required=True,
        help="Directory of local session records written by ati-lab-session.",
    )
    parser.add_argument(
        "--exported",
        type=Path,
        required=True,
        help="JSONL of privacy-safe rows exported from the origin's captured output.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Write a corpus that is not fitting-ready, for collection diagnostics only.",
    )
    args = parser.parse_args(argv)

    try:
        if args.output_dir.exists():
            raise CorpusError(f"refusing to overwrite {args.output_dir}")
        records = load_session_records(sorted(args.session_dir.glob("*.json")))
        corpus, built = build(records, load_exported_rows(args.exported))
    except (CorpusError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    summary = built["summary"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["fitting_ready"] and not args.diagnostic:
        print(
            "error: corpus is not fitting-ready: "
            + "; ".join(summary["fitting_blockers"])
            + ". Nothing was written; rerun with --diagnostic to inspect it anyway.",
            file=sys.stderr,
        )
        return 2
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "access.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in corpus), encoding="utf-8"
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
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
