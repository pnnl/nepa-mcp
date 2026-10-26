"""Typed identity and source-preserving normalization."""

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit


def now():
    return datetime.now(UTC).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{4}", value.upper()):
        raise ValueError("property_number must be a public FUDS number, such as A04MS0002")
    return value.upper()


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def page_args(max_results, result_offset):
    integer(max_results, "max_results", 1, 100)
    integer(result_offset, "result_offset", 0, 100000)


def geo(latitude, longitude, buffer_miles=25):
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
    return latitude, longitude, buffer_miles


def yes_no(value):
    if value is None:
        return {"raw": None, "value": None, "state": "missing"}
    code = str(value).lower()
    return {
        "raw": value,
        "value": {"yes": True, "no": False}.get(code),
        "state": "known" if code in {"yes", "no"} else "unknown" if code == "tbd" else "unrecognized",
    }


def official_link(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        if (
            p.scheme == "https"
            and (p.hostname == "usace.army.mil" or (p.hostname or "").endswith(".usace.army.mil"))
            and not p.username
            and not p.password
            and p.port in {None, 443}
        ):
            return value
    except ValueError:
        return None
    return None


def epoch_date(value):
    result = {"raw": value, "date_utc": None, "temporal_role": "not established by source field"}
    if value is None:
        return result
    if type(value) not in {int, float} or not math.isfinite(value):
        return {**result, "warning": "invalid source date"}
    try:
        result["date_utc"] = datetime.fromtimestamp(value / 1000, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        result["warning"] = "invalid source date"
    return result


def coded_values(attributes, layer):
    from pathlib import Path

    domains = json.loads(Path(__file__).with_name("domains.json").read_text())[str(layer)]
    return {
        field: {
            "raw": attributes.get(field),
            "label": codes.get(str(attributes.get(field))),
            "state": "missing"
            if attributes.get(field) is None
            else "known"
            if str(attributes[field]) in codes
            else "unrecognized",
        }
        for field, codes in domains.items()
        if field in attributes
    }
