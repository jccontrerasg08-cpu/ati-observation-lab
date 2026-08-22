"""Reconcile local opaque request IDs against Railway structured deployment logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
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


def matching_log_count(
    railway_cli: str, project: str, service: str, environment: str, request_ids: list[str]
) -> int:
    if not request_ids:
        return 0
    query = " OR ".join(f"@request_id:{request_id}" for request_id in request_ids)
    command = [
        railway_cli,
        "logs",
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
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def reconcile(args: argparse.Namespace) -> dict[str, object]:
    labels = args.labels.resolve()
    request_ids = load_request_ids(labels)
    railway_cli = os.environ.get("RAILWAY_CLI", "railway")
    matched = missing = ambiguous = 0
    for start in range(0, len(request_ids), _BATCH_SIZE):
        batch = request_ids[start : start + _BATCH_SIZE]
        count = matching_log_count(
            railway_cli, args.project, args.service, args.environment, batch
        )
        if count == len(batch):
            matched += len(batch)
        elif count < len(batch):
            matched += count
            missing += len(batch) - count
        else:
            matched += len(batch)
            ambiguous += count - len(batch)
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
    args = parser.parse_args()
    try:
        print(json.dumps(reconcile(args), separators=(",", ":"), sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"request-id reconciliation failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
