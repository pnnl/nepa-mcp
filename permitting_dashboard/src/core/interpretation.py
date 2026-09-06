"""Conservative milestone interpretation; source values are never overwritten."""

from datetime import date, datetime
from typing import Any

from src.core.constants import MILESTONE_FIELDS


def source_fields(row: dict, fields: tuple[str, ...]) -> dict[str, Any]:
    """Preserve exact labels, strings and booleans; absent fields become JSON null."""
    return {field: row.get(field) for field in fields}


def interpret_milestone(row: dict, as_of: date) -> dict:
    result = source_fields(row, MILESTONE_FIELDS)
    warnings = []
    dates = {}
    for field in (
        "action_milestone_baseline_target",
        "action_milestone_completion_target",
        "milestone_alternative_completion_date",
        "action_milestone_completion_actual",
    ):
        value = row.get(field)
        dates[field] = None
        if value not in (None, ""):
            try:
                dates[field] = datetime.fromisoformat(value).date()
            except (ValueError, TypeError):
                warnings.append(f"invalid_date:{field}")
    alternative = row.get("milestone_alternative_completion_date")
    target_field = (
        "milestone_alternative_completion_date"
        if alternative not in (None, "")
        else "action_milestone_completion_target"
    )
    target = dates[target_field]
    baseline = dates["action_milestone_baseline_target"]
    actual = dates["action_milestone_completion_actual"]
    complete, na = row.get("action_milestone_complete"), row.get("action_milestone_na")
    for field in ("action_milestone_complete", "action_milestone_na"):
        if type(row.get(field)) is not bool:
            warnings.append(f"unknown_or_invalid_flag:{field}")
    if actual and actual > as_of:
        warnings.append("future_actual_completion_date")
    if complete is True and not actual:
        warnings.append("complete_without_valid_actual_date")
    if complete is False and row.get("action_milestone_completion_actual") not in (None, ""):
        warnings.append("incomplete_with_actual_date")
    if na is True and (actual or complete is True):
        warnings.append("not_applicable_with_completion")
    if na is True:
        status = "not_applicable"
    elif warnings:
        status = "inconsistent_or_unknown"
    elif complete is True:
        status = "completed"
    elif row.get("action_status") in (
        "Complete",
        "Cancelled",
        "Class of Action Changed",
        "No Longer Required to be Tracked",
    ):
        status = "inactive_action"
    elif row.get("project_field_project_status") in ("Complete", "Cancelled", "Class of Action Changed"):
        status = "inactive_project"
    elif row.get("action_status") == "Paused" or row.get("project_field_project_status") == "Paused":
        status = "paused"
    elif target is None:
        status = "unscheduled"
    elif target < as_of:
        status = "past_target_incomplete"
    else:
        status = "scheduled"
    result.update(
        effective_target_date=target.isoformat() if target else None,
        effective_target_source=target_field if target else None,
        target_shift_days=(target - baseline).days if target and baseline else None,
        interpreted_status=status,
        warnings=warnings,
    )
    return result
