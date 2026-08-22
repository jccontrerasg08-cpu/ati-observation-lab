"""Reconcile local opaque request IDs against Railway structured deployment logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_BATCH_SIZE = 24


def load_request_ids(labels_path: Path) -> list[str]:
    source = labels_path.read_bytes()
    request_ids: list[str] = []
    for line_number, line in enumerate(source.decode("utf-8").splitlines(), start=1):
        if not line:
            raise ValueError(f"empty label line at position {line_number}")
        row = json.loads(line)
        request_id = row.get("request_id")
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise ValueError(f"invalid opaque request ID at position {line_number}")
        request_ids.append(request_id)
    if not request_ids:
        raise ValueError("labels file is empty")
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("duplicate opaque request ID in labels")
    return request_ids


def matching_log_counts(
    railway_cli: str,
    project: str,
    service: str,
    environment: str,
    deployment: str,
    request_ids: list[str],
) -> Counter[str]:
    if not request_ids:
        return Counter()
    query = " OR ".join(f"@request_id:{request_id}" for request_id in request_ids)
    command = [
        railway_cli,
        "logs",
        deployment,
        "--project",
        project,
        "--service",
        service,
        "--environment",
        environment,
        "--lines",
        str(len(request_ids) + 1),
        "--filter",
        query,
        "--json",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    requested_ids = set(request_ids)
    counts: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        request_id = row.get("request_id")
        if request_id in requested_ids:
            counts[request_id] += 1
    return counts


def reconcile(args: argparse.Namespace) -> dict[str, object]:
    labels = args.labels.resolve()
    request_ids = load_request_ids(labels)
    railway_cli = os.environ.get("RAILWAY_CLI", "railway")
    matched = missing = ambiguous = 0
    for start in range(0, len(request_ids), _BATCH_SIZE):
        batch = request_ids[start : start + _BATCH_SIZE]
        counts = matching_log_counts(
            railway_cli,
            args.project,
            args.service,
            args.environment,
            args.deployment,
            batch,
        )
        matched += sum(count == 1 for count in counts.values())
        missing += sum(request_id not in counts for request_id in batch)
        ambiguous += sum(count - 1 for count in counts.values() if count > 1)
    checksum = hashlib.sha256(labels.read_bytes()).hexdigest()
    return {
        "ambiguous": ambiguous,
        "expected": len(request_ids),
        "labels_sha256": checksum,
        "matched": matched,
        "missing": missing,
        "status": "complete" if missing == 0 and ambiguous == 0 else "incomplete",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--deployment", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(reconcile(args), separators=(",", ":"), sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"request-id reconciliation failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
