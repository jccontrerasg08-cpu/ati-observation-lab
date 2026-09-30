"""The versioned closed-route catalogue shared by every ATI-PF-2 component.

This file's JSON companion is the single source of truth for the laboratory's closed
`/lab/*` catalogue. The origin application, the Cloudflare Worker, the local executor and
the corpus builder are each checked against it by tests, and the ATI repository pins the
same ATI-PF-2 route-category mapping and version. A route may only change here, together
with every consumer, in one reviewed change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Any

_RAW: dict[str, Any] = json.loads(
    resources.files(__package__).joinpath("catalogue.json").read_text(encoding="utf-8")
)

CATALOGUE_VERSION: str = _RAW["version"]
"""Version string; ATI pins the same value next to its route-category mapping."""

ROUTE_STATUS: MappingProxyType[str, int] = MappingProxyType(
    {route["path"]: route["status"] for route in _RAW["routes"]}
)
"""Every closed `/lab/*` route and the status the origin serves for it."""

PF2_ROUTE_CATEGORIES: MappingProxyType[str, str] = MappingProxyType(
    {
        route["path"]: route["pf2_category"]
        for route in _RAW["routes"]
        if route["pf2_category"] is not None
    }
)
"""Routes eligible for an ATI-PF-2 corpus and their coarse category."""

TASK_BRANCHES: MappingProxyType[str, str] = MappingProxyType(dict(_RAW["task_branches"]))
"""Audit-only task names and the branch route each one takes."""

PACING_VARIANTS: MappingProxyType[str, tuple[float, float]] = MappingProxyType(
    {name: (float(low), float(high)) for name, (low, high) in _RAW["pacing_variants"].items()}
)
"""Declared pacing regimes as inclusive delay ranges in seconds."""

HUMAN_PACING_VARIANTS: frozenset[str] = frozenset(_RAW["human_pacing_variants"])
"""Regimes a consented participant can follow; `burst` is not one of them."""


@dataclass(frozen=True, slots=True)
class Step:
    """One planned request in the closed catalogue."""

    method: str
    path: str
    expected_status: int


def plan_session(task: str, *, fetch_assets: bool) -> tuple[Step, ...]:
    """Build the ATI-PF-2 route plan, identical in shape for every cohort.

    Every step is an ATI-PF-2-eligible route, the plan always terminates at completion,
    and the integrity-only error route is never part of it.
    """

    branch = TASK_BRANCHES.get(task)
    if branch is None:
        raise ValueError(f"task must be one of {sorted(TASK_BRANCHES)}")
    paths = ["/lab/start", "/lab/page/landing"]
    if fetch_assets:
        paths.append("/lab/assets/site.css")
    paths.append("/lab/page/catalog")
    if fetch_assets:
        paths.append("/lab/assets/pixel.svg")
    paths.extend([branch, "/lab/complete"])
    for path in paths:
        if path not in PF2_ROUTE_CATEGORIES:
            raise ValueError(f"route is not ATI-PF-2 eligible: {path}")
    return tuple(Step("GET", path, ROUTE_STATUS[path]) for path in paths)
