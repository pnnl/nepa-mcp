"""Read-only screening utilities for BLM Mineral & Land Records System data.

The public MLRS/NLSDB ArcGIS services geospatially represent case records from
legal land descriptions.  Their polygons are screening geometries, not surveys
or legal determinations.  This adapter preserves each source family's status
vocabulary and returns bounded, independently paginated source pages.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import validate_coordinates
from src.core.constants import (
    AUTHORIZATION_DISPOSITIONS,
    BLM_MLRS_REPORTS_URL,
    BLM_MLRS_RESEARCH_MAP_URL,
    DEFAULT_OPEN_DISPOSITIONS,
    ENERGY_LEASE_FAMILIES,
    ENERGY_LEASE_FIELDS,
    HUB_LAYER_ID,
    LAND_USE_FIELDS,
    LAND_USE_FAMILIES,
    LAND_USE_PRODUCT_CATEGORIES,
    LOCATABLE_OPERATION_FAMILIES,
    MAX_RESULT_OFFSET,
    MAX_RESULTS_PER_SOURCE,
    MLRS_GEOTHERMAL_LEASES_URL,
    MLRS_LEASES_PERMITS_EASEMENTS_URL,
    MLRS_LOCATABLE_NOTICES_URL,
    MLRS_LOCATABLE_PLANS_URL,
    MLRS_OIL_GAS_LEASES_URL,
    MLRS_ROW_URL,
    OPERATIONS_DISPOSITIONS,
    OPERATIONS_FIELDS,
    OUTPUT_CRS,
    QUERY_MAX_ATTEMPTS,
    QUERY_TIMEOUT_SECONDS,
    SOURCE_CRS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceSpec:
    """One fixed BLM ArcGIS source used by the server."""

    key: str
    title: str
    record_role: str
    service_url: str
    layer_id: int
    fields: tuple[str, ...]
    default_where: str = "1=1"
    source_note: str = ""

    @property
    def layer_url(self) -> str:
        return f"{self.service_url}/{self.layer_id}"


ROW_SOURCE = SourceSpec(
    "right_of_way",
    "Rights of Way",
    "authorization",
    MLRS_ROW_URL,
    HUB_LAYER_ID,
    LAND_USE_FIELDS,
    source_note="MLRS land-use authorization cases classified as rights-of-way.",
)
LEASE_PERMIT_EASEMENT_SOURCE = SourceSpec(
    "lease_permit_easement",
    "Leases, Permits, and Easements",
    "authorization",
    MLRS_LEASES_PERMITS_EASEMENTS_URL,
    HUB_LAYER_ID,
    LAND_USE_FIELDS,
    source_note="MLRS non-ROW land-use authorization cases.",
)
LOCATABLE_PLAN_SOURCE = SourceSpec(
    "locatable_plan_of_operations",
    "Locatable Plans of Operations",
    "operational_plan",
    MLRS_LOCATABLE_PLANS_URL,
    HUB_LAYER_ID,
    OPERATIONS_FIELDS,
    source_note="MLRS locatable-mineral plan-level operations with Authorized or Pending disposition.",
)
LOCATABLE_NOTICE_SOURCE = SourceSpec(
    "locatable_notice",
    "Locatable Notices",
    "notice",
    MLRS_LOCATABLE_NOTICES_URL,
    HUB_LAYER_ID,
    OPERATIONS_FIELDS,
    source_note="MLRS locatable-mineral notice-level operations with Authorized or Pending disposition.",
)
GEOTHERMAL_SOURCE = SourceSpec(
    "geothermal_lease",
    "Geothermal Leases",
    "mineral_lease",
    MLRS_GEOTHERMAL_LEASES_URL,
    HUB_LAYER_ID,
    ENERGY_LEASE_FIELDS,
    source_note="MLRS geothermal lease cases; a lease is not approval for ground-disturbing operations.",
)
OIL_GAS_SOURCE = SourceSpec(
    "oil_and_gas_lease",
    "Oil and Gas Leases",
    "mineral_lease",
    MLRS_OIL_GAS_LEASES_URL,
    HUB_LAYER_ID,
    ENERGY_LEASE_FIELDS,
    source_note="MLRS oil-and-gas lease cases; a lease is not an approved drilling permit or operating well.",
)

_QUALITY_GROUPS = {
    "0": "direct_plss_match",
    "1": "direct_plss_match",
    "2": "direct_plss_match",
    "3": "direct_plss_match",
    "4": "calculated_plss_match",
    "4.1": "calculated_plss_match",
    "5": "calculated_plss_match",
    "6": "calculated_plss_match",
    "7": "calculated_plss_match",
    "8": "calculated_plss_match",
    "8.1": "mapped_to_section",
    "8.2": "mapped_to_section",
    "8.3": "mapped_to_section",
    "9": "mapped_to_section",
    "10": "mapped_to_section",
    "15": "mixed_mapped_unmapped",
    "11": "attributes_only",
    "12": "attributes_only",
    "20": "attributes_only",
    "21": "attributes_only",
    "22": "attributes_only",
    "25": "mapped_to_county",
    "100": "staff_improved_geometry",
}
_QUALITY_CODE = re.compile(
    r"^\s*(100|25|22|21|20|15|12|11|10|9|8(?:\.[123])?|7|6|5|4(?:\.1)?|3|2|1|0)(?=\s*[:;,]|\s|$)"
)

_FILTER_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &(),.'/_-]{0,79}$")
_PRODUCT_CATEGORY_PATTERNS = {
    "transmission": ("POWER TRANSMISSION", "POWER LINE", "POWER FACILIT"),
    "solar_wind": ("SOLAR", "WIND"),
    "pipeline": ("PIPELINE", "PIPE STORAGE"),
    "road": ("ROAD", "HIGHWAY", "TRAMWAY"),
    "communications": ("COMMUNICATION", "TELEPHONE", "TELEGRAPH", "FIBER OPTIC", "RADIO", "TV SITE"),
}

_DATE_FIELDS = {
    "CSE_DISP_DT": "disposition_date",
    "EFF_DT": "effective_date",
    "EXP_DT": "expiration_date",
    "SALE_DT": "sale_date",
    "Created": "record_created_at",
    "Modified": "record_modified_at",
}

_FIELD_MAP = {
    "CSE_NR": "case_serial_number",
    "LEG_CSE_NR": "legacy_case_serial_number",
    "BLM_PROD": "product",
    "CSE_TYPE_NR": "product_code",
    "CSE_DISP": "source_disposition",
    "CMMDTY": "commodity",
    "FRMTN": "formation",
    "PRDCNG": "production_status",
    "ADMIN_STATE": "administrative_state",
    "GEO_STATE": "geographic_state",
    "CSE_JURIS_DESC": "jurisdiction",
    "CSE_WIDTH": "recorded_width",
    "CSE_LGTH": "recorded_length",
    "RCRD_ACRS": "source_case_acres",
    "SRC": "geometry_source",
}


def get_land_use_authorizations_in_roi(
    lat: float,
    lon: float,
    buffer_miles: float = 25.0,
    *,
    include_closed: bool = False,
    source_dispositions: Iterable[str] | None = None,
    authorization_family: str = "all",
    product_category: str = "all",
    max_results_per_source: int = 25,
    result_offset_per_source: int = 0,
) -> dict[str, Any]:
    """Return BLM MLRS ROW and other land-use authorization case records."""
    dispositions = _resolve_dispositions(
        source_dispositions,
        allowed=AUTHORIZATION_DISPOSITIONS,
        defaults=DEFAULT_OPEN_DISPOSITIONS,
        include_closed=include_closed,
    )
    sources = _select_sources(
        authorization_family,
        allowed=LAND_USE_FAMILIES,
        mapping={
            "all": (ROW_SOURCE, LEASE_PERMIT_EASEMENT_SOURCE),
            "right_of_way": (ROW_SOURCE,),
            "lease_permit_easement": (LEASE_PERMIT_EASEMENT_SOURCE,),
        },
        label="authorization_family",
    )
    product_category = _validate_choice(
        product_category,
        allowed=LAND_USE_PRODUCT_CATEGORIES,
        label="product_category",
    )
    return _screen_sources(
        sources,
        lat,
        lon,
        buffer_miles,
        max_results_per_source=max_results_per_source,
        result_offset_per_source=result_offset_per_source,
        source_dispositions=dispositions,
        where=_product_category_where(product_category),
        prefer_pending_interim=source_dispositions is None,
        filters={
            "source_dispositions": list(dispositions),
            "authorization_family": authorization_family,
            "product_category": product_category,
        },
        screening_boundary=(
            "An intersection identifies a geospatially represented MLRS case record. It does not establish a "
            "surveyed facility footprint, current grant validity or compliance, land ownership, availability, or "
            "approval of a proposed use."
        ),
    )


def get_locatable_operations_in_roi(
    lat: float,
    lon: float,
    buffer_miles: float = 25.0,
    *,
    source_dispositions: Iterable[str] | None = None,
    operation_family: str = "all",
    commodity_filter: str | None = None,
    max_results_per_source: int = 25,
    result_offset_per_source: int = 0,
) -> dict[str, Any]:
    """Return MLRS locatable-mineral plan and notice case records."""
    dispositions = _resolve_dispositions(
        source_dispositions,
        allowed=OPERATIONS_DISPOSITIONS,
        defaults=OPERATIONS_DISPOSITIONS,
    )
    sources = _select_sources(
        operation_family,
        allowed=LOCATABLE_OPERATION_FAMILIES,
        mapping={
            "all": (LOCATABLE_PLAN_SOURCE, LOCATABLE_NOTICE_SOURCE),
            "plan_of_operations": (LOCATABLE_PLAN_SOURCE,),
            "notice": (LOCATABLE_NOTICE_SOURCE,),
        },
        label="operation_family",
    )
    commodity_filter = _validate_filter_text(commodity_filter, "commodity_filter")
    return _screen_sources(
        sources,
        lat,
        lon,
        buffer_miles,
        max_results_per_source=max_results_per_source,
        result_offset_per_source=result_offset_per_source,
        source_dispositions=dispositions,
        where=_contains_where("CMMDTY", commodity_filter),
        filters={
            "source_dispositions": list(dispositions),
            "operation_family": operation_family,
            "commodity_filter": commodity_filter,
        },
        screening_boundary=(
            "Plans of operations and notices are distinct regulatory records. An Authorized disposition does not "
            "establish that operations are underway, currently compliant, or covered by every ancillary approval."
        ),
    )


def get_energy_leases_in_roi(
    lat: float,
    lon: float,
    buffer_miles: float = 25.0,
    *,
    include_closed: bool = False,
    source_dispositions: Iterable[str] | None = None,
    lease_family: str = "all",
    commodity_filter: str | None = None,
    formation_filter: str | None = None,
    max_results_per_source: int = 25,
    result_offset_per_source: int = 0,
) -> dict[str, Any]:
    """Return MLRS geothermal and oil-and-gas lease case records."""
    dispositions = _resolve_dispositions(
        source_dispositions,
        allowed=AUTHORIZATION_DISPOSITIONS,
        defaults=DEFAULT_OPEN_DISPOSITIONS,
        include_closed=include_closed,
    )
    sources = _select_sources(
        lease_family,
        allowed=ENERGY_LEASE_FAMILIES,
        mapping={
            "all": (GEOTHERMAL_SOURCE, OIL_GAS_SOURCE),
            "geothermal": (GEOTHERMAL_SOURCE,),
            "oil_and_gas": (OIL_GAS_SOURCE,),
        },
        label="lease_family",
    )
    commodity_filter = _validate_filter_text(commodity_filter, "commodity_filter")
    formation_filter = _validate_filter_text(formation_filter, "formation_filter")
    return _screen_sources(
        sources,
        lat,
        lon,
        buffer_miles,
        max_results_per_source=max_results_per_source,
        result_offset_per_source=result_offset_per_source,
        source_dispositions=dispositions,
        where=_and_where(
            _contains_where("CMMDTY", commodity_filter),
            _contains_where("FRMTN", formation_filter),
        ),
        filters={
            "source_dispositions": list(dispositions),
            "lease_family": lease_family,
            "commodity_filter": commodity_filter,
            "formation_filter": formation_filter,
        },
        screening_boundary=(
            "A federal mineral lease identifies a recorded lease interest. It is not an approved drilling permit, "
            "well, exploration plan, utilization approval, proof of production, or authorization for ground disturbance."
        ),
    )


def _resolve_dispositions(
    requested: Iterable[str] | None,
    *,
    allowed: tuple[str, ...],
    defaults: tuple[str, ...],
    include_closed: bool = False,
) -> tuple[str, ...]:
    if requested is None:
        values = (*defaults, "Closed") if include_closed and "Closed" in allowed else defaults
    else:
        values = tuple(requested)
        if not values:
            raise ValueError("source_dispositions must contain at least one value when supplied")

    invalid = sorted({value for value in values if value not in allowed})
    if invalid:
        raise ValueError(
            "source_dispositions contains unsupported value(s): "
            + ", ".join(invalid)
            + ". Allowed values: "
            + ", ".join(allowed)
        )
    requested_set = set(values)
    return tuple(value for value in allowed if value in requested_set)


def _validate_choice(value: str, *, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return value


def _select_sources(
    value: str,
    *,
    allowed: tuple[str, ...],
    mapping: dict[str, tuple[SourceSpec, ...]],
    label: str,
) -> tuple[SourceSpec, ...]:
    return mapping[_validate_choice(value, allowed=allowed, label=label)]


def _validate_filter_text(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not _FILTER_TEXT.fullmatch(normalized):
        raise ValueError(
            f"{label} must be 1 to 80 characters and contain only letters, numbers, spaces, or basic punctuation"
        )
    return normalized


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _contains_where(field: str, value: str | None) -> str:
    if value is None:
        return "1=1"
    return f"UPPER({field}) LIKE '%{_sql_literal(value.upper())}%'"


def _product_category_where(category: str) -> str:
    if category == "all":
        return "1=1"

    def category_clause(name: str) -> str:
        patterns = _PRODUCT_CATEGORY_PATTERNS[name]
        return "(" + " OR ".join(f"UPPER(BLM_PROD) LIKE '%{pattern}%'" for pattern in patterns) + ")"

    if category == "other":
        classified = " OR ".join(category_clause(name) for name in _PRODUCT_CATEGORY_PATTERNS)
        return f"NOT ({classified})"
    return category_clause(category)


def _and_where(*clauses: str) -> str:
    active = [clause for clause in clauses if clause and clause != "1=1"]
    if not active:
        return "1=1"
    return " AND ".join(f"({clause})" for clause in active)


def validate_result_window(max_results_per_source: int, result_offset_per_source: int) -> tuple[int, int]:
    """Validate independently paginated source windows."""
    try:
        limit = int(max_results_per_source)
        offset = int(result_offset_per_source)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_results_per_source and result_offset_per_source must be integers") from exc
    if not 1 <= limit <= MAX_RESULTS_PER_SOURCE:
        raise ValueError(f"max_results_per_source must be between 1 and {MAX_RESULTS_PER_SOURCE}")
    if not 0 <= offset <= MAX_RESULT_OFFSET:
        raise ValueError(f"result_offset_per_source must be between 0 and {MAX_RESULT_OFFSET}")
    return limit, offset


def format_land_use_authorizations_summary(result: dict[str, Any]) -> str:
    return _format_result(result, "BLM MLRS Land-Use Authorizations")


def format_locatable_operations_summary(result: dict[str, Any]) -> str:
    return _format_result(result, "BLM MLRS Locatable-Mineral Operations")


def format_energy_leases_summary(result: dict[str, Any]) -> str:
    return _format_result(result, "BLM MLRS Energy Leases")


def _screen_sources(
    sources: tuple[SourceSpec, ...],
    lat: float,
    lon: float,
    buffer_miles: float,
    *,
    max_results_per_source: int,
    result_offset_per_source: int,
    screening_boundary: str,
    source_dispositions: tuple[str, ...],
    where: str = "1=1",
    prefer_pending_interim: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    limit, offset = validate_result_window(max_results_per_source, result_offset_per_source)
    base = {
        "query_type": "roi",
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "max_results_per_source": limit,
        "result_offset_per_source": offset,
        "retrieved_at": _utc_now_iso(),
        "source_spatial_reference": SOURCE_CRS,
        "output_spatial_reference": OUTPUT_CRS,
        "filters": filters or {},
        "screening_boundary": screening_boundary,
    }
    try:
        geometry = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    except Exception as exc:
        logger.error("BLM MLRS ROI buffer creation failed (%s)", type(exc).__name__)
        unavailable = [
            _unavailable_source(
                source,
                "Project-area geometry could not be created; this is not a no-hit finding.",
                result_offset=offset,
            )
            for source in sources
        ]
        return _finish_result(base, unavailable)

    return _finish_result(
        base,
        _query_sources(
            sources,
            geometry=geometry,
            max_results_per_source=limit,
            result_offset_per_source=offset,
            source_dispositions=source_dispositions,
            where=where,
            prefer_pending_interim=prefer_pending_interim,
        ),
    )


def _query_sources(
    sources: tuple[SourceSpec, ...],
    *,
    geometry: dict[str, Any] | None,
    max_results_per_source: int,
    result_offset_per_source: int,
    source_dispositions: tuple[str, ...],
    where: str,
    prefer_pending_interim: bool,
) -> list[dict[str, Any]]:
    """Query independent source families concurrently while preserving declaration order."""
    if not sources:
        return []
    by_key: dict[str, dict[str, Any]] = {}
    # Keep concurrency deliberately modest; these are public BLM services with
    # no published high-volume API contract.
    with ThreadPoolExecutor(max_workers=min(3, len(sources))) as executor:
        futures = {
            executor.submit(
                _query_source,
                source,
                geometry=geometry,
                max_results=max_results_per_source,
                result_offset=result_offset_per_source,
                source_dispositions=source_dispositions,
                where=where,
                prefer_pending_interim=prefer_pending_interim,
            ): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                by_key[source.key] = future.result()
            except Exception as exc:  # Defensive: workers normally contain failures.
                logger.error("Unexpected BLM MLRS worker failure for %s (%s)", source.key, type(exc).__name__)
                by_key[source.key] = _unavailable_source(
                    source,
                    "The BLM source failed unexpectedly; this is not a no-hit finding.",
                    result_offset=result_offset_per_source,
                )
    return [by_key[source.key] for source in sources]


def _query_source(
    source: SourceSpec,
    *,
    geometry: dict[str, Any] | None,
    max_results: int,
    result_offset: int,
    source_dispositions: tuple[str, ...],
    where: str,
    prefer_pending_interim: bool = False,
) -> dict[str, Any]:
    object_ids_by_disposition: dict[str, list[int]] = {}
    for disposition in source_dispositions:
        disposition_where = _and_where(
            source.default_where,
            where,
            f"CSE_DISP = '{_sql_literal(disposition)}'",
        )
        try:
            object_ids_by_disposition[disposition] = ArcGISService.query_object_ids(
                source.service_url,
                source.layer_id,
                geometry,
                where=disposition_where,
                timeout=QUERY_TIMEOUT_SECONDS,
                simplify_geometry=False,
                max_attempts=QUERY_MAX_ATTEMPTS,
                service_name=f"BLM MLRS {source.title}",
            )
        except Exception as exc:
            logger.warning("BLM MLRS object-ID query failed for %s (%s)", source.key, type(exc).__name__)
            return _unavailable_source(
                source,
                "The BLM source ID query was unavailable; this is not a no-hit finding.",
                result_offset=result_offset,
            )

    if prefer_pending_interim:
        preferred_order = ("Pending", "Interim", "Authorized", "Closed")
        ordered_object_ids = [
            object_id for disposition in preferred_order for object_id in object_ids_by_disposition.get(disposition, [])
        ]
    else:
        ordered_object_ids = sorted(
            {object_id for disposition_ids in object_ids_by_disposition.values() for object_id in disposition_ids}
        )

    total_matching_feature_count = len(ordered_object_ids)
    selected_object_ids = ordered_object_ids[result_offset : result_offset + max_results]
    has_more = result_offset + len(selected_object_ids) < total_matching_feature_count
    next_result_offset = result_offset + len(selected_object_ids) if has_more else None
    matching_counts_by_disposition = {
        disposition: len(object_ids_by_disposition[disposition]) for disposition in source_dispositions
    }

    if not selected_object_ids:
        listing_complete = total_matching_feature_count == 0 or result_offset == 0
        return {
            "source_key": source.key,
            "source_title": source.title,
            "record_role": source.record_role,
            "source_endpoint": source.layer_url,
            "source_note": source.source_note,
            "retrieval_status": "ok",
            "listing_complete": listing_complete,
            "result_offset": result_offset,
            "total_matching_feature_count": total_matching_feature_count,
            "matching_counts_by_disposition": matching_counts_by_disposition,
            "selected_object_id_count": 0,
            "selected_object_ids": [],
            "fetched_feature_count": 0,
            "raw_feature_count": 0,
            "returned_feature_count": 0,
            "returned_unique_case_count": 0,
            "returned_record_count": 0,
            "returned_counts_by_disposition": {},
            "has_more": False,
            "next_result_offset": None,
            "records": [],
            "warnings": [],
        }

    try:
        query_result = ArcGISService.query_features(
            source.service_url,
            source.layer_id,
            None,
            out_fields=",".join(source.fields),
            return_geometry=False,
            timeout=QUERY_TIMEOUT_SECONDS,
            page_size=len(selected_object_ids),
            max_features=len(selected_object_ids),
            extra_params={
                "where": "1=1",
                "objectIds": ",".join(str(object_id) for object_id in selected_object_ids),
                "orderByFields": "OBJECTID ASC",
            },
            max_attempts=QUERY_MAX_ATTEMPTS,
            service_name=f"BLM MLRS {source.title}",
        )
    except Exception as exc:
        logger.warning("BLM MLRS selected-feature query failed for %s (%s)", source.key, type(exc).__name__)
        return _unavailable_source(
            source,
            "The BLM source feature query was unavailable; this is not a no-hit finding.",
            result_offset=result_offset,
        )

    raw_features = query_result.features
    if not isinstance(raw_features, list):
        return _unavailable_source(
            source,
            "The BLM source returned malformed feature data.",
            result_offset=result_offset,
        )

    selected_set = set(selected_object_ids)
    features_by_object_id: dict[int, dict[str, Any]] = {}
    malformed_count = 0
    unexpected_count = 0
    for feature in raw_features:
        if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
            malformed_count += 1
            continue
        raw_object_id = feature["attributes"].get("OBJECTID")
        try:
            object_id = int(raw_object_id)
        except (TypeError, ValueError):
            malformed_count += 1
            continue
        if object_id not in selected_set:
            unexpected_count += 1
            continue
        if object_id in features_by_object_id:
            malformed_count += 1
            continue
        features_by_object_id[object_id] = feature

    missing_object_ids = [object_id for object_id in selected_object_ids if object_id not in features_by_object_id]
    records: list[dict[str, Any]] = []
    date_issue_count = 0
    for object_id in selected_object_ids:
        feature = features_by_object_id.get(object_id)
        if feature is None:
            continue
        record = _parse_record(feature["attributes"], source)
        if record is None:
            malformed_count += 1
            continue
        if any(
            quality in {"implausible_past", "implausible_future", "invalid"}
            for quality in record["date_quality"].values()
        ):
            date_issue_count += 1
        records.append(record)

    collapsed = _collapse_records(records)
    warnings = [warning for warning in query_result.warnings if "feature safety cap" not in warning.lower()]
    if malformed_count:
        warnings.append(f"Skipped {malformed_count} malformed or unidentifiable source feature(s).")
    if date_issue_count:
        warnings.append(f"Flagged implausible or invalid source date values in {date_issue_count} record(s).")
    if unexpected_count:
        warnings.append(f"Ignored {unexpected_count} source feature(s) outside the selected object-ID page.")
    if missing_object_ids:
        warnings.append(f"The source omitted {len(missing_object_ids)} selected object ID(s).")

    if selected_object_ids and not collapsed:
        retrieval_status = "unavailable"
        warnings.append("No usable case records remained after validation; this is not a no-hit finding.")
    elif malformed_count or unexpected_count or missing_object_ids or query_result.warnings or query_result.truncated:
        retrieval_status = "degraded"
    else:
        retrieval_status = "ok"

    listing_complete = (
        retrieval_status == "ok" and result_offset == 0 and not has_more and len(records) == len(selected_object_ids)
    )

    return {
        "source_key": source.key,
        "source_title": source.title,
        "record_role": source.record_role,
        "source_endpoint": source.layer_url,
        "source_note": source.source_note,
        "retrieval_status": retrieval_status,
        "listing_complete": listing_complete,
        "result_offset": result_offset,
        "total_matching_feature_count": total_matching_feature_count,
        "matching_counts_by_disposition": matching_counts_by_disposition,
        "selected_object_id_count": len(selected_object_ids),
        "selected_object_ids": selected_object_ids,
        "fetched_feature_count": len(raw_features),
        "raw_feature_count": len(raw_features),
        "returned_feature_count": len(records),
        "returned_unique_case_count": len(collapsed),
        "returned_record_count": len(collapsed),
        "returned_counts_by_disposition": dict(
            sorted(Counter(record.get("source_disposition") or "Not reported" for record in collapsed).items())
        ),
        "has_more": has_more,
        "next_result_offset": next_result_offset,
        "records": collapsed,
        "warnings": warnings,
    }


def _unavailable_source(source: SourceSpec, warning: str, *, result_offset: int = 0) -> dict[str, Any]:
    return {
        "source_key": source.key,
        "source_title": source.title,
        "record_role": source.record_role,
        "source_endpoint": source.layer_url,
        "source_note": source.source_note,
        "retrieval_status": "unavailable",
        "listing_complete": False,
        "result_offset": result_offset,
        "total_matching_feature_count": None,
        "matching_counts_by_disposition": {},
        "selected_object_id_count": 0,
        "selected_object_ids": [],
        "fetched_feature_count": 0,
        "raw_feature_count": 0,
        "returned_feature_count": 0,
        "returned_unique_case_count": 0,
        "returned_record_count": 0,
        "returned_counts_by_disposition": {},
        "has_more": False,
        "next_result_offset": None,
        "records": [],
        "warnings": [warning],
    }


def _finish_result(base: dict[str, Any], source_results: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_statuses = [source["retrieval_status"] for source in source_results]
    if source_results and all(status == "unavailable" for status in retrieval_statuses):
        retrieval_status = "unavailable"
    elif any(status in {"unavailable", "degraded"} for status in retrieval_statuses):
        retrieval_status = "degraded"
    else:
        retrieval_status = "ok"

    known_matching_feature_count = sum(source["total_matching_feature_count"] or 0 for source in source_results)
    all_counts_known = all(source["total_matching_feature_count"] is not None for source in source_results)

    return {
        **base,
        "retrieval_status": retrieval_status,
        "listing_complete": bool(source_results) and all(source["listing_complete"] for source in source_results),
        "source_count": len(source_results),
        "total_matching_feature_count": known_matching_feature_count if all_counts_known else None,
        "known_matching_feature_count": known_matching_feature_count,
        "source_counts_by_family": {
            source["source_key"]: source["total_matching_feature_count"] for source in source_results
        },
        "returned_feature_count": sum(source["returned_feature_count"] for source in source_results),
        "returned_unique_case_count": sum(source["returned_unique_case_count"] for source in source_results),
        "returned_record_count": sum(source["returned_record_count"] for source in source_results),
        "sources": source_results,
    }


def _parse_record(attributes: dict[str, Any], source: SourceSpec) -> dict[str, Any] | None:
    serial = _coerce_text(attributes.get("CSE_NR"))
    legacy_serial = _coerce_text(attributes.get("LEG_CSE_NR"))
    if not serial and not legacy_serial:
        return None

    record: dict[str, Any] = {
        "case_family": source.key,
        "record_role": source.record_role,
        "source_object_id": _coerce_integer(attributes.get("OBJECTID")),
        "case_serial_number": serial,
        "legacy_case_serial_number": legacy_serial,
        "source_feature_count": 1,
        "source_endpoint": source.layer_url,
    }
    for source_field, output_field in _FIELD_MAP.items():
        if source_field not in attributes:
            continue
        value = attributes.get(source_field)
        if output_field in {"source_case_acres", "source_land_status_acres"}:
            record[output_field] = _coerce_number(value)
        else:
            record[output_field] = _coerce_text(value)

    date_quality: dict[str, str] = {}
    for source_field, output_field in _DATE_FIELDS.items():
        if source_field not in attributes:
            continue
        date_value, quality = _parse_epoch_millis(attributes.get(source_field), output_field)
        record[output_field] = date_value
        if quality:
            date_quality[output_field] = quality
    record["date_quality"] = date_quality

    quality_code, quality_group = _normalize_geometry_quality(attributes.get("QLTY"))
    record["geometry_quality_code"] = quality_code
    record["geometry_quality"] = quality_group
    return record


def _collapse_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate mapped features for the same case and disposition."""
    collapsed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (
            record.get("case_family", ""),
            record.get("case_serial_number") or record.get("legacy_case_serial_number") or "",
            record.get("source_disposition", ""),
        )
        if key in collapsed:
            collapsed[key]["source_feature_count"] += 1
            object_id = record.get("source_object_id")
            if object_id is not None:
                collapsed[key]["source_object_ids"].append(object_id)
            continue
        record["source_object_ids"] = [record["source_object_id"]] if record.get("source_object_id") is not None else []
        collapsed[key] = record
    return list(collapsed.values())


def _parse_epoch_millis(
    value: Any,
    field_name: str = "disposition_date",
) -> tuple[str | None, str | None]:
    if value in (None, ""):
        return None, None
    try:
        milliseconds = float(value)
        if not math.isfinite(milliseconds):
            raise ValueError
        parsed = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None, "invalid"

    now = datetime.now(UTC)
    if parsed.year < 1800:
        quality = "implausible_past"
    elif field_name in {"expiration_date", "effective_date"}:
        if parsed.year > 2200:
            quality = "implausible_future"
        elif parsed > now:
            quality = "expected_future"
        elif parsed.year < 1970:
            quality = "historic"
        else:
            quality = "plausible"
    elif field_name in {"record_created_at", "record_modified_at"} and parsed > now + timedelta(days=7):
        quality = "implausible_future"
    elif parsed > now + timedelta(days=366):
        quality = "implausible_future"
    elif parsed > now:
        quality = "future_unverified"
    elif parsed.year < 1970:
        quality = "historic"
    else:
        quality = "plausible"
    return parsed.isoformat().replace("+00:00", "Z"), quality


def _normalize_geometry_quality(value: Any) -> tuple[str | None, str]:
    text = _coerce_text(value)
    match = _QUALITY_CODE.match(text)
    if not match:
        return None, "unknown"
    code = match.group(1)
    return code, _QUALITY_GROUPS.get(code, "unknown")


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coerce_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return number


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _format_result(result: dict[str, Any], title: str) -> str:
    lines = [f"## {title}", ""]
    center = result.get("center", {})
    lines += [
        f"**Location:** ({center.get('latitude')}, {center.get('longitude')})",
        f"**Buffer:** {result.get('buffer_miles')} miles",
        (
            "**Pagination:** Up to "
            f"{result.get('max_results_per_source')} records per source beginning at source offset "
            f"{result.get('result_offset_per_source')}"
        ),
    ]
    filters = result.get("filters") or {}
    rendered_filters = []
    for name, value in filters.items():
        if value in (None, "all", [], ()):
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        rendered_filters.append(f"{name}={value}")
    if rendered_filters:
        lines.append(f"**Filters:** {'; '.join(rendered_filters)}")

    total_matching = result.get("total_matching_feature_count")
    if total_matching is None:
        total_label = f"unknown; known sources={result.get('known_matching_feature_count', 0)}"
    else:
        total_label = str(total_matching)
    lines += [
        f"**Retrieval health:** {result.get('retrieval_status')}",
        f"**Listing complete:** {str(bool(result.get('listing_complete'))).lower()}",
        f"**Matching source features before pagination:** {total_label}",
        f"**Returned source features:** {result.get('returned_feature_count', 0)}",
        f"**Returned unique cases:** {result.get('returned_unique_case_count', 0)}",
        f"**Retrieved:** {result.get('retrieved_at')}",
        "",
    ]
    source_counts = result.get("source_counts_by_family") or {}
    if source_counts:
        lines.insert(
            -1,
            "**Matching source features by family:** "
            + ", ".join(
                f"{family}={count if count is not None else 'unknown'}" for family, count in source_counts.items()
            ),
        )

    for source in result.get("sources", []):
        lines += [f"### {source['source_title']}", ""]
        lines.append(
            f"Retrieval health: **{source['retrieval_status']}** | "
            f"Listing complete: **{str(bool(source['listing_complete'])).lower()}**"
        )
        source_total = source.get("total_matching_feature_count")
        lines.append(
            f"Matching source features before pagination: {source_total if source_total is not None else 'unknown'} | "
            f"Selected object IDs: {source.get('selected_object_id_count', 0)} | "
            f"Fetched source features: {source.get('fetched_feature_count', 0)} | "
            f"Returned unique cases: {source.get('returned_unique_case_count', 0)}"
        )
        lines.append(
            f"Pagination: has_more={str(bool(source.get('has_more'))).lower()} | "
            f"next_result_offset={source.get('next_result_offset')}"
        )
        if source.get("selected_object_ids"):
            lines.append(
                "Selected object ID page: " + ", ".join(str(object_id) for object_id in source["selected_object_ids"])
            )
        matching_counts = source.get("matching_counts_by_disposition") or {}
        if matching_counts:
            lines.append(
                "Source dispositions before pagination: "
                + ", ".join(f"{status}={count}" for status, count in matching_counts.items())
            )
        returned_counts = source.get("returned_counts_by_disposition") or {}
        if returned_counts:
            lines.append(
                "Returned-page dispositions: "
                + ", ".join(f"{status}={count}" for status, count in returned_counts.items())
            )
        lines.append(f"Source: {source['source_endpoint']}")
        if source.get("source_note"):
            lines.append(f"Source scope: {source['source_note']}")
        lines.append("")
        for warning in source.get("warnings", []):
            lines += [f"> Warning: {warning}", ""]

        records = source.get("records", [])
        if source["retrieval_status"] == "unavailable":
            lines += ["No absence finding can be made from this source for this request.", ""]
        elif not records:
            if source["retrieval_status"] == "degraded":
                lines += [
                    "No usable records were returned from the available portion of this source; "
                    "do not treat this as an absence finding.",
                    "",
                ]
            else:
                if source.get("result_offset", 0):
                    lines += [
                        f"No records were returned at source offset {source['result_offset']}; this does not "
                        "establish that the source has no earlier matching records.",
                        "",
                    ]
                else:
                    lines += ["No matching geospatially represented records were returned by this source.", ""]
        else:
            for record in records:
                lines.append(_format_record(record))
            lines.append("")

    lines += [
        "---",
        "",
        f"**Screening boundary:** {result.get('screening_boundary')}",
        (
            "BLM notes that MLRS geometries are derived from legal land descriptions and PLSS data; some records "
            "cannot be geocoded, and mapped records may be generalized to aliquot, section, or county level."
        ),
        f"Confirm case details in the [MLRS Research Map]({BLM_MLRS_RESEARCH_MAP_URL}) or "
        f"[MLRS public reports]({BLM_MLRS_REPORTS_URL}) and with the responsible BLM office.",
    ]
    return "\n".join(lines)


def _format_record(record: dict[str, Any]) -> str:
    serial = record.get("case_serial_number") or record.get("legacy_case_serial_number") or "Unknown serial"
    headline = " — ".join(
        value
        for value in (
            record.get("source_disposition"),
            record.get("product"),
        )
        if value
    )
    line = f"- **{serial}**"
    if headline:
        line += f" — {headline}"

    details = []
    legacy = record.get("legacy_case_serial_number")
    if legacy and legacy != serial:
        details.append(f"legacy serial {legacy}")
    if record.get("commodity"):
        details.append(f"commodity {record['commodity']}")
    if record.get("formation"):
        details.append(f"formation {record['formation']}")
    if record.get("geographic_state"):
        details.append(f"geographic state {record['geographic_state']}")
    if record.get("jurisdiction"):
        details.append(f"jurisdiction {record['jurisdiction']}")
    if record.get("source_case_acres") is not None:
        details.append(f"source case acres {record['source_case_acres']:g}")
    if record.get("production_status"):
        details.append(f"source production indicator {record['production_status']}")
    if record.get("source_object_ids"):
        details.append(
            "source object ID"
            + ("s " if len(record["source_object_ids"]) > 1 else " ")
            + ", ".join(str(object_id) for object_id in record["source_object_ids"])
        )
    for field, label in (
        ("disposition_date", "disposition date"),
        ("effective_date", "effective date"),
        ("expiration_date", "expiration date"),
        ("sale_date", "sale date"),
        ("record_created_at", "source created"),
        ("record_modified_at", "source modified"),
    ):
        if record.get(field):
            date_quality = record.get("date_quality", {}).get(field)
            suffix = f" [{date_quality}]" if date_quality not in (None, "plausible", "historic") else ""
            details.append(f"{label} {record[field]}{suffix}")
    quality = record.get("geometry_quality")
    if quality and quality != "unknown":
        code = record.get("geometry_quality_code")
        details.append(f"geometry quality {quality}{f' ({code})' if code else ''}")
    if record.get("source_feature_count", 1) > 1:
        details.append(f"{record['source_feature_count']} mapped source features collapsed")
    if details:
        line += f"\n  - {'; '.join(details)}"
    return line
