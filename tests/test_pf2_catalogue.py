"""The closed catalogue is one versioned contract; every consumer must agree with it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from observation_lab.app import _LAB_CONTENT
from observation_lab.pf2.catalogue import (
    CATALOGUE_VERSION,
    HUMAN_PACING_VARIANTS,
    PACING_VARIANTS,
    PAGE_CONTENT,
    PF2_ROUTE_CATEGORIES,
    READING_LOAD,
    ROUTE_STATUS,
    TASK_BRANCHES,
    plan_session,
)

# Pinned identically in agent-traffic-intelligence (tests/evaluation/
# test_pf2_catalogue_parity.py) against PF2_ROUTE_CATEGORIES there. Change both together.
ATI_PINNED_VERSION = "ati-pf2-catalogue-2"
ATI_PINNED_CATEGORIES = {
    "/lab/start": "start",
    "/lab/page/landing": "landing",
    "/lab/page/catalog": "catalog",
    "/lab/page/detail": "detail",
    "/lab/page/related": "related",
    "/lab/complete": "complete",
    "/lab/assets/site.css": "asset",
    "/lab/assets/pixel.svg": "asset",
}
# Also pinned in ATI as PF2_READING_LOAD, per route category.
ATI_PINNED_READING_LOAD = {
    "start": "short",
    "landing": "short",
    "complete": "short",
    "catalog": "long",
    "detail": "long",
    "related": "long",
}
WORKER_SOURCE = Path(__file__).resolve().parents[1] / "cloudflare-worker/src/index.mjs"


def test_origin_serves_exactly_the_catalogue_routes_and_statuses() -> None:
    assert set(_LAB_CONTENT) == set(ROUTE_STATUS)
    for path, (status, _media_type, _content) in _LAB_CONTENT.items():
        assert status == ROUTE_STATUS[path], path


def test_worker_allowlists_exactly_the_catalogue_routes() -> None:
    source = WORKER_SOURCE.read_text(encoding="utf-8")
    block = re.search(r"const LAB_PATHS = new Set\(\[(.*?)\]\);", source, re.DOTALL)
    assert block is not None, "LAB_PATHS literal not found in the Worker"
    assert set(re.findall(r'"(/lab/[^"]+)"', block.group(1))) == set(ROUTE_STATUS)


def test_pf2_mapping_matches_the_mapping_pinned_in_ati() -> None:
    assert CATALOGUE_VERSION == ATI_PINNED_VERSION
    assert dict(PF2_ROUTE_CATEGORIES) == ATI_PINNED_CATEGORIES
    by_category = {PF2_ROUTE_CATEGORIES[path]: load for path, load in READING_LOAD.items()}
    assert by_category == ATI_PINNED_READING_LOAD


def test_every_page_has_a_reading_load_and_text_and_nothing_else_does() -> None:
    pages = {path for path, category in PF2_ROUTE_CATEGORIES.items() if category != "asset"}
    assert set(READING_LOAD) == pages
    assert set(PAGE_CONTENT) == pages
    for path in pages:
        assert PAGE_CONTENT[path].title and PAGE_CONTENT[path].paragraphs


def test_long_pages_give_a_reader_markedly_more_to_read_than_short_ones() -> None:
    words = {
        path: sum(len(paragraph.split()) for paragraph in page.paragraphs)
        for path, page in PAGE_CONTENT.items()
    }
    shortest_long = min(words[path] for path, load in READING_LOAD.items() if load == "long")
    longest_short = max(words[path] for path, load in READING_LOAD.items() if load == "short")
    assert shortest_long >= 5 * longest_short


def test_the_integrity_only_error_route_is_served_but_never_pf2_eligible() -> None:
    assert ROUTE_STATUS["/lab/missing"] == 404
    assert "/lab/missing" not in PF2_ROUTE_CATEGORIES


def test_every_pf2_route_is_served_successfully() -> None:
    assert all(ROUTE_STATUS[path] == 200 for path in PF2_ROUTE_CATEGORIES)


def test_task_branches_are_pf2_eligible_pages() -> None:
    for branch in TASK_BRANCHES.values():
        assert PF2_ROUTE_CATEGORIES[branch] in {"detail", "related"}


def test_human_pacing_variants_are_a_strict_subset_of_all_variants() -> None:
    assert HUMAN_PACING_VARIANTS < set(PACING_VARIANTS)
    assert "burst" not in HUMAN_PACING_VARIANTS
    for low, high in PACING_VARIANTS.values():
        assert 0 < low < high


@pytest.mark.parametrize("task", sorted(TASK_BRANCHES))
@pytest.mark.parametrize("assets", [True, False])
def test_every_plan_is_pf2_eligible_and_terminates_at_completion(
    task: str, assets: bool
) -> None:
    steps = plan_session(task, fetch_assets=assets)

    assert steps[0].path == "/lab/start"
    assert steps[-1].path == "/lab/complete"
    assert all(step.path in PF2_ROUTE_CATEGORIES for step in steps)
    assert all(step.expected_status == 200 for step in steps)
    assert TASK_BRANCHES[task] in [step.path for step in steps]


def test_both_tasks_produce_the_same_shape() -> None:
    detail = [step.path for step in plan_session("task-detail", fetch_assets=True)]
    related = [step.path for step in plan_session("task-related", fetch_assets=True)]

    assert len(detail) == len(related)
    assert detail.index("/lab/page/detail") == related.index("/lab/page/related")


def test_unknown_task_is_refused() -> None:
    with pytest.raises(ValueError, match="task must be one of"):
        plan_session("task-missing", fetch_assets=True)
