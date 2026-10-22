"""Bounded upstream adapters for EPA Superfund sources.

Each adapter returns ``(records, SourceReport)`` and never raises for an
upstream failure: the real error is logged, and the public report says the
source was unavailable rather than empty. Validation errors propagate.

The network boundaries are ``ArcGISService.query_object_ids`` and
``query_features`` (the five ArcGIS layers), ``get_json_rows`` (Envirofacts DMAP), and ``get_json`` (the
Federal Register API). EPA's site-profile and search pages are never fetched
because EPA's robots.txt disallows automated access to them.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.http import get_json, get_json_rows
from src.core.normalization import (
    EPA_ID_RE,
    FRS_REGISTRY_RE,
    SourceReport,
    coordinate,
    dmap_timestamp_field,
    epa_url,
    epoch_ms_field,
    federal_facility,
    fingerprint,
    mdy_field,
    normalize_npl_status,
    now_utc,
    parse_linked_field,
    parse_partial_deletion,
    state_code_from_name,
    text,
)
from src.core.sources import (
    ARCGIS_MAX_ATTEMPTS,
    ARCGIS_ID_BATCH_SIZE,
    ARCGIS_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    DMAP_BASE,
    DMAP_CONTAMINANT_FIELDS,
    DMAP_CONTAMINANTS_TABLE,
    DMAP_SITE_FIELDS,
    DMAP_SITE_TABLE,
    DMAP_TIMEOUT_SECONDS,
    DMAP_UNSAFE_CHARACTERS,
    EPA_PROGRAM_DOMAIN,
    FEDERAL_REGISTER_FIELDS,
    FEDERAL_REGISTER_MAX_RESULTS,
    FEDERAL_REGISTER_TIMEOUT_SECONDS,
    FEDERAL_REGISTER_URL,
    FRS_SEMS,
    NPL_POINTS,
    SITE_FEATURE_CLASS_LABELS,
    CACHE_SECONDS,
    HEADERS,
    Budget,
    LayerSpec,
)

logger = logging.getLogger(__name__)

POLYGON_LAYERS = frozenset({"site_boundaries", "ou_boundaries", "ic_boundaries"})
SKIPPED_NOTE = "Not queried: the tool's time budget was exhausted before this source was reached."


_CACHE: dict[tuple, tuple[float, Any, str]] = {}


def _cached(key: tuple, fetch):
    """Reuse an identical successful read for CACHE_SECONDS; failures are never cached."""
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2], True
    value = fetch()
    if len(_CACHE) > 256:
        _CACHE.clear()
    retrieved_at = now_utc()
    _CACHE[key] = (time.monotonic(), value, retrieved_at)
    return value, retrieved_at, False


def _failed(key: str, label: str, note: str, url: str | None = None) -> SourceReport:
    return SourceReport(key, label, "failed", note=note, url=url, retrieved_at=now_utc())


# =============================================================================
# ARCGIS
# =============================================================================


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_like(field: str, term: str) -> str:
    """Case-insensitive substring match; validated terms contain no LIKE wildcards."""
    return f"UPPER({field}) LIKE {sql_literal('%' + term.upper() + '%')}"


def sql_in(field: str, values: list[str]) -> str:
    return f"{field} IN ({', '.join(sql_literal(value) for value in values)})"


def query_layer(
    spec: LayerSpec,
    *,
    where: str,
    budget: Budget,
    max_features: int,
    geometry: dict[str, Any] | None = None,
    return_geometry: bool = False,
) -> tuple[list[dict[str, Any]], SourceReport]:
    """Select IDs once, fetch bounded batches, and flag changes without claiming an atomic snapshot."""
    if not budget.allows(ARCGIS_TIMEOUT_SECONDS * ARCGIS_MAX_ATTEMPTS):
        return [], SourceReport(spec.key, spec.label, "skipped", note=SKIPPED_NOTE, url=spec.layer_url)
    extra: dict[str, Any] = {"where": where, "orderByFields": f"{spec.oid_field} ASC"}
    if return_geometry and spec.key in POLYGON_LAYERS:
        # Generalize polygon output; containment and distance only need ~50 m fidelity.
        extra.update({"maxAllowableOffset": 0.0005, "geometryPrecision": 6})

    def ids():
        if not budget.allows(ARCGIS_TIMEOUT_SECONDS * ARCGIS_MAX_ATTEMPTS):
            raise RuntimeError("ID query budget exhausted")
        return ArcGISService.query_object_ids(
            spec.url,
            spec.layer_id,
            geometry,
            where=where,
            timeout=budget.timeout(ARCGIS_TIMEOUT_SECONDS, requests=ARCGIS_MAX_ATTEMPTS),
            max_attempts=ARCGIS_MAX_ATTEMPTS,
            simplify_geometry=False,
            service_name=spec.label,
            headers=HEADERS,
            allow_redirects=False,
        )

    try:
        object_ids = ids()
    except Exception as exc:  # noqa: BLE001 - every upstream failure becomes a reported state
        logger.error("%s query failed: %s", spec.label, exc)
        return [], _failed(
            spec.key, spec.label, f"{spec.label} query failed; unavailable, not a no-hit finding.", spec.layer_url
        )

    selected = object_ids[:max_features]
    features_by_id: dict[int, dict[str, Any]] = {}
    truncated, partial = len(object_ids) > max_features, False
    notes = []
    if truncated:
        notes.append(f"Reached the {max_features}-feature safety cap; counts are lower bounds.")
    for start in range(0, len(selected), ARCGIS_ID_BATCH_SIZE):
        batch = selected[start : start + ARCGIS_ID_BATCH_SIZE]
        if not budget.allows(ARCGIS_TIMEOUT_SECONDS * ARCGIS_MAX_ATTEMPTS):
            partial = True
            notes.append("Feature retrieval stopped at the tool budget; selected IDs remain unread.")
            break
        try:
            result = ArcGISService.query_features(
                spec.url,
                spec.layer_id,
                None,
                out_fields=",".join(spec.out_fields),
                return_geometry=return_geometry,
                out_sr=4326 if return_geometry else None,
                timeout=budget.timeout(ARCGIS_TIMEOUT_SECONDS, requests=ARCGIS_MAX_ATTEMPTS * 2),
                max_attempts=ARCGIS_MAX_ATTEMPTS,
                page_size=len(batch),
                max_features=len(batch),
                service_name=spec.label,
                headers=HEADERS,
                allow_redirects=False,
                extra_params={**extra, "objectIds": ",".join(map(str, batch))},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("%s feature batch failed: %s", spec.label, exc)
            if not features_by_id:
                return [], _failed(
                    spec.key, spec.label, "Selected-feature query failed; unavailable, not empty.", spec.layer_url
                )
            partial = True
            notes.append("A selected-feature batch failed; earlier batches are retained, but retrieval is incomplete.")
            break
        truncated |= result.truncated
        if result.truncated:
            notes.append("A selected-feature batch hit a source transfer limit; counts are lower bounds.")
        notes.extend(result.warnings)
        skipped = 0
        for feature in result.features:
            attrs = feature.get("attributes") if isinstance(feature, dict) else None
            oid = _int(attrs.get(spec.oid_field)) if isinstance(attrs, dict) else None
            if oid not in batch or oid in features_by_id:
                skipped += 1
                continue
            features_by_id[oid] = feature
        missing = len(batch) - sum(oid in features_by_id for oid in batch)
        if skipped or missing:
            partial = True
            notes.append(
                f"Skipped {skipped} malformed, duplicate, or unexpected features; {missing} selected IDs were missing."
            )
    verified_ids = object_ids
    if selected:
        try:
            verified_ids = ids()
            if verified_ids != object_ids:
                partial = True
                notes.insert(
                    0, "Matching source IDs changed during retrieval; restart this query before continuing pagination."
                )
        except Exception as exc:  # noqa: BLE001
            verified_ids = None
            logger.error("%s final ID check failed: %s", spec.label, exc)
            partial = True
            notes.insert(0, "Final source-ID check unavailable; a stable selection could not be verified.")
    features = [features_by_id[oid] for oid in selected if oid in features_by_id]
    status = "truncated" if truncated else "partial" if partial else "complete" if features else "empty"
    report = SourceReport(
        spec.key,
        spec.label,
        status,
        record_count=len(features),
        note=" ".join(notes),
        url=spec.layer_url,
        retrieved_at=now_utc(),
        fingerprint=fingerprint(
            {"ids": object_ids, "verified_ids": verified_ids, "features": features, "partial": partial}
        ),
    )
    return features, report


def _epa_id(value: Any) -> str | None:
    """Accept only well-formed EPA IDs from sources, so identifiers can be rendered verbatim."""
    candidate = (text(value) or "").upper()
    return candidate if EPA_ID_RE.fullmatch(candidate) else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _code(value: Any, pattern: str = r"[A-Z0-9]{1,3}") -> str | None:
    candidate = (text(value) or "").upper()
    return candidate if re.fullmatch(pattern, candidate) else None


def point_record(feature: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an NPL status point; returns None when the record carries no usable EPA ID."""
    attrs = feature["attributes"]
    epa_id = _epa_id(attrs.get("Site_EPA_ID"))
    if not epa_id:
        return None
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    latitude = coordinate(geometry.get("y"), -90, 90)
    longitude = coordinate(geometry.get("x"), -180, 180)
    coordinate_source = "point geometry (WGS84)"
    if latitude is None or longitude is None:
        latitude = coordinate(attrs.get("Latitude"), -90, 90)
        longitude = coordinate(attrs.get("Longitude"), -180, 180)
        coordinate_source = "Latitude/Longitude attributes" if latitude is not None else None
    sems_id, warning = None, None
    raw_sems = attrs.get("SEMS_ID")
    if isinstance(raw_sems, int) and not isinstance(raw_sems, bool) and 0 < raw_sems < 10_000_000:
        sems_id = f"{raw_sems:07d}"
    profile = parse_linked_field(attrs.get("Site_Progress_Profile"))
    profile_id = re.search(r"[?&]id=(\d{7})\b", profile["url"] or "")
    if profile_id and sems_id and profile_id.group(1) != sems_id:
        warning = f"SEMS_ID {sems_id} disagrees with the profile link id {profile_id.group(1)}"
    state_name = text(attrs.get("State"))
    return {
        "source": NPL_POINTS.key,
        "object_id": _int(attrs.get("ObjectId2")),
        "epa_id": epa_id,
        "sems_id": sems_id,
        "sems_id_warning": warning,
        "name": text(attrs.get("Site_Name")),
        "state_name": state_name,
        "state_code": state_code_from_name(state_name),
        "city": text(attrs.get("City")),
        "county": text(attrs.get("County")),
        "region": f"{attrs['Region_ID']:02d}" if isinstance(attrs.get("Region_ID"), int) else None,
        "status": normalize_npl_status(attrs.get("Status"), NPL_POINTS.key),
        "dates": {
            "proposed": mdy_field(attrs.get("Proposed_Date")),
            "listed": mdy_field(attrs.get("Listing_Date")),
            "construction_completion": mdy_field(attrs.get("Construction_Completion_Date")),
            "notice_of_intent_to_delete": mdy_field(attrs.get("NOID_Date")),
            "deleted": mdy_field(attrs.get("Deletion_Date")),
        },
        "construction_completion_number": attrs.get("Construction_Completion_Number"),
        "partial_deletion": parse_partial_deletion(attrs.get("Site_has_had_a_Partial_Deletion")),
        "links": {
            "site_progress_profile": profile,
            "listing_narrative": parse_linked_field(attrs.get("Site_Listing_Narrative")),
            "proposed_fr_notice": parse_linked_field(attrs.get("Proposed_FR_Notice")),
            "final_fr_notice": parse_linked_field(attrs.get("Final_FR_Notice")),
            "notice_of_intent_to_delete_fr_notice": parse_linked_field(attrs.get("NOID_FR_Notice")),
            "deletion_fr_notice": parse_linked_field(attrs.get("Deletion_FR_Notice")),
            "notice_of_data_availability": parse_linked_field(attrs.get("Notice_of_Data_Availability")),
            "restoration_fr_notice": parse_linked_field(attrs.get("Restoration_FR_Notice_Jumper_Page")),
        },
        "latitude": latitude,
        "longitude": longitude,
        "coordinate_source": coordinate_source,
    }


def boundary_record(spec: LayerSpec, feature: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a total-site, OU, or IC polygon feature, preserving raw class/type values."""
    attrs = feature["attributes"]
    epa_id = _epa_id(attrs.get("EPA_ID"))
    if not epa_id:
        return None
    feature_class = _int(attrs.get("SITE_FEATURE_CLASS"))
    class_label = SITE_FEATURE_CLASS_LABELS.get(feature_class) if spec.key == "site_boundaries" else None
    raw_type = attrs.get("SITE_FEATURE_TYPE")
    feature_type = text(raw_type)
    if feature_type and feature_type.casefold() == "<null>":
        feature_type = None
    program = text(attrs.get("EPA_PROGRAM"))
    last_change = epoch_ms_field(attrs.get("LAST_CHANGE_DATE"))
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else None
    return {
        "source": spec.key,
        "object_id": _int(attrs.get("OBJECTID")),
        "epa_id": epa_id,
        "site_name": text(attrs.get("SITE_NAME")),
        "region": f"{attrs['REGION_CODE']:02d}" if isinstance(attrs.get("REGION_CODE"), int) else None,
        "feature_class": feature_class,
        "feature_class_label": class_label,
        "feature_type": feature_type,
        "feature_type_raw": raw_type,
        "feature_name": text(attrs.get("SITE_FEATURE_NAME")),
        "feature_description": text(attrs.get("SITE_FEATURE_DESCRIPTION")),
        "feature_source": text(attrs.get("SITE_FEATURE_SOURCE")),
        "epa_program": program,
        "epa_program_in_domain": program in EPA_PROGRAM_DOMAIN if program else None,
        "status": normalize_npl_status(attrs.get("NPL_STATUS_CODE"), spec.key, last_change["iso"]),
        "federal_facility": federal_facility(attrs.get("FEDERAL_FACILITY_DETER_CODE")),
        "last_change_date": last_change,
        "original_creation_date": epoch_ms_field(attrs.get("ORIGINAL_CREATION_DATE")),
        "city": text(attrs.get("CITY_NAME")),
        "county": text(attrs.get("COUNTY")),
        "state_code": _code(attrs.get("STATE_CODE"), r"[A-Z]{2}"),
        "site_info_url": epa_url(attrs.get("URL_ALIAS_TXT")),
        "feature_info_url": epa_url(attrs.get("FEATURE_INFO_URL")),
        "feature_info_label": text(attrs.get("FEATURE_INFO_URL_DESC")),
        "gis_area": attrs.get("GIS_AREA") if isinstance(attrs.get("GIS_AREA"), (int, float)) else None,
        "gis_area_units": text(attrs.get("GIS_AREA_UNITS")),
        "rings": geometry.get("rings") if geometry else None,
    }


def frs_record(feature: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an FRS SEMS program-interest point; FRS identity is not SEMS site identity."""
    attrs = feature["attributes"]
    registry_id = text(attrs.get("REGISTRY_ID"))
    registry_id = registry_id if registry_id and FRS_REGISTRY_RE.fullmatch(registry_id) else None
    program_id = text(attrs.get("PGM_SYS_ID"))
    if not registry_id and not program_id:
        return None
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    update = epoch_ms_field(attrs.get("UPDATE_DATE"))
    return {
        "source": FRS_SEMS.key,
        "object_id": _int(attrs.get("OBJECTID")),
        "registry_id": registry_id,
        "program_system": text(attrs.get("PGM_SYS_ACRNM")),
        "program_id": program_id,
        "epa_id": _epa_id(program_id),
        "name": text(attrs.get("PRIMARY_NAME")),
        "city": text(attrs.get("CITY_NAME")),
        "county": text(attrs.get("COUNTY_NAME")),
        "state_code": _code(attrs.get("STATE_CODE"), r"[A-Z]{2}"),
        "interest_type": text(attrs.get("INTEREST_TYPE")),
        "status": normalize_npl_status(attrs.get("ACTIVE_STATUS"), FRS_SEMS.key, update["iso"]),
        "federal_facility_code": text(attrs.get("FED_FACILITY_CODE")),
        "update_date": update,
        "facility_url": epa_url(attrs.get("FAC_URL")),
        "latitude": coordinate(geometry.get("y"), -90, 90),
        "longitude": coordinate(geometry.get("x"), -180, 180),
        "latitude_nad83": coordinate(attrs.get("LATITUDE83"), -90, 90),
        "longitude_nad83": coordinate(attrs.get("LONGITUDE83"), -180, 180),
    }


def reuse_record(feature: dict[str, Any]) -> dict[str, Any] | None:
    """A Superfund Sites in Reuse map point: EPA reports some reuse at the site, not suitability for new uses."""
    attrs = feature["attributes"]
    site_id = _int(attrs.get("Site_ID"))
    if site_id is None or not 0 < site_id < 10_000_000:
        return None
    return {
        "source": "sites_in_reuse",
        "object_id": _int(attrs.get("FID")),
        "sems_id": f"{site_id:07d}",
        "name": text(attrs.get("Site_Name")),
        "summary_url": epa_url(attrs.get("Snapshot")),
    }


def records_from(
    spec: LayerSpec, features: list[dict[str, Any]], report: SourceReport
) -> tuple[list[dict[str, Any]], SourceReport]:
    builder = {"npl_points": point_record, "frs_sems": frs_record, "sites_in_reuse": reuse_record}.get(spec.key)
    records = [builder(f) if builder else boundary_record(spec, f) for f in features]
    usable = [record for record in records if record]
    unusable = len(records) - len(usable)
    if unusable and report.usable:
        report.status = "partial" if report.status != "truncated" else report.status
        report.note = " ".join(filter(None, [report.note, f"Skipped {unusable} feature(s) without an identifier."]))
    report.record_count = len(usable)
    if report.status == "complete" and not usable:
        report.status = "empty"
    return usable, report


def layer_records(
    spec: LayerSpec,
    *,
    where: str,
    budget: Budget,
    max_features: int,
    geometry: dict[str, Any] | None = None,
    return_geometry: bool = False,
) -> tuple[list[dict[str, Any]], SourceReport]:
    features, report = query_layer(
        spec, where=where, budget=budget, max_features=max_features, geometry=geometry, return_geometry=return_geometry
    )
    return records_from(spec, features, report)


# =============================================================================
# ENVIROFACTS DMAP
# =============================================================================


def dmap_value(value: str) -> str:
    """Encode a DMAP path value; the parser rejects ' & + / even percent-encoded, so callers pre-substitute @."""
    if set(value) & DMAP_UNSAFE_CHARACTERS or not value.strip(". "):
        raise ValueError("DMAP values cannot contain ' & + or / and must not be only dots")
    return quote(value, safe="@")


def dmap_name_clause(query: str) -> list[str]:
    """Substring name match; unsafe characters become the anchored `like` operator's @ wildcard."""
    if set(query) & DMAP_UNSAFE_CHARACTERS:
        pattern = "".join("@" if character in DMAP_UNSAFE_CHARACTERS else character for character in query.upper())
        return ["name", "like", dmap_value(f"@{pattern}@")]
    return ["name", "contains", dmap_value(query.upper())]


def dmap_url(table: str, segments: list[str]) -> str:
    return f"{DMAP_BASE}/{table}/{'/'.join(segments)}/JSON"


def dmap_rows(
    table: str, segments: list[str], *, key: str, label: str, budget: Budget
) -> tuple[list[dict], SourceReport]:
    url = dmap_url(table, segments)
    if not budget.allows(DMAP_TIMEOUT_SECONDS):
        return [], SourceReport(key, label, "skipped", note=SKIPPED_NOTE, url=url)
    try:
        rows, retrieved_at, cached = _cached(
            ("dmap", url),
            lambda: get_json_rows(
                url,
                timeout=(CONNECT_TIMEOUT_SECONDS, budget.timeout(DMAP_TIMEOUT_SECONDS)),
                service_name=label,
                headers=HEADERS,
                allow_redirects=False,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("%s request failed: %s", label, exc)
        return [], _failed(key, label, f"{label} request failed; unavailable, not a no-hit finding.", url)
    status = "complete" if rows else "empty"
    note = (
        f"Cached response originally retrieved at {retrieved_at}; reused for up to {CACHE_SECONDS} seconds."
        if cached
        else ""
    )
    return rows, SourceReport(key, label, status, record_count=len(rows), note=note, url=url, retrieved_at=retrieved_at)


def dmap_site_record(row: dict[str, Any]) -> dict[str, Any] | None:
    site_id = text(row.get("site_id"))
    epa_id = _epa_id(row.get("epa_id"))
    if not site_id or not re.fullmatch(r"\d{7}", site_id) or not epa_id:
        return None
    latitude = coordinate(row.get("primary_latitude_decimal_val"), -90, 90)
    longitude = coordinate(row.get("primary_longitude_decimal_val"), -180, 180)
    return {
        "source": "dmap_site",
        "site_id": site_id,
        "epa_id": epa_id,
        "name": text(row.get("name")),
        "city": text(row.get("city_name")),
        "county": text(row.get("county_name")),
        "state_code": _code(row.get("fk_ref_state_code"), r"[A-Z]{2}"),
        "region": _code(row.get("fk_ref_region_code"), r"\d{2}"),
        "status": normalize_npl_status(row.get("npl_status_code"), "dmap_site"),
        "npl_status_name": text(row.get("npl_status_name")),
        "non_npl_status": {
            "code": _code(row.get("non_npl_status_code")),
            "name": text(row.get("non_npl_status_name")),
            "date": dmap_timestamp_field(row.get("non_npl_status_date")),
        },
        "archived": {
            "indicator": _code(row.get("archived_ind")),
            "date": dmap_timestamp_field(row.get("archived_date")),
        },
        "saa_agreement_site_ind": _code(row.get("saa_agreement_site_ind")),
        "federal_facility_ind": _code(row.get("federal_facility_ind")),
        "latitude": latitude if longitude is not None else None,
        "longitude": longitude if latitude is not None else None,
        "raw": {field: row.get(field) for field in DMAP_SITE_FIELDS},
    }


def dmap_sites(segments: list[str], budget: Budget) -> tuple[list[dict[str, Any]], SourceReport]:
    rows, report = dmap_rows(
        DMAP_SITE_TABLE, segments, key="dmap_site", label="Envirofacts SEMS site table", budget=budget
    )
    records = [record for record in (dmap_site_record(row) for row in rows) if record]
    if len(records) != len(rows):
        report.status = "partial"
        report.note = f"Skipped {len(rows) - len(records)} row(s) without site_id/epa_id."
    report.record_count = len(records)
    return records, report


def dmap_contaminant_rows(site_id: str, max_rows: int, budget: Budget) -> tuple[list[dict[str, Any]], SourceReport]:
    """Explicit fk_site_id join; one extra row is requested to detect truncation."""
    segments = ["fk_site_id", "equals", dmap_value(site_id), f"1:{max_rows + 1}"]
    rows, report = dmap_rows(
        DMAP_CONTAMINANTS_TABLE,
        segments,
        key="dmap_contaminants",
        label="Envirofacts SEMS contaminants table",
        budget=budget,
    )
    records = [{field: row.get(field) for field in DMAP_CONTAMINANT_FIELDS} for row in rows]
    if len(records) > max_rows:
        records = records[:max_rows]
        report.status = "truncated"
        report.note = f"More than {max_rows} rows matched; counts are lower bounds."
    report.record_count = len(records)
    return records, report


# =============================================================================
# FEDERAL REGISTER
# =============================================================================


def federal_register_documents(
    phrase: str, budget: Budget, published_on_or_after: str | None = None
) -> tuple[list[dict[str, Any]], SourceReport]:
    """EPA Federal Register documents whose text contains the exact site-name phrase, newest first."""
    key, label = "federal_register", "Federal Register API (EPA documents)"
    params: dict[str, Any] = {
        "conditions[term]": f'"{phrase}"',
        "conditions[agencies][]": "environmental-protection-agency",
        "order": "newest",
        "per_page": FEDERAL_REGISTER_MAX_RESULTS,
        "fields[]": list(FEDERAL_REGISTER_FIELDS),
    }
    if published_on_or_after:
        params["conditions[publication_date][gte]"] = published_on_or_after
    if not budget.allows(FEDERAL_REGISTER_TIMEOUT_SECONDS):
        return [], SourceReport(key, label, "skipped", note=SKIPPED_NOTE, url=FEDERAL_REGISTER_URL)
    try:
        payload, retrieved_at, cached = _cached(
            ("federal_register", phrase, published_on_or_after),
            lambda: get_json(
                FEDERAL_REGISTER_URL,
                params=params,
                timeout=(CONNECT_TIMEOUT_SECONDS, budget.timeout(FEDERAL_REGISTER_TIMEOUT_SECONDS)),
                service_name=label,
                headers=HEADERS,
                allow_redirects=False,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("%s request failed: %s", label, exc)
        return [], _failed(
            key, label, f"{label} request failed; unavailable, not a no-hit finding.", FEDERAL_REGISTER_URL
        )
    results = payload.get("results")
    if not isinstance(results, list):
        _CACHE.pop(("federal_register", phrase, published_on_or_after), None)
        return [], _failed(
            key,
            label,
            "Federal Register returned an invalid document list; unavailable, not empty.",
            FEDERAL_REGISTER_URL,
        )
    documents = []
    for row in results:
        if not isinstance(row, dict) or not re.fullmatch(r"[0-9A-Z-]{5,20}", str(row.get("document_number") or "")):
            continue
        url = row.get("html_url") if isinstance(row.get("html_url"), str) else None
        documents.append(
            {
                "document_number": row["document_number"],
                "title": text(row.get("title")),
                "action": text(row.get("action")),
                "type": text(row.get("type")),
                "abstract": text(row.get("abstract")),
                "published": row.get("publication_date")
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("publication_date") or ""))
                else None,
                "comments_close_on": row.get("comments_close_on")
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("comments_close_on") or ""))
                else None,
                "docket_ids": [text(d) for d in row.get("docket_ids") or [] if text(d)][:5],
                "url": url if url and url.startswith("https://www.federalregister.gov/") and " " not in url else None,
            }
        )
    total = payload.get("count") if isinstance(payload.get("count"), int) else len(documents)
    status = (
        "truncated"
        if total > len(results)
        else "partial"
        if len(documents) != len(results)
        else "complete"
        if documents
        else "empty"
    )
    oldest = min((d["published"] for d in documents if d["published"]), default=None)
    note = (
        f"{total} documents matched; the newest {len(documents)} were read, so documents published before "
        f"{oldest} were not read. Narrow with a publication date."
        if status == "truncated"
        else ""
    )
    if len(documents) != len(results):
        note += f" Skipped {len(results) - len(documents)} malformed document records."
    if cached:
        note += f" Cached response originally retrieved at {retrieved_at}; reused for up to {CACHE_SECONDS} seconds."
    return documents, SourceReport(
        key,
        label,
        status,
        record_count=len(documents),
        note=note.strip(),
        url=FEDERAL_REGISTER_URL,
        retrieved_at=retrieved_at,
    )
