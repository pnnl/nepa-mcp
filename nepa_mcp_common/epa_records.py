"""Evidence and paging conventions for the EPA record lookups."""

import json
from datetime import UTC, datetime


def evidence(**context):
    return dict(context, status="complete", retrieved_at=datetime.now(UTC).isoformat(), sources=[], warnings=[])


def warn(result, message, *, unavailable=False):
    if message not in result["warnings"]:
        result["warnings"].append(message)
    result["status"] = "unavailable" if unavailable else "partial"


def window(limit, offset):
    if not 1 <= limit <= 100 or not 0 <= offset <= 9999:
        raise ValueError("max_results must be 1–100 and result_offset must be 0–9999")


def page(result, rows, limit, offset, *, more):
    result.update(
        records=rows,
        result_offset=offset,
        has_more=more,
        next_offset=offset + limit if more and offset + limit <= 9999 else None,
    )
    if more and offset + limit > 9999:
        warn(result, "Additional records exceed the supported offset.")
    elif not rows and not more and result["status"] == "complete":
        result["status"] = "empty"


def fields(row, names):
    """Project source columns; retain nulls and numeric zero without coercion."""
    return {name: row[name] for name in names.split() if name in row}


def render(result):
    return json.dumps(result, ensure_ascii=False, indent=2)
