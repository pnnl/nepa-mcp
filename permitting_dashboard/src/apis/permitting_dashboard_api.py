"""Bounded read-only queries against the official Permitting Data Portal.

No caller-supplied URL, field name, or SoQL is accepted. Search uses the
publisher's canonical project row; timetables retain action/milestone grain.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from nepa_mcp_common.http import UpstreamServiceError, get_json, get_json_rows
from src.core.constants import (
    ACTION_FIELDS,
    API_URL,
    COVERAGE_NOTE,
    DATASET_ID,
    DATASET_URL,
    EFFECTIVE_TARGET,
    MAX_OFFSET,
    MAX_RESULTS,
    MAX_TIMETABLE_ROWS,
    METADATA_URL,
    MILESTONE_FIELDS,
    MODES,
    PROJECT_FIELDS,
    PROJECT_STATUSES,
    QUERY_TIMEOUT_SECONDS,
    STATES,
)
from src.core.interpretation import interpret_milestone, source_fields


def _today() -> date:
    return datetime.now(UTC).date()


def _integer(value: int, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
        raise ValueError(f"{name} must contain 1 to 160 characters")
    if any(ord(c) < 32 for c in value) or any(c in value for c in "%_\\"):
        raise ValueError(f"{name} cannot contain control characters, backslashes, or SQL LIKE wildcards")
    return value.strip()


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _contains(field: str, value: str) -> str:
    return f"upper({field}) like {_literal('%' + value.upper() + '%')}"


def _project_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        raise ValueError("project_id must be a numeric string of 1 to 20 digits")
    return value


def _date(value: str, name: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date") from exc


def _project_filters(
    *,
    query: str | None = None,
    states: list[str] | None = None,
    sector: str | None = None,
    lead_agency: str | None = None,
    category: str | None = None,
    project_status: str | None = None,
) -> list[str]:
    clauses = []
    for name, field, value in (
        ("query", "project_title", query),
        ("sector", "project_sector", sector),
        ("category", "project_category", category),
    ):
        value = _text(value, name)
        if value is not None:
            clauses.append(_contains(field, value))
    lead_agency = _text(lead_agency, "lead_agency")
    if lead_agency is not None:
        clauses.append(
            f"({_contains('project_field_project_lead_agency', lead_agency)} or "
            f"{_contains('project_field_project_lead_agency_bureau', lead_agency)})"
        )
    if states is not None:
        if not isinstance(states, list) or not 1 <= len(states) <= 10:
            raise ValueError("states must be a list of 1 to 10 US state/territory postal codes")
        if any(not isinstance(s, str) or s.upper() not in STATES for s in states):
            raise ValueError("states must contain valid US state/territory postal codes")
        clauses.append("project_field_location_state in (" + ",".join(_literal(s.upper()) for s in states) + ")")
    if project_status is not None:
        if project_status not in PROJECT_STATUSES:
            raise ValueError(f"project_status must be one of {PROJECT_STATUSES}")
        clauses.append(f"project_field_project_status = {_literal(project_status)}")
    return clauses


def _metadata() -> int:
    data = get_json(METADATA_URL, timeout=QUERY_TIMEOUT_SECONDS, service_name="Permitting Dashboard metadata")
    stamp = data.get("rowsUpdatedAt")
    if data.get("id") != DATASET_ID or type(stamp) is not int or not 0 < stamp < 253402300800:
        raise UpstreamServiceError("Permitting Dashboard metadata has no valid dataset identity/update timestamp")
    return stamp


def _fetch_page(
    clauses: list[str],
    fields: tuple[str, ...],
    order: str,
    max_results: int,
    result_offset: int,
    *,
    cap: int = MAX_RESULTS,
    snapshot_updated_at: int | None = None,
) -> tuple[dict, list[dict]]:
    _integer(max_results, "max_results", 1, cap)
    _integer(result_offset, "result_offset", 0, MAX_OFFSET)
    if snapshot_updated_at is not None:
        _integer(snapshot_updated_at, "snapshot_updated_at", 1, 253402300799)
    result: dict[str, Any] = {
        "status": "unavailable",
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "publisher": "Federal Permitting Data Portal",
            "dataset_id": DATASET_ID,
            "dataset_url": DATASET_URL,
            "api_url": API_URL,
            "metadata_url": METADATA_URL,
            "snapshot_updated_at": None,
            "dataset_rows_updated_at_utc": None,
            "metadata_status": "unavailable",
            "last_data_fetched": [],
        },
        "pagination": {
            "max_results": max_results,
            "result_offset": result_offset,
            "returned_count": 0,
            "has_more": None,
            "next_result_offset": None,
            "listing_complete": False,
        },
        "coverage_note": COVERAGE_NOTE,
        "warnings": [],
    }
    warnings = result["warnings"]
    stamp = None
    try:
        stamp = _metadata()
        updated = datetime.fromtimestamp(stamp, UTC)
        result["source"].update(
            snapshot_updated_at=stamp, dataset_rows_updated_at_utc=updated.isoformat(), metadata_status="ok"
        )
        if datetime.now(UTC) - updated > timedelta(days=7):
            warnings.append("Dataset refresh is more than seven days old; individual agency entries may be older.")
    except UpstreamServiceError as exc:
        warnings.append(str(exc))
    if snapshot_updated_at is not None and stamp != snapshot_updated_at:
        result["error"] = "Snapshot changed or cannot be verified. Restart pagination without snapshot_updated_at."
        return result, []
    params = {
        "$select": ",".join(dict.fromkeys(fields + ("last_data_fetched",))),
        "$where": " and ".join(clauses) or "1=1",
        "$order": order,
        "$limit": max_results + 1,
        "$offset": result_offset,
    }
    result["query_parameters"] = params
    try:
        rows = get_json_rows(API_URL, params=params, timeout=QUERY_TIMEOUT_SECONDS, service_name="Permitting Dashboard")
        if len(rows) > max_results + 1 or any(not r.get("project_id") for r in rows):
            raise UpstreamServiceError(
                "Permitting Dashboard returned invalid project rows or exceeded the requested limit"
            )
    except UpstreamServiceError as exc:
        result["error"] = str(exc)
        return result, []
    try:
        after = _metadata()
        if stamp is None or after != stamp:
            warnings.append("Dataset changed during retrieval or its initial snapshot could not be verified.")
    except UpstreamServiceError as exc:
        warnings.append(f"Final snapshot check failed: {exc}")
    has_more = len(rows) > max_results
    rows = rows[:max_results]
    fetches = sorted({str(r["last_data_fetched"]) for r in rows if r.get("last_data_fetched")})
    result["source"]["last_data_fetched"] = fetches
    if len(fetches) > 1:
        warnings.append("Returned rows have different export fetch timestamps.")
    if any(not r.get("last_data_fetched") for r in rows):
        warnings.append("Some returned rows lack an export fetch timestamp.")
    next_offset = result_offset + len(rows) if has_more else None
    if next_offset is not None and next_offset > MAX_OFFSET:
        next_offset = None
        warnings.append("Pagination safety cap reached; narrow the search filters.")
    result["pagination"].update(
        returned_count=len(rows),
        has_more=has_more,
        next_result_offset=next_offset,
        listing_complete=not has_more and result_offset == 0 and not warnings,
    )
    result["status"] = "partial" if warnings else "truncated" if has_more else "ok" if rows else "empty"
    return result, rows


def search_permitting_projects(
    query: str | None = None,
    states: list[str] | None = None,
    sector: str | None = None,
    lead_agency: str | None = None,
    category: str | None = None,
    project_status: str | None = None,
    max_results: int = 25,
    result_offset: int = 0,
    snapshot_updated_at: int | None = None,
) -> dict:
    clauses = ["project_canonical = true"] + _project_filters(
        query=query,
        states=states,
        sector=sector,
        lead_agency=lead_agency,
        category=category,
        project_status=project_status,
    )
    result, rows = _fetch_page(
        clauses,
        PROJECT_FIELDS,
        "project_id ASC,unique_id ASC",
        max_results,
        result_offset,
        snapshot_updated_at=snapshot_updated_at,
    )
    projects = {}
    for row in rows:
        projects.setdefault(row["project_id"], source_fields(row, PROJECT_FIELDS))
    result["projects"] = list(projects.values())
    if len(projects) != len(rows):
        result["warnings"].append("Duplicate canonical project rows detected; displayed projects were deduplicated.")
        result["status"] = "partial"
        result["pagination"]["listing_complete"] = False
    result["project_count"] = len(projects)
    return result


def get_project_permitting_timetable(
    project_id: str,
    max_results: int = 500,
    result_offset: int = 0,
    snapshot_updated_at: int | None = None,
) -> dict:
    project_id = _project_id(project_id)
    fields = PROJECT_FIELDS + ACTION_FIELDS + MILESTONE_FIELDS
    result, rows = _fetch_page(
        [f"project_id = {_literal(project_id)}"],
        fields,
        "action_id ASC,unique_id ASC",
        max_results,
        result_offset,
        cap=MAX_TIMETABLE_ROWS,
        snapshot_updated_at=snapshot_updated_at,
    )
    result.update(project=None, actions=[], as_of_date=_today().isoformat(), summary_scope="returned_page")
    if not rows:
        return result
    result["project"] = source_fields(rows[0], PROJECT_FIELDS)
    actions = {}
    seen = set()
    for row in rows:
        if source_fields(row, PROJECT_FIELDS) != result["project"]:
            result["warnings"].append("Conflicting project fields across milestone rows; first row shown.")
        action_id = row.get("action_id")
        if not action_id:
            result["warnings"].append("Project row has no tracked action ID.")
            continue
        action = actions.setdefault(action_id, {**source_fields(row, ACTION_FIELDS), "milestones": []})
        if source_fields(row, ACTION_FIELDS) != {key: action[key] for key in ACTION_FIELDS}:
            result["warnings"].append(f"Conflicting fields for action {action_id}; first row shown.")
        milestone_id = row.get("milestone_id")
        if not milestone_id:
            result["warnings"].append(f"Action {action_id} has a row without a milestone ID.")
            continue
        key = (action_id, milestone_id)
        if key in seen:
            result["warnings"].append(f"Duplicate milestone {milestone_id} in action {action_id}; first row shown.")
            continue
        seen.add(key)
        action["milestones"].append(interpret_milestone(row, _today()))
    result["actions"] = list(actions.values())
    result["summary"] = {
        "returned_action_count": len(actions),
        "returned_milestone_count": len(seen),
        "action_status_counts": dict(Counter(a["action_status"] for a in actions.values())),
        "milestones_with_quality_warnings": sum(bool(m["warnings"]) for a in actions.values() for m in a["milestones"]),
    }
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    if result["warnings"]:
        result["status"] = "partial"
        result["pagination"]["listing_complete"] = False
    if result["pagination"]["listing_complete"]:
        result["summary_scope"] = "complete_project_export"
    return result


def find_permitting_milestones(
    mode: str = "upcoming",
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: str | None = None,
    states: list[str] | None = None,
    sector: str | None = None,
    agency: str | None = None,
    action_type: str | None = None,
    project_status: str | None = None,
    max_results: int = 25,
    result_offset: int = 0,
    snapshot_updated_at: int | None = None,
) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    today = _today()
    start = (
        _date(date_from, "date_from")
        if date_from is not None
        else (
            today
            if mode == "upcoming"
            else today - timedelta(days=30)
            if mode == "recently_completed"
            else date(1900, 1, 1)
        )
    )
    end = (
        _date(date_to, "date_to")
        if date_to is not None
        else (
            today + timedelta(days=30)
            if mode == "upcoming"
            else today
            if mode == "recently_completed"
            else today - timedelta(days=1)
        )
    )
    if (
        start > end
        or (mode == "upcoming" and start < today)
        or (mode == "recently_completed" and end > today)
        or (mode == "past_target" and end >= today)
    ):
        raise ValueError("Date window must be ordered and match the mode relative to today's UTC date")
    clauses = ["milestone_id is not null", "action_milestone_na = false"]
    clauses += _project_filters(states=states, sector=sector, project_status=project_status)
    if project_id is not None:
        clauses.append(f"project_id = {_literal(_project_id(project_id))}")
    for name, field, value in (("agency", "action_agency", agency), ("action_type", "action_type", action_type)):
        value = _text(value, name)
        if value is not None:
            clauses.append(_contains(field, value))
    if mode == "recently_completed":
        date_field = "action_milestone_completion_actual"
        clauses.append("action_milestone_complete = true")
    else:
        date_field = EFFECTIVE_TARGET
        clauses += [
            "action_milestone_complete = false",
            "action_milestone_completion_actual is null",
            "action_status in ('In Progress','Planned')",
            "project_field_project_status in ('In Progress','Planned')",
        ]
    clauses += [
        f"{date_field} >= {_literal(start.isoformat() + 'T00:00:00.000')}",
        f"{date_field} <= {_literal(end.isoformat() + 'T23:59:59.999')}",
    ]
    order = f"{date_field} {'DESC' if mode == 'recently_completed' else 'ASC'},unique_id ASC"
    result, rows = _fetch_page(
        clauses,
        PROJECT_FIELDS + ACTION_FIELDS + MILESTONE_FIELDS,
        order,
        max_results,
        result_offset,
        snapshot_updated_at=snapshot_updated_at,
    )
    result.update(
        mode=mode,
        as_of_date=today.isoformat(),
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        date_basis="actual_completion" if mode == "recently_completed" else "alternative_then_target",
        milestones=[
            {
                "project": source_fields(r, PROJECT_FIELDS),
                "action": source_fields(r, ACTION_FIELDS),
                "milestone": interpret_milestone(r, today),
            }
            for r in rows
        ],
    )
    result["interpretation_note"] = (
        "Past target means reported date has passed and milestone remains incomplete; it is not a confirmed delay. "
        "Upcoming/past-target searches exclude paused, cancelled, completed and unclassified projects/actions, "
        "not-applicable milestones, and milestones with actual dates. Timetable lookup retains all source rows."
    )
    return result
