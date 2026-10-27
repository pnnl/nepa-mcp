"""Typed APS v1.0 query construction; no arbitrary upstream field/operator inputs."""

import re
from datetime import date

DATE_FIELDS = {"document_date": "DocumentDate", "date_added": "DateAddedTimestamp"}
SORT_FIELDS = {**DATE_FIELDS, "accession_number": "AccessionNumber", "title": "DocumentTitle"}


def integer(value, name, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer from {lo} to {hi}")
    return value


def text(value, name, limit=2000, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"{name} must contain printable text, at most {limit} characters")
    return value.strip()


def accession(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", value):
        raise ValueError(
            "accession_number must be a bounded accession identifier, not a URL, docket expression, or path"
        )
    return value.upper() if value.lower().startswith("ml") else value


def page(max_results, result_offset):
    integer(max_results, "max_results", 1, 100)
    integer(result_offset, "result_offset", 0, 100000)


def iso(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def build(
    query="",
    docket_number=None,
    document_type=None,
    date_basis="document_date",
    date_from=None,
    date_to=None,
    library="both",
    sort_by="document_date",
    sort_direction="descending",
    max_results=50,
    result_offset=0,
):
    page(max_results, result_offset)
    query = text(query, "query", empty=True)
    if date_basis not in DATE_FIELDS:
        raise ValueError("date_basis must be document_date or date_added")
    if library not in {"main", "legacy", "both"}:
        raise ValueError("library must be main, legacy, or both")
    if sort_by not in SORT_FIELDS:
        raise ValueError(f"sort_by must be one of {tuple(SORT_FIELDS)}")
    if sort_direction not in {"ascending", "descending"}:
        raise ValueError("sort_direction must be ascending or descending")
    filters = []
    if docket_number is not None:
        # No guessed padding, reactor assumption, or lossy numeric conversion.
        docket_number = text(docket_number, "docket_number", 32)
        if not re.fullmatch(r"[0-9]{1,20}", docket_number):
            raise ValueError(
                "docket_number must be an exact numeric string as published by NRC; leading zeros are preserved"
            )
        filters.append({"field": "DocketNumber", "operator": "equals", "value": docket_number})
    if document_type is not None:
        filters.append(
            {"field": "DocumentType", "operator": "equals", "value": text(document_type, "document_type", 160)}
        )
    if date_from is not None:
        iso(date_from, "date_from")
    if date_to is not None:
        iso(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from cannot follow date_to")
    field = DATE_FIELDS[date_basis]
    for value, operator in [(date_from, "ge"), (date_to, "le")]:
        if value:
            filters.append({"field": field, "value": f"({field} {operator} '{value}')"})
    if not query and not filters:
        raise ValueError("Provide a query or a substantive docket, document type, or date filter")
    return {
        "q": query,
        "filters": filters,
        "anyFilters": [],
        "mainLibFilter": library in {"main", "both"},
        "legacyLibFilter": library in {"legacy", "both"},
        "sort": SORT_FIELDS[sort_by],
        "sortDirection": int(sort_direction == "descending"),
        "skip": result_offset,
    }
