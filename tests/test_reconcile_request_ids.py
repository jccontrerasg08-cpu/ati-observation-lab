from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_reconciler_reports_aggregate_success_without_request_ids(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    request_ids = [f"{number:032x}" for number in range(1, 7)]
    labels.write_text(
        "".join(
            json.dumps({"request_id": request_id}, separators=(",", ":")) + "\n"
            for request_id in request_ids
        ),
        encoding="utf-8",
    )
    fake_railway = tmp_path / "railway"
    fake_railway.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s\\n' "
        + " ".join(f"'{{\"request_id\":\"{request_id}\"}}'" for request_id in request_ids)
        + "\n",
        encoding="utf-8",
    )
    fake_railway.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_request_ids.py",
            "--labels",
            str(labels),
            "--project",
            "project-id",
            "--service",
            "service-id",
            "--environment",
            "production",
            "--deployment",
            "deployment-id",
        ],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "RAILWAY_CLI": str(fake_railway)},
    )

    summary = json.loads(result.stdout)
    assert summary["expected"] == 6
    assert summary["matched"] == 6
    assert summary["missing"] == 0
    assert summary["ambiguous"] == 0
    assert summary["status"] == "complete"
    assert summary["labels_sha256"]
    assert not any(request_id in result.stdout for request_id in request_ids)


def test_reconciler_queries_a_batch_once_and_reports_aggregate_summary(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    request_ids = [f"{number:032x}" for number in range(1, 4)]
    labels.write_text(
        "".join(
            json.dumps({"request_id": request_id}, separators=(",", ":")) + "\n"
            for request_id in request_ids
        ),
        encoding="utf-8",
    )
    calls = tmp_path / "calls"
    fake_railway = tmp_path / "railway"
    fake_railway.write_text(
        "#!/usr/bin/env sh\n"
        "printf x >> \"$COUNTER_FILE\"\n"
        "printf '%s\\n' "
        + " ".join(f"'{{\"request_id\":\"{request_id}\"}}'" for request_id in request_ids)
        + "\n",
        encoding="utf-8",
    )
    fake_railway.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_request_ids.py",
            "--labels",
            str(labels),
            "--project",
            "project-id",
            "--service",
            "service-id",
            "--environment",
            "production",
            "--deployment",
            "deployment-id",
        ],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "COUNTER_FILE": str(calls),
            "RAILWAY_CLI": str(fake_railway),
        },
    )

    summary = json.loads(result.stdout)
    assert calls.read_text(encoding="utf-8") == "x"
    assert summary["expected"] == 3
    assert summary["matched"] == 3
    assert summary["missing"] == 0
    assert summary["ambiguous"] == 0
    assert summary["status"] == "complete"
    assert not any(request_id in result.stdout for request_id in request_ids)


def test_reconciler_scopes_batch_query_to_explicit_deployment(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    request_ids = [f"{number:032x}" for number in range(1, 3)]
    labels.write_text(
        "".join(
            json.dumps({"request_id": request_id}, separators=(",", ":")) + "\n"
            for request_id in request_ids
        ),
        encoding="utf-8",
    )
    arguments = tmp_path / "arguments"
    fake_railway = tmp_path / "railway"
    fake_railway.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s' \"$*\" > \"$ARGUMENTS_FILE\"\n"
        "printf '%s\\n' "
        + " ".join(f"'{{\"request_id\":\"{request_id}\"}}'" for request_id in request_ids)
        + "\n",
        encoding="utf-8",
    )
    fake_railway.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_request_ids.py",
            "--labels",
            str(labels),
            "--project",
            "project-id",
            "--service",
            "service-id",
            "--environment",
            "production",
            "--deployment",
            "historical-deployment-id",
        ],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "ARGUMENTS_FILE": str(arguments),
            "RAILWAY_CLI": str(fake_railway),
        },
    )

    assert "historical-deployment-id" in arguments.read_text(encoding="utf-8")
    assert json.loads(result.stdout)["status"] == "complete"
