"""Offline contract, interpretation, query safety, and failure tests."""

import asyncio
import copy
import sys
from datetime import date

import pytest
from fastmcp import Client

from nepa_mcp.loader import load_server_module
from nepa_mcp_common.http import UpstreamServiceError

STAMP = 1788590286


def _row(**overrides):
    """Minimal source-shaped milestone data, independent of live project snapshots."""
    return {
        "project_id": "124556",
        "project_title": "Example campus",
        "project_field_project_status": "In Progress",
        "project_field_location_state": "VA",
        "total_estimated_project_cost": "$1,234.00",
        "action_id": "1",
        "action_type": "Section 404 Clean Water Act",
        "action_status": "In Progress",
        "action_agency": "US Army Corps of Engineers - Regulatory",
        "milestone_id": "101",
        "unique_id": "101",
        "action_milestone_name": "Application received",
        "action_milestone_completion_target": "2026-02-13T00:00:00.000",
        "action_milestone_baseline_target": "2026-02-13T00:00:00.000",
        "action_milestone_completion_actual": "2026-02-13T00:00:00.000",
        "action_milestone_complete": True,
        "action_milestone_na": False,
        "action_milestone_final_milestone": False,
        "last_data_fetched": "2026-09-05T06:05:42.000",
        **overrides,
    }


def _project_rows():
    return [
        _row(),
        _row(milestone_id="102", unique_id="102", action_milestone_na=True),
        _row(
            action_id="2",
            action_type="Environmental Assessment (EA)",
            milestone_id="201",
            unique_id="201",
            action_milestone_completion_target="2027-06-11T00:00:00.000",
            action_milestone_completion_actual=None,
            action_milestone_complete=False,
            action_milestone_final_milestone=True,
        ),
        _row(
            action_id="3", action_type="ESA Consultation", action_status="Complete", milestone_id="301", unique_id="301"
        ),
        _row(
            action_id="4",
            action_type="Section 106 Review",
            action_status="Complete",
            milestone_id="401",
            unique_id="401",
        ),
    ]


def _alternative_date_rows():
    return [
        _row(
            project_id="122316",
            action_milestone_name="Scoping",
            action_milestone_complete=False,
            action_milestone_completion_actual=None,
            action_milestone_completion_target="2026-08-31T00:00:00.000",
            action_milestone_baseline_target="2026-08-31T00:00:00.000",
            milestone_alternative_completion_date="2026-10-05T00:00:00.000",
        ),
    ]


@pytest.fixture
def api(monkeypatch):
    server = load_server_module("permitting_dashboard")
    module = sys.modules[server.search_permitting_projects.__module__]
    monkeypatch.setattr(module, "_metadata", lambda: STAMP)
    monkeypatch.setattr(module, "_today", lambda: date(2026, 9, 6))
    # A forgotten mock must fail immediately rather than use the network.
    monkeypatch.setattr(module, "get_json_rows", lambda *_a, **_k: pytest.fail("Unexpected network query"))
    return module


def install_rows(api, monkeypatch, rows):
    calls = []

    def query(url, *, params, **kwargs):
        calls.append((url, params, kwargs))
        return copy.deepcopy(rows)

    monkeypatch.setattr(api, "get_json_rows", query)
    return calls


def test_timetable_preserves_review_grain_and_source_values(api, monkeypatch):
    install_rows(api, monkeypatch, _project_rows())
    result = api.get_project_permitting_timetable("124556")
    assert result["status"] == "ok"
    assert result["summary_scope"] == "complete_project_export"
    assert result["summary"]["action_status_counts"] == {"In Progress": 2, "Complete": 2}
    assert result["summary"]["returned_milestone_count"] == 5
    assert result["summary"]["milestones_with_quality_warnings"] == 1
    assert result["project"]["project_id"] == "124556"
    assert result["project"]["total_estimated_project_cost"] == "$1,234.00"
    assert result["source"]["dataset_rows_updated_at_utc"] == "2026-09-05T06:38:06+00:00"
    assert result["source"]["last_data_fetched"] == ["2026-09-05T06:05:42.000"]
    ea = next(a for a in result["actions"] if a["action_type"] == "Environmental Assessment (EA)")
    final = next(m for m in ea["milestones"] if m["action_milestone_final_milestone"])
    assert final["effective_target_date"] == "2027-06-11"
    assert final["action_milestone_completion_actual"] is None
    assert final["interpreted_status"] == "scheduled"


def test_alternative_date_takes_precedence_and_retains_original(api, monkeypatch):
    install_rows(api, monkeypatch, _alternative_date_rows())
    result = api.get_project_permitting_timetable("122316")
    milestones = result["actions"][0]["milestones"]
    scoping = next(m for m in milestones if m["action_milestone_name"].startswith("Scoping"))
    assert scoping["effective_target_date"] == "2026-10-05"
    assert scoping["effective_target_source"] == "milestone_alternative_completion_date"
    assert scoping["action_milestone_completion_target"] == "2026-08-31T00:00:00.000"
    assert scoping["target_shift_days"] == 35


@pytest.mark.parametrize(
    "updates,expected,warning",
    [
        (
            {"action_milestone_completion_actual": "2027-10-01T00:00:00.000"},
            "inconsistent_or_unknown",
            "future_actual_completion_date",
        ),
        ({"action_milestone_completion_actual": None}, "inconsistent_or_unknown", "complete_without_valid_actual_date"),
        ({"action_milestone_complete": False}, "inconsistent_or_unknown", "incomplete_with_actual_date"),
        ({"action_milestone_na": True}, "not_applicable", "not_applicable_with_completion"),
        (
            {"action_milestone_complete": "false"},
            "inconsistent_or_unknown",
            "unknown_or_invalid_flag:action_milestone_complete",
        ),
        (
            {"milestone_alternative_completion_date": "bad-date"},
            "inconsistent_or_unknown",
            "invalid_date:milestone_alternative_completion_date",
        ),
    ],
)
def test_inconsistent_source_dates_and_flags_are_not_silently_normalized(api, updates, expected, warning):
    row = {**_row(), **updates}
    result = api.interpret_milestone(row, date(2026, 9, 6))
    assert result["interpreted_status"] == expected
    assert warning in result["warnings"]
    for k, v in updates.items():
        assert result[k] == v


@pytest.mark.parametrize(
    "status,target,expected",
    [
        ("In Progress", "2026-09-01T00:00:00.000", "past_target_incomplete"),
        ("In Progress", None, "unscheduled"),
        ("Paused", "2026-09-01T00:00:00.000", "paused"),
        ("Cancelled", "2026-09-01T00:00:00.000", "inactive_action"),
    ],
)
def test_incomplete_milestone_interpretation(api, status, target, expected):
    row = {
        **_row(),
        "action_milestone_complete": False,
        "action_milestone_completion_actual": None,
        "action_status": status,
        "action_milestone_completion_target": target,
    }
    assert api.interpret_milestone(row, date(2026, 9, 6))["interpreted_status"] == expected


def test_search_uses_canonical_rows_and_escapes_literals(api, monkeypatch):
    rows = [_row()]
    calls = install_rows(api, monkeypatch, rows)
    result = api.search_permitting_projects(
        query="O'Brien ' OR '1'='1", states=["va"], sector="Data", lead_agency="Army", project_status="In Progress"
    )
    where = calls[0][1]["$where"]
    assert "project_canonical = true" in where
    assert "O''BRIEN '' OR ''1''=''1" in where
    assert "project_field_location_state in ('VA')" in where
    assert "project_field_project_lead_agency_bureau" in where
    assert result["project_count"] == 1
    assert "milestone_id" not in result["projects"][0]


def test_lookahead_pagination_and_snapshot_token(api, monkeypatch):
    calls = install_rows(api, monkeypatch, [_row(), {**_row(), "project_id": "124557"}])
    result = api.search_permitting_projects(max_results=1, result_offset=3, snapshot_updated_at=STAMP)
    assert result["status"] == "truncated"
    assert result["pagination"] == {
        "max_results": 1,
        "result_offset": 3,
        "returned_count": 1,
        "has_more": True,
        "next_result_offset": 4,
        "listing_complete": False,
    }
    assert calls[0][1]["$limit"] == 2
    assert calls[0][1]["$offset"] == 3
    assert "unique_id" in calls[0][1]["$order"]


def test_snapshot_change_prevents_mixing_pages(api, monkeypatch):
    result = api.search_permitting_projects(snapshot_updated_at=STAMP - 1)
    assert result["status"] == "unavailable"
    assert "Snapshot changed" in result["error"]
    assert result["pagination"]["has_more"] is None


def test_snapshot_change_during_query_is_partial(api, monkeypatch):
    stamps = iter([STAMP, STAMP + 1])
    monkeypatch.setattr(api, "_metadata", lambda: next(stamps))
    install_rows(api, monkeypatch, [_row()])
    result = api.search_permitting_projects()
    assert result["status"] == "partial"
    assert not result["pagination"]["listing_complete"]


def test_metadata_outage_preserves_data_with_partial_status(api, monkeypatch):
    def fail():
        raise UpstreamServiceError("metadata unavailable")

    monkeypatch.setattr(api, "_metadata", fail)
    install_rows(api, monkeypatch, [_row()])
    result = api.search_permitting_projects()
    assert result["status"] == "partial"
    assert result["project_count"] == 1
    assert result["source"]["metadata_status"] == "unavailable"


def test_empty_and_unavailable_are_distinct(api, monkeypatch):
    install_rows(api, monkeypatch, [])
    empty = api.search_permitting_projects(query="nonexistent")
    assert empty["status"] == "empty" and empty["pagination"]["has_more"] is False

    def fail(*_a, **_k):
        raise UpstreamServiceError("timeout")

    monkeypatch.setattr(api, "get_json_rows", fail)
    unavailable = api.search_permitting_projects()
    assert unavailable["status"] == "unavailable" and unavailable["pagination"]["has_more"] is None
    assert unavailable["error"] == "timeout"


def test_timetable_page_does_not_claim_project_totals(api, monkeypatch):
    install_rows(api, monkeypatch, _project_rows()[:3])
    result = api.get_project_permitting_timetable("124556", max_results=2)
    assert result["status"] == "truncated"
    assert result["summary_scope"] == "returned_page"
    assert result["summary"]["returned_milestone_count"] == 2


def test_conflicting_and_duplicate_rows_are_explicit(api, monkeypatch):
    row = _row()
    install_rows(api, monkeypatch, [row, {**row, "action_status": "Complete"}])
    result = api.get_project_permitting_timetable("124556")
    assert result["status"] == "partial"
    assert result["summary"]["returned_milestone_count"] == 1
    assert any("Conflicting fields" in w for w in result["warnings"])
    assert any("Duplicate milestone" in w for w in result["warnings"])


def test_upstream_ignoring_limits_or_returning_wrong_shape_fails(api, monkeypatch):
    install_rows(api, monkeypatch, [{"new_schema_id": "1"}])
    assert api.search_permitting_projects()["status"] == "unavailable"
    install_rows(api, monkeypatch, _project_rows())
    assert api.search_permitting_projects(max_results=1)["status"] == "unavailable"


@pytest.mark.parametrize(
    "mode,start,end,date_field",
    [
        ("upcoming", "2026-09-06", "2026-10-06", "coalesce("),
        ("recently_completed", "2026-08-07", "2026-09-06", "action_milestone_completion_actual"),
        ("past_target", "1900-01-01", "2026-09-05", "coalesce("),
    ],
)
def test_milestone_modes_query_correct_dates_and_flags(api, monkeypatch, mode, start, end, date_field):
    calls = install_rows(api, monkeypatch, [])
    result = api.find_permitting_milestones(mode=mode, project_id="124556", agency="Army", action_type="404")
    where = calls[0][1]["$where"]
    assert start in where and end in where and date_field in where
    assert "action_milestone_na = false" in where
    assert "action_milestone_complete = " + ("true" if mode == "recently_completed" else "false") in where
    if mode != "recently_completed":
        assert "action_milestone_completion_actual is null" in where
        assert "action_status in ('In Progress','Planned')" in where
    assert result["status"] == "empty"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "%"},
        {"query": "_"},
        {"query": "x\n"},
        {"query": "x\\"},
        {"query": " "},
        {"query": "x" * 161},
        {"states": []},
        {"states": ["ZZ"]},
        {"states": "VA"},
        {"project_status": "approved"},
        {"max_results": True},
        {"max_results": 1.5},
        {"max_results": 101},
        {"result_offset": -1},
        {"result_offset": 100001},
    ],
)
def test_invalid_search_inputs_fail_before_network(api, kwargs):
    with pytest.raises(ValueError):
        api.search_permitting_projects(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "overdue"},
        {"date_from": "2026-02-30"},
        {"date_from": "2026-9-1"},
        {"date_from": "2026-10-01", "date_to": "2026-09-01"},
        {"mode": "recently_completed", "date_to": "2027-01-01"},
        {"mode": "past_target", "date_to": "2026-09-06"},
        {"project_id": "1 OR 1=1"},
    ],
)
def test_invalid_milestone_inputs_fail_before_network(api, kwargs):
    with pytest.raises(ValueError):
        api.find_permitting_milestones(**kwargs)


def test_fastmcp_contract_and_structured_output(monkeypatch):
    server = load_server_module("permitting_dashboard")
    api = sys.modules[server.search_permitting_projects.__module__]
    monkeypatch.setattr(api, "_metadata", lambda: STAMP)
    monkeypatch.setattr(api, "get_json_rows", lambda *_a, **_k: _project_rows())

    async def run():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools} == {
                "search_permitting_projects",
                "get_project_permitting_timetable",
                "find_permitting_milestones",
            }
            assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools)
            result = await client.call_tool("get_project_permitting_timetable", {"project_id": "124556"})
            assert result.data["summary"]["returned_action_count"] == 4
            assert result.structured_content is not None
            invalid = await client.call_tool(
                "get_project_permitting_timetable", {"project_id": "1 OR 1=1"}, raise_on_error=False
            )
            assert invalid.is_error

    asyncio.run(run())
