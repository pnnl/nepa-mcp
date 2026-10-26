"""Validation and bounded result envelopes."""

import hashlib
import json
import math
from datetime import UTC, datetime
from urllib.parse import urlsplit
from src.core.sources import MANIFEST, NOTE


def now():
    return datetime.now(UTC).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def text(value, name, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must contain 1–160 printable characters")
    return value.strip()


def integer(value, name, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer from {lo} to {hi}")


def page(max_results, result_offset):
    integer(max_results, "max_results", 1, 100)
    integer(result_offset, "result_offset", 0, 100000)


def geo(latitude, longitude, buffer_miles):
    for value, name, lo, hi in [
        (latitude, "latitude", -90, 90),
        (longitude, "longitude", -180, 180),
        (buffer_miles, "buffer_miles", 0.1, 100),
    ]:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not lo <= value <= hi
        ):
            raise ValueError(f"{name} must be numeric from {lo} to {hi}")


def source_url(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.port not in {None, 443}:
            return None
        host = p.hostname
        allowed = host in {
            "www.denix.osd.mil",
            "www.bracpmo.navy.mil",
            "www.afcec.af.mil",
            "www.nae.usace.army.mil",
            "gispub.epa.gov",
            "services.arcgis.com",
            "www.realestatesales.gov",
            "www.nrc.gov",
        }
        return value if allowed else None
    except ValueError:
        return None


def output(records, reports, warnings=None, max_results=100, result_offset=0, **extra):
    page(max_results, result_offset)
    complete = bool(reports) and all(r.get("complete", False) for r in reports)
    selected = records[result_offset : result_offset + max_results]
    more = result_offset + len(selected) < len(records)
    return {
        "status": "unavailable"
        if reports and all(r["status"] in {"unavailable", "restricted", "unsupported", "schema_error"} for r in reports)
        else "partial"
        if not complete or warnings
        else "ok"
        if records
        else "empty",
        "records": selected,
        "sources": reports,
        "warnings": warnings or [],
        "retrieved_at": now(),
        "source_manifest": MANIFEST,
        "coverage_note": NOTE,
        "result_fingerprint": fingerprint(
            {"records": records, "sources": [(r.get("url"), r["status"]) for r in reports]}
        ),
        "pagination": {
            "max_results": max_results,
            "result_offset": result_offset,
            "returned_count": len(selected),
            "total": len(records),
            "total_kind": "exact_within_retrieved_scope" if complete else "lower_bound",
            "has_more": more if complete or more else None,
            "next_result_offset": result_offset + len(selected) if more else None,
            "retrieval_complete": complete,
            "snapshot_guaranteed": False,
        },
        **extra,
    }
