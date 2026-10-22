"""Pure validation, normalization, sanitizing, and parsing helpers for EPA Superfund sources.

Nothing here performs network I/O. Raw source values are preserved beside every
normalized value so a reader can always see what the publisher actually said.
"""

from __future__ import annotations

import html
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from src.core.sources import (
    CODE_STATUS,
    FEDERAL_FACILITY_LABELS,
    FRS_STATUS_TEXT,
    NPL_STATUS_CODE_LABELS,
    NPL_STATUS_VALUES,
    POINT_STATUS_TEXT,
    STATE_CODES_BY_NAME,
    STATE_NAMES,
)

# =============================================================================
# SOURCE STATES
# =============================================================================

SOURCE_STATES = ("complete", "empty", "partial", "truncated", "failed", "unsupported", "skipped")


@dataclass
class SourceReport:
    """Retrieval state of one source for one tool call, independent of every other source."""

    key: str
    label: str
    status: str
    record_count: int = 0
    note: str = ""
    url: str | None = None
    retrieved_at: str | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SOURCE_STATES:
            raise ValueError(f"unknown source status {self.status!r}")

    @property
    def usable(self) -> bool:
        return self.status in {"complete", "empty", "partial", "truncated"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fingerprint(value: Any) -> str:
    """Hash ordered evidence, not retrieval timestamps or cache bookkeeping."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=asdict)
    return hashlib.sha256(payload.encode()).hexdigest()


# =============================================================================
# IDENTIFIERS AND ARGUMENTS
# =============================================================================

EPA_ID_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
SEMS_ID_RE = re.compile(r"^\d{1,7}$")
FRS_REGISTRY_RE = re.compile(r"^\d{12}$")
OU_ID_RE = re.compile(r"^\d{1,2}$")
QUERY_RE = re.compile(r"^(?=.*[A-Za-z0-9])[A-Za-z0-9 .,'&()/#-]{2,100}$")
MEDIA_RE = re.compile(r"^[A-Za-z /()-]{2,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INVENTORY_SCOPES = ("npl_and_mapped", "sems_candidates")
DOCUMENT_TYPES = (
    "record_of_decision",
    "rod_amendment",
    "explanation_of_significant_differences",
    "five_year_review",
    "proposed_plan",
    "institutional_controls",
    "deletion",
    "federal_register_notice",
    "listing_narrative",
    "community_involvement",
    "fact_sheet",
    "close_out_report",
    "correspondence",
    "other",
)


def validate_epa_id(value: Any) -> str:
    text = value.strip().upper() if isinstance(value, str) else ""
    if not EPA_ID_RE.fullmatch(text):
        raise ValueError(
            "epa_id must be an EPA site identifier such as NJD063157150 (2 letters then 10 letters or digits)"
        )
    return text


def validate_sems_id(value: Any) -> str:
    """Return a 7-character, zero-padded SEMS site identifier; numeric stripping would break lookups."""
    text = value.strip() if isinstance(value, str) else ""
    if not SEMS_ID_RE.fullmatch(text):
        raise ValueError("sems_id must be a numeric SEMS site identifier of 1 to 7 digits, such as 0200397")
    return text.zfill(7)


def validate_frs_registry_id(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not FRS_REGISTRY_RE.fullmatch(text):
        raise ValueError("frs_registry_id must be a 12-digit FRS registry identifier")
    return text


def validate_operable_unit(value: Any) -> str | None:
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else ""
    if not OU_ID_RE.fullmatch(text):
        raise ValueError("operable_unit must be a 1-2 digit OU identifier such as 01 or 00")
    return text.zfill(2)


def validate_query(value: Any, name: str = "query") -> str | None:
    if value is None:
        return None
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if not QUERY_RE.fullmatch(text):
        raise ValueError(f"{name} must be 2-100 letters, digits, spaces, or . , ' & ( ) / # -")
    return text


def validate_state(value: Any) -> str | None:
    if value is None:
        return None
    text = value.strip().upper() if isinstance(value, str) else ""
    if text not in STATE_NAMES:
        raise ValueError("state must be a US state or territory postal code such as NJ")
    return text


def validate_npl_status(value: Any) -> str | None:
    if value is None:
        return None
    if value not in NPL_STATUS_VALUES:
        raise ValueError(f"npl_status must be one of: {', '.join(NPL_STATUS_VALUES)}")
    return value


def validate_scope(value: Any) -> str:
    if value not in INVENTORY_SCOPES:
        raise ValueError(f"inventory_scope must be one of: {', '.join(INVENTORY_SCOPES)}")
    return value


def validate_media(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if not MEDIA_RE.fullmatch(text):
        raise ValueError("media must be a SEMS media name such as Groundwater or Soil")
    return text


def validate_document_type(value: Any) -> str | None:
    if value is None:
        return None
    if value not in DOCUMENT_TYPES:
        raise ValueError(f"document_type must be one of: {', '.join(DOCUMENT_TYPES)}")
    return value


def validate_date(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError(f"{name} must be a YYYY-MM-DD date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date") from exc
    return value


def state_code_from_name(name: Any) -> str | None:
    return STATE_CODES_BY_NAME.get(name.strip().casefold()) if isinstance(name, str) else None


# =============================================================================
# TEXT, MARKUP, AND LINKS
# =============================================================================

_TAG_RE = re.compile(r"<[A-Za-z/!][^<>]{0,2000}>")
_CONTROL_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"([\\`*_\[\]|<>#@])")
_SCHEME_RE = re.compile(r"\b(https?|ftp|javascript|data|mailto):", re.IGNORECASE)
_URL_SAFE_RE = re.compile(r"^[A-Za-z0-9._~:/?#&=%+,;-]+$")


def text(value: Any) -> str | None:
    """Return stripped source text with tags and entities removed, or None when blank."""
    if value is None:
        return None
    cleaned = " ".join(_CONTROL_RE.sub("", html.unescape(_TAG_RE.sub(" ", str(value)))).split())
    return cleaned or None


def clip(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def md(value: Any, limit: int = 300) -> str:
    """Render untrusted source text as inert Markdown (no tags, links, tables, or emphasis)."""
    cleaned = clip(text(value), limit) or ""
    # Escaping the scheme colon keeps the text readable but stops renderers from auto-linking it.
    escaped = _SCHEME_RE.sub(r"\1\\:", _MARKDOWN_RE.sub(r"\\\1", cleaned))
    return re.sub(r"(?i)\bwww\.", r"www\\.", escaped)


def extract_href(value: Any) -> str | None:
    match = _HREF_RE.search(html.unescape(str(value))) if value else None
    return match.group(1).strip() if match else None


def epa_url(value: Any) -> str | None:
    """Return the URL only when it is an https link on an EPA-owned host; never emit other links."""
    if not isinstance(value, str):
        return None
    candidate = html.unescape(value).strip()
    if candidate.startswith("www.epa.gov/") or candidate.startswith("semspub.epa.gov/"):
        candidate = "https://" + candidate
    if len(candidate) > 500 or not _URL_SAFE_RE.fullmatch(candidate):
        return None
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").casefold()
    if parts.scheme != "https" or parts.username or parts.password or port:
        return None
    if host != "epa.gov" and not host.endswith(".epa.gov"):
        return None
    return candidate


def link(label: Any, url: str | None, limit: int = 120) -> str:
    """Markdown link for a validated EPA URL, else the inert label."""
    rendered = md(label, limit) or "link"
    return f"[{rendered}]({url.replace('(', '%28').replace(')', '%29')})" if url else rendered


def parse_linked_field(value: Any) -> dict[str, str | None]:
    """Split an HTML-bearing link field into visible text and a validated EPA URL."""
    href = extract_href(value)
    url = epa_url(href) if href else epa_url(value)
    return {"text": text(value), "url": url}


def parse_partial_deletion(value: Any) -> dict[str, str | None]:
    """The point layer publishes a plain 'No' or an HTML anchor around 'Yes'; neither is a Boolean field."""
    visible = (text(value) or "").casefold()
    state = "yes" if visible == "yes" else "no" if visible == "no" else "unknown"
    href = extract_href(value)
    return {"value": state, "raw": clip(text(value), 200), "url": epa_url(href) if href else None}


# =============================================================================
# LISTING STATUS
# =============================================================================


@dataclass(frozen=True)
class NplStatus:
    normalized: str
    raw: str | None
    label: str | None
    source: str
    source_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_npl_status(raw: Any, source: str, source_date: str | None = None) -> NplStatus:
    """Map a source-specific status to the shared vocabulary without discarding the raw value."""
    raw_text = raw.strip() if isinstance(raw, str) else None
    raw_text = raw_text or None
    key = (raw_text or "").casefold()
    if source == "npl_points":
        normalized, label = POINT_STATUS_TEXT.get(key, "unknown"), raw_text
    elif source == "frs_sems":
        normalized, label = FRS_STATUS_TEXT.get(key, "unknown"), raw_text
    else:
        code = (raw_text or "").upper()
        normalized, label = CODE_STATUS.get(code, "unknown"), NPL_STATUS_CODE_LABELS.get(code)
    return NplStatus(normalized=normalized, raw=raw_text, label=label, source=source, source_date=source_date)


def status_conflict(statuses: list[NplStatus]) -> bool:
    return len({status.normalized for status in statuses if status.normalized != "unknown"}) > 1


def raw_status_values(normalized: str, source: str) -> list[str]:
    """Inverse status map for where-clauses; an empty list means the source cannot express that status."""
    if source == "npl_points":
        table = POINT_STATUS_TEXT
        return [raw for raw, value in table.items() if value == normalized and raw]
    if source == "frs_sems":
        return [raw.upper() for raw, value in FRS_STATUS_TEXT.items() if value == normalized]
    return [code for code, value in CODE_STATUS.items() if value == normalized]


def federal_facility(code: Any) -> dict[str, str | None]:
    raw = code.strip().upper() if isinstance(code, str) and code.strip() else None
    return {"raw": raw, "label": FEDERAL_FACILITY_LABELS.get(raw or "")}


# =============================================================================
# DATES
# =============================================================================

_MDY_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_mdy(value: Any) -> str | None:
    match = _MDY_RE.fullmatch(value.strip()) if isinstance(value, str) else None
    return _iso(int(match.group(3)), int(match.group(1)), int(match.group(2))) if match else None


def mdy_field(value: Any) -> dict[str, str | None]:
    raw = value.strip() if isinstance(value, str) and value.strip() else None
    return {"raw": raw, "iso": parse_mdy(raw)}


def epoch_ms_field(value: Any) -> dict[str, Any]:
    """ArcGIS dates are UTC epoch milliseconds; a missing date stays missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return {"raw": None, "iso": None}
    try:
        iso = datetime.fromtimestamp(value / 1000, UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        iso = None
    return {"raw": value, "iso": iso}


def dmap_timestamp_field(value: Any) -> dict[str, str | None]:
    raw = value.strip() if isinstance(value, str) and value.strip() else None
    iso = None
    if raw:
        try:
            parsed = datetime.fromisoformat(raw).date()
            iso = parsed.isoformat() if parsed.year >= 1900 else None
        except ValueError:
            iso = None
    return {"raw": raw, "iso": iso}


# =============================================================================
# COORDINATES
# =============================================================================


def coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def distance_miles(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance in statute miles; longitude wrap is handled by the haversine form."""
    lat_a_rad, lat_b_rad = math.radians(lat_a), math.radians(lat_b)
    delta_lat, delta_lon = math.radians(lat_b - lat_a), math.radians(lon_b - lon_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a_rad) * math.cos(lat_b_rad) * math.sin(delta_lon / 2) ** 2
    return 3958.7613 * 2 * math.asin(min(1.0, math.sqrt(value)))


def polygon_distance_miles(lat: float, lon: float, rings: Any) -> tuple[float | None, str]:
    """Return 0 when a WGS84 ring contains the point, else distance to the nearest generalized vertex."""
    from shapely.geometry import Point, Polygon

    if not isinstance(rings, list):
        return None, "no_geometry"
    nearest = None
    containing = 0  # even-odd rule: a point inside a hole ring is outside the polygon
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            continue
        vertices = [
            (float(vertex[0]), float(vertex[1]))
            for vertex in ring
            if isinstance(vertex, (list, tuple))
            and len(vertex) >= 2
            and coordinate(vertex[0], -180, 180) is not None
            and coordinate(vertex[1], -90, 90) is not None
        ]
        if len(vertices) < 4:
            continue
        # Unwrap each ring across the date line, then place the query in the same longitude interval.
        unwrapped = [vertices[0]]
        for x, y in vertices[1:]:
            x += 360 * round((unwrapped[-1][0] - x) / 360)
            unwrapped.append((x, y))
        center_x = sum(x for x, _ in unwrapped) / len(unwrapped)
        point = Point(lon + 360 * round((center_x - lon) / 360), lat)
        try:
            polygon = Polygon(unwrapped)
            if polygon.boundary.covers(point):
                return 0.0, "inside_site_polygon"
            containing += polygon.contains(point)
        except ValueError:
            pass
        for x, y in vertices:
            miles = distance_miles(lat, lon, y, x)
            nearest = miles if nearest is None or miles < nearest else nearest
    if containing % 2:
        return 0.0, "inside_site_polygon"
    if nearest is None:
        return None, "no_geometry"
    return nearest, "nearest_polygon_vertex_approximate"


def normalize_name(value: Any) -> str:
    """Comparison key for names: casefolded words without punctuation or a trailing 'superfund site'."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (text(value) or "").casefold())
    cleaned = re.sub(r"\b(superfund|site|the|inc|co|corp|corporation|company)\b", " ", cleaned)
    return " ".join(cleaned.split())


@dataclass
class Page:
    """Bounded pagination over a complete, deterministically ordered list."""

    items: list[Any]
    offset: int
    limit: int
    total: int = field(init=False)

    def __post_init__(self) -> None:
        self.total = len(self.items)

    @property
    def end(self) -> int:
        return min(self.offset + self.limit, self.total)

    @property
    def window(self) -> list[Any]:
        return self.items[self.offset : self.end]
