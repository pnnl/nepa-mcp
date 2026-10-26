"""EPA Superfund research tools: identity, discovery, mapped evidence, records, and notices.

Each ``get_*``/``search_*`` function returns a result dictionary that keeps the
complete, deterministically ordered record list plus one ``SourceReport`` per
queried source. ``format_*`` functions page that list and render Markdown. A
listing, deletion, construction-completion milestone, archived record, or
mapped boundary is never presented as unrestricted use, clean land, or
development suitability.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Callable

from nepa_mcp_common.arcgis import ArcGISService
from src.apis.adapters import (
    dmap_contaminant_rows,
    dmap_name_clause,
    dmap_sites,
    dmap_value,
    federal_register_documents,
    layer_records,
    sql_in,
    sql_like,
    sql_literal,
)
from src.core.normalization import (
    NplStatus,
    Page,
    SourceReport,
    distance_miles,
    fingerprint,
    link,
    md,
    normalize_name,
    now_utc,
    parse_mdy,
    polygon_distance_miles,
    raw_status_values,
    status_conflict,
    validate_document_type,
    validate_epa_id,
    validate_frs_registry_id,
    validate_media,
    validate_npl_status,
    validate_operable_unit,
    validate_query,
    validate_scope,
    validate_sems_id,
    validate_state,
    validate_date,
)
from src.core.sources import (
    CONTAMINANT_UNAVAILABLE_FIELDS,
    DMAP_CONTAMINANT_ROWS,
    DMAP_SEARCH_ROWS,
    FRS_SEMS,
    HEADERS,
    IC_BOUNDARIES,
    LOOKUP_MAX_FEATURES,
    MAX_PAGE_SIZE,
    NOT_RETRIEVED_NOTE,
    NPL_POINTS,
    OU_BOUNDARIES,
    REUSE_POINTS,
    ROI_MAX_FEATURES,
    SEARCH_MAX_FEATURES,
    SITE_BOUNDARIES,
    STATE_NAMES,
    Budget,
)

logger = logging.getLogger(__name__)

SCOPE_NOTE = {
    "npl_and_mapped": "NPL status points and published total-site boundary attributes (not every Superfund site).",
    "sems_candidates": (
        "NPL status points, total-site boundaries, FRS SEMS facility-interest points, and the Envirofacts SEMS site "
        "table. FRS interests are unresolved candidates, not confirmed NPL sites or active cleanups."
    ),
}
ROI_SCOPE_NOTE = {
    "npl_and_mapped": SCOPE_NOTE["npl_and_mapped"],
    "sems_candidates": (
        "NPL status points, total-site boundaries, and FRS SEMS facility-interest points; FRS candidates are resolved "
        "against the Envirofacts SEMS site table by exact EPA ID. FRS interests are not confirmed NPL sites."
    ),
}
ENRICH_MAX_IDS = 200
STATUS_TEXT = {
    "final": "final NPL",
    "proposed": "proposed for NPL",
    "deleted": "deleted from final NPL",
    "part_of_npl_site": "part of an NPL site",
    "not_on_npl": "not on the NPL",
    "removed_from_proposed": "removed from proposed NPL",
    "pre_proposal": "pre-proposal",
    "withdrawn": "withdrawn from final NPL",
    "not_valid_site": "not a valid site or incident",
    "unknown": "status not published or unrecognized",
}
SOURCE_SHORT = {
    "npl_points": "NPL status point",
    "site_boundaries": "total-site boundary",
    "ou_boundaries": "OU boundary",
    "ic_boundaries": "IC boundary",
    "frs_sems": "FRS SEMS interest",
    "dmap_site": "SEMS site table",
}
NOT_A_DETERMINATION = (
    "Note: Listing status, deletion, construction completion, archiving, and mapped boundaries are program records, "
    "not determinations of unrestricted use, current contamination extent, or development suitability."
)

# =============================================================================
# SHARED HELPERS
# =============================================================================


def _result(reports: list[SourceReport], warnings: list[str], **values: Any) -> dict[str, Any]:
    usable = [report for report in reports if report.usable]
    return {
        **values,
        "result_fingerprint": fingerprint(
            {"values": values, "sources": [(r.key, r.status, r.record_count, r.fingerprint) for r in reports]}
        ),
        "reports": reports,
        "warnings": warnings,
        "data_unavailable": bool(reports) and not usable,
        "retrieved_at": now_utc(),
    }


def _lower_bound(reports: list[SourceReport]) -> bool:
    return any(report.status in {"truncated", "partial", "skipped", "failed"} for report in reports)


def _point_by_epa_id(epa_id: str, budget: Budget) -> tuple[dict[str, Any] | None, SourceReport]:
    records, report = layer_records(
        NPL_POINTS, where=f"Site_EPA_ID = {sql_literal(epa_id)}", budget=budget, max_features=10
    )
    return (records[0] if records else None), report


def _dmap_site(field: str, value: str, budget: Budget) -> tuple[dict[str, Any] | None, SourceReport]:
    records, report = dmap_sites([field, "equals", dmap_value(value)], budget)
    return (records[0] if records else None), report


def resolve_identity(
    *,
    epa_id: str | None = None,
    sems_id: str | None = None,
    frs_registry_id: str | None = None,
    budget: Budget,
    need_site_table: bool = False,
) -> dict[str, Any]:
    """Resolve typed identifiers through published crosswalks only (never by name or proximity)."""
    reports: list[SourceReport] = []
    warnings: list[str] = []
    identity: dict[str, Any] = {
        "epa_id": epa_id,
        "sems_id": None,
        "point": None,
        "dmap": None,
        "frs": [],
        "conflict": False,
    }

    if frs_registry_id:
        frs, report = layer_records(
            FRS_SEMS,
            where=f"REGISTRY_ID = {sql_literal(frs_registry_id)} AND PGM_SYS_ACRNM = 'SEMS'",
            budget=budget,
            max_features=50,
        )
        reports.append(report)
        identity["frs"] = frs
        epa_ids = sorted({record["epa_id"] for record in frs if record["epa_id"]})
        if len(epa_ids) == 1:
            identity["epa_id"] = epa_id = epa_ids[0]
        elif len(epa_ids) > 1:
            warnings.append(
                f"FRS registry {frs_registry_id} carries {len(epa_ids)} SEMS program identifiers ({', '.join(epa_ids)}); "
                "look each up by epa_id. No single site was selected."
            )
            return {**identity, "reports": reports, "warnings": warnings}
        else:
            return {**identity, "reports": reports, "warnings": warnings}

    if sems_id:
        dmap, report = _dmap_site("site_id", sems_id, budget)
        reports.append(report)
        identity["dmap"] = dmap
        identity["sems_id"] = sems_id
        if dmap:
            identity["epa_id"] = epa_id = dmap["epa_id"]
        else:
            points, point_report = layer_records(
                NPL_POINTS, where=f"SEMS_ID = {int(sems_id)}", budget=budget, max_features=10
            )
            reports.append(point_report)
            if points:
                identity["point"] = points[0]
                identity["epa_id"] = epa_id = points[0]["epa_id"]

    if epa_id and identity["point"] is None:
        point, report = _point_by_epa_id(epa_id, budget)
        reports.append(report)
        identity["point"] = point
    point = identity["point"]
    if point and point.get("sems_id_warning"):
        warnings.append(point["sems_id_warning"])
    if epa_id and identity["dmap"] is None and (need_site_table or not (point and point.get("sems_id"))):
        dmap, report = _dmap_site("epa_id", epa_id, budget)
        reports.append(report)
        identity["dmap"] = dmap

    point_sems = point.get("sems_id") if point else None
    dmap_sems = identity["dmap"]["site_id"] if identity["dmap"] else None
    if point_sems and dmap_sems and point_sems != dmap_sems:
        identity["conflict"] = True
        warnings.append(
            f"Crosswalk conflict: the NPL status layer gives SEMS id {point_sems} but the SEMS site table gives {dmap_sems}; "
            "neither value was selected."
        )
    elif not identity["sems_id"]:
        identity["sems_id"] = point_sems or dmap_sems
    source = point or identity["dmap"] or {}
    identity["name"] = source.get("name")
    identity["state_code"] = source.get("state_code")
    identity["region"] = source.get("region")
    return {**identity, "reports": reports, "warnings": warnings}


def _listing_statuses(statuses: list[NplStatus]) -> list[NplStatus]:
    """FRS ACTIVE_STATUS is a program-interest label, not listing evidence."""
    return [status for status in statuses if status.source != "frs_sems"]


def _enrich(
    sites: dict[str, dict[str, Any]],
    *,
    points: bool,
    boundaries: bool,
    site_table: bool,
    budget: Budget,
    reports: list[SourceReport],
    warnings: list[str],
) -> None:
    """Complete matched EPA IDs from the other sources by exact identifier, so filters never hide conflicts."""
    eligible = [epa_id for epa_id in sorted(sites) if not epa_id.startswith("FRS:")]
    wanted = {
        "point": [i for i in eligible if points and sites[i]["point"] is None],
        "boundaries": [i for i in eligible if boundaries and not sites[i]["boundaries"]],
        "dmap": [i for i in eligible if site_table and sites[i]["dmap"] is None],
    }
    for kind, ids in wanted.items():
        if not ids:
            continue
        if len(ids) > ENRICH_MAX_IDS:
            warnings.append(
                f"Only the first {ENRICH_MAX_IDS} of {len(ids)} matched sites were cross-checked against the "
                f"{kind} source; other sites may show fewer source statuses than exist."
            )
            ids = ids[:ENRICH_MAX_IDS]
        if kind == "dmap":
            records, report = dmap_sites(["epa_id", "in", dmap_value(",".join(ids))], budget)
        else:
            spec = NPL_POINTS if kind == "point" else SITE_BOUNDARIES
            records, report = layer_records(
                spec, where=sql_in(spec.epa_id_field, ids), budget=budget, max_features=LOOKUP_MAX_FEATURES
            )
        report.key, report.label = f"{report.key}_by_epa_id", f"{report.label} (exact EPA ID cross-check)"
        reports.append(report)
        for record in records:
            site = sites.get(record["epa_id"])
            if site is None:
                continue
            if kind == "boundaries":
                site["boundaries"].append(record)
            else:
                site[kind] = record


# =============================================================================
# 1. SEARCH
# =============================================================================


def search_epa_superfund_sites(
    query: str | None = None,
    state: str | None = None,
    npl_status: str | None = None,
    inventory_scope: str = "npl_and_mapped",
) -> dict[str, Any]:
    query = validate_query(query)
    state = validate_state(state)
    npl_status = validate_npl_status(npl_status)
    inventory_scope = validate_scope(inventory_scope)
    if not (query or state or npl_status):
        raise ValueError("provide a query, state, or npl_status filter")
    budget = Budget()
    reports: list[SourceReport] = []
    warnings: list[str] = []
    sites: dict[str, dict[str, Any]] = {}

    def where(name: str, city: str, county: str, state_clause: str | None, status_clause: str | None) -> str:
        parts = []
        if query:
            parts.append(f"({sql_like(name, query)} OR {sql_like(city, query)} OR {sql_like(county, query)})")
        parts.extend(clause for clause in (state_clause, status_clause) if clause)
        return " AND ".join(parts)

    def entry(epa_id: str) -> dict[str, Any]:
        return sites.setdefault(epa_id, {"epa_id": epa_id, "point": None, "boundaries": [], "frs": [], "dmap": None})

    point_statuses = [value.upper() for value in raw_status_values(npl_status, "npl_points")] if npl_status else []
    if npl_status and not point_statuses:
        reports.append(
            SourceReport(
                NPL_POINTS.key,
                NPL_POINTS.label,
                "unsupported",
                note=f"This layer does not publish '{npl_status}' records.",
            )
        )
    else:
        point_where = where(
            "Site_Name",
            "City",
            "County",
            f"State = {sql_literal(STATE_NAMES[state])}" if state else None,
            sql_in("UPPER(Status)", point_statuses) if point_statuses else None,
        )
        points, report = layer_records(NPL_POINTS, where=point_where, budget=budget, max_features=SEARCH_MAX_FEATURES)
        reports.append(report)
        for point in points:
            entry(point["epa_id"])["point"] = point

    codes = raw_status_values(npl_status, "site_boundaries") if npl_status else []
    base_boundary = where(
        "SITE_NAME", "CITY_NAME", "COUNTY", f"STATE_CODE = {sql_literal(state)}" if state else None, None
    )
    boundary_where = " AND ".join(filter(None, [base_boundary, sql_in("NPL_STATUS_CODE", codes) if codes else None]))
    boundaries, report = layer_records(
        SITE_BOUNDARIES, where=boundary_where, budget=budget, max_features=SEARCH_MAX_FEATURES
    )
    reports.append(report)
    for boundary in boundaries:
        entry(boundary["epa_id"])["boundaries"].append(boundary)

    undetermined: list[str] = []
    if npl_status:
        unknown_where = " AND ".join(filter(None, [base_boundary, "(NPL_STATUS_CODE IS NULL OR NPL_STATUS_CODE = '')"]))
        unknown, unknown_report = layer_records(
            SITE_BOUNDARIES, where=unknown_where, budget=budget, max_features=SEARCH_MAX_FEATURES
        )
        unknown_report.key, unknown_report.label = (
            "site_boundaries_unknown_status",
            "Total-site boundaries without a status",
        )
        reports.append(unknown_report)
        undetermined = sorted({record["epa_id"] for record in unknown} - set(sites))

    if inventory_scope == "sems_candidates" and (query or state):
        # FRS ACTIVE_STATUS is a program-interest label, so it never satisfies a listing-status filter.
        frs_where = where(
            "PRIMARY_NAME", "CITY_NAME", "COUNTY_NAME", f"STATE_CODE = {sql_literal(state)}" if state else None, None
        )
        frs, report = layer_records(
            FRS_SEMS, where=f"({frs_where}) AND PGM_SYS_ACRNM = 'SEMS'", budget=budget, max_features=SEARCH_MAX_FEATURES
        )
        reports.append(report)
        for record in frs:
            entry(record["epa_id"] or f"FRS:{record['registry_id'] or record['program_id']}")["frs"].append(record)
    if inventory_scope == "sems_candidates":
        segments: list[str] = []
        if state:
            segments += ["fk_ref_state_code", "equals", state]
        if query:
            segments += (["and"] if segments else []) + dmap_name_clause(query)
        if npl_status:
            dmap_codes = raw_status_values(npl_status, "dmap_site")
            segments += (["and"] if segments else []) + ["npl_status_code", "equals", dmap_codes[0]]
        segments += ["sort", "name:asc", f"1:{DMAP_SEARCH_ROWS + 1}"]  # one extra row detects truncation
        rows, report = dmap_sites(segments, budget)
        if len(rows) > DMAP_SEARCH_ROWS:
            rows = rows[:DMAP_SEARCH_ROWS]
            report.status, report.record_count = "truncated", len(rows)
            report.note = f"More than {DMAP_SEARCH_ROWS} SEMS site rows matched; narrow the query."
        reports.append(report)
        for row in rows:
            entry(row["epa_id"])["dmap"] = row

    _enrich(
        sites,
        points=True,
        boundaries=True,
        site_table=inventory_scope == "sems_candidates",
        budget=budget,
        reports=reports,
        warnings=warnings,
    )
    results = [_merge_site(site) for site in sites.values()]
    if npl_status:
        kept = []
        for site in results:
            listing = [s.normalized for s in _listing_statuses(site["statuses"]) if s.normalized != "unknown"]
            if npl_status in listing:
                kept.append(site)
            elif not listing:
                undetermined.append(site["epa_id"])
        results = kept
        undetermined = sorted(set(undetermined))
    results.sort(key=lambda site: ((site["name"] or "").casefold(), site["epa_id"]))
    return _result(
        reports,
        warnings,
        query=query,
        state=state,
        npl_status=npl_status,
        inventory_scope=inventory_scope,
        sites=results,
        undetermined_status_epa_ids=undetermined,
    )


LARGE_AREA_ACRES = 10_000


def area_summary(boundaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Largest source-reported feature area, flagged when it cannot be a contamination footprint."""
    acres = [b for b in boundaries if b["gis_area"] is not None and (b["gis_area_units"] or "").casefold() == "acres"]
    other_units = sorted(
        {b["gis_area_units"] or "no unit" for b in boundaries if b["gis_area"] is not None} - {"Acres", "acres"}
    )
    if not acres and not other_units:
        return None
    largest = max(acres, key=lambda b: b["gis_area"]) if acres else None
    flags = []
    if largest and largest["gis_area"] > LARGE_AREA_ACRES:
        flags.append(
            "very large; likely a facility perimeter, mining district, or study area, not a contamination footprint"
        )
    if other_units:
        flags.append(f"some features report units {', '.join(other_units)}, which are not areas")
    return {
        "acres": largest["gis_area"] if largest else None,
        "feature_type": largest["feature_type"] if largest else None,
        "features": len(boundaries),
        "flags": flags,
    }


def _federal_facility(boundaries: list[dict[str, Any]], dmap: dict[str, Any] | None) -> str | None:
    values = {b["federal_facility"]["label"] for b in boundaries if b["federal_facility"]["label"]}
    if dmap and dmap.get("federal_facility_ind") in {"Y", "N"}:
        values.add("Federal Facility" if dmap["federal_facility_ind"] == "Y" else "Not a Federal Facility")
    if not values:
        return None
    return values.pop() if len(values) == 1 else "sources disagree (" + "; ".join(sorted(values)) + ")"


def _merge_site(site: dict[str, Any]) -> dict[str, Any]:
    point, dmap, boundaries, frs = site["point"], site["dmap"], site["boundaries"], site["frs"]
    statuses: list[NplStatus] = []
    if point:
        statuses.append(point["status"])
    statuses += [boundary["status"] for boundary in boundaries]
    if dmap:
        statuses.append(dmap["status"])
    statuses += [record["status"] for record in frs]
    names = [record.get("name") or record.get("site_name") for record in [point, dmap, *boundaries, *frs] if record]
    if point:
        resolution = "npl_status_point"
    elif dmap:
        resolution = "sems_site_record"
    elif boundaries:
        resolution = "boundary_only"
    else:
        resolution = "frs_candidate_only"
    located = next((r for r in [point, dmap, *frs] if r and r.get("latitude") is not None), None)
    return {
        "epa_id": site["epa_id"],
        "name": next((name for name in names if name), None),
        "resolution": resolution,
        "sources": sorted({record["source"] for record in [point, dmap, *boundaries, *frs] if record}),
        "statuses": _unique_statuses(statuses),
        "status_conflict": status_conflict(_listing_statuses(statuses)),
        "point": point,
        "dmap": dmap,
        "boundary_feature_count": len(boundaries),
        "boundary_feature_types": sorted({boundary["feature_type"] or "(none)" for boundary in boundaries}),
        "frs": frs,
        "state_code": next(
            (r.get("state_code") for r in [point, dmap, *boundaries, *frs] if r and r.get("state_code")), None
        ),
        "city": next((r.get("city") for r in [point, dmap, *boundaries, *frs] if r and r.get("city")), None),
        "has_coordinates": located is not None,
        "has_geometry": bool(boundaries),
        "federal_facility": _federal_facility(boundaries, dmap),
        "construction_completion": (point or {}).get("dates", {}).get("construction_completion", {}).get("iso"),
        "deleted": (point or {}).get("dates", {}).get("deleted", {}).get("iso"),
        "area": area_summary(boundaries),
    }


def _unique_statuses(statuses: list[NplStatus]) -> list[NplStatus]:
    seen, unique = set(), []
    for status in statuses:
        key = (status.source, status.raw, status.source_date)
        if key not in seen:
            seen.add(key)
            unique.append(status)
    return unique


# =============================================================================
# 2. ROI DISCOVERY
# =============================================================================


def get_epa_superfund_sites_in_roi(
    latitude: float, longitude: float, buffer_miles: float = 25.0, inventory_scope: str = "npl_and_mapped"
) -> dict[str, Any]:
    inventory_scope = validate_scope(inventory_scope)
    budget = Budget()
    base = {
        "center": {"latitude": latitude, "longitude": longitude},
        "buffer_miles": buffer_miles,
        "inventory_scope": inventory_scope,
    }
    try:
        geometry = ArcGISService.create_roi_buffer(
            latitude, longitude, buffer_miles, headers=HEADERS, allow_redirects=False
        )
    except Exception:  # noqa: BLE001
        report = SourceReport(
            "roi_buffer", "ArcGIS GeometryServer ROI buffer", "failed", note="The ROI buffer could not be created."
        )
        return _result([report], [], sites=[], **base)

    reports: list[SourceReport] = []
    sites: dict[str, dict[str, Any]] = {}

    def entry(epa_id: str) -> dict[str, Any]:
        return sites.setdefault(epa_id, {"epa_id": epa_id, "point": None, "boundaries": [], "frs": [], "dmap": None})

    for spec in (NPL_POINTS, SITE_BOUNDARIES) + ((FRS_SEMS,) if inventory_scope == "sems_candidates" else ()):
        where = "PGM_SYS_ACRNM = 'SEMS'" if spec is FRS_SEMS else "1=1"
        records, report = layer_records(
            spec, where=where, budget=budget, max_features=ROI_MAX_FEATURES, geometry=geometry, return_geometry=True
        )
        reports.append(report)
        for record in records:
            if spec is NPL_POINTS:
                entry(record["epa_id"])["point"] = record
            elif spec is SITE_BOUNDARIES:
                entry(record["epa_id"])["boundaries"].append(record)
            else:
                entry(record["epa_id"] or f"FRS:{record['registry_id']}")["frs"].append(record)

    warnings: list[str] = []
    basis_by_id = {
        epa_id: "+".join(
            label for label, present in (("point", site["point"]), ("polygon", site["boundaries"])) if present
        )
        or "frs_candidate"
        for epa_id, site in sites.items()
    }
    in_roi_points = {epa_id for epa_id, site in sites.items() if site["point"]}
    _enrich(
        sites,
        points=True,
        boundaries=False,
        site_table=inventory_scope == "sems_candidates",
        budget=budget,
        reports=reports,
        warnings=warnings,
    )
    results = []
    for epa_id, site in sites.items():
        merged = _merge_site(site)
        point, boundaries, frs = (site["point"] if epa_id in in_roi_points else None), site["boundaries"], site["frs"]
        candidates: list[tuple[float, str]] = []
        if point and point.get("latitude") is not None:
            candidates.append((distance_miles(latitude, longitude, point["latitude"], point["longitude"]), "npl_point"))
        inside_type = None
        for boundary in boundaries:
            miles, how = polygon_distance_miles(latitude, longitude, boundary.get("rings"))
            if miles is not None:
                candidates.append((miles, how))
                if how == "inside_site_polygon" and inside_type is None:
                    inside_type = boundary["feature_type"] or "untyped"
        if not candidates:
            for record in frs:
                if record.get("latitude") is not None:
                    candidates.append(
                        (distance_miles(latitude, longitude, record["latitude"], record["longitude"]), "frs_point")
                    )
        nearest = min(candidates) if candidates else (None, None)
        merged.update(
            {
                "match_basis": basis_by_id[epa_id],
                "frs_matched": bool(frs),
                "distance_miles": round(nearest[0], 3) if nearest[0] is not None else None,
                "distance_basis": nearest[1],
                "inside_feature_type": inside_type,
            }
        )
        for boundary in boundaries:
            boundary.pop("rings", None)
        results.append(merged)
    results.sort(
        key=lambda s: (
            s["distance_miles"] is None,
            s["distance_miles"] or 0.0,
            (s["name"] or "").casefold(),
            s["epa_id"],
        )
    )
    if any(report.status == "truncated" for report in reports):
        warnings.append("A layer reached its feature cap; site grouping may be incomplete and counts are lower bounds.")
    return _result(reports, warnings, sites=results, **base)


# =============================================================================
# 3. SITE
# =============================================================================


def get_epa_superfund_site(
    epa_id: str | None = None, sems_id: str | None = None, frs_registry_id: str | None = None
) -> dict[str, Any]:
    provided = [value for value in (epa_id, sems_id, frs_registry_id) if value is not None]
    if len(provided) != 1:
        raise ValueError("provide exactly one of epa_id, sems_id, or frs_registry_id")
    epa_id = validate_epa_id(epa_id) if epa_id is not None else None
    sems_id = validate_sems_id(sems_id) if sems_id is not None else None
    frs_registry_id = validate_frs_registry_id(frs_registry_id) if frs_registry_id is not None else None
    budget = Budget()
    identity = resolve_identity(
        epa_id=epa_id, sems_id=sems_id, frs_registry_id=frs_registry_id, budget=budget, need_site_table=True
    )
    reports, warnings = list(identity.pop("reports")), list(identity.pop("warnings"))
    mapped: dict[str, Any] = {}
    resolved = identity["epa_id"]
    if resolved:
        where = f"EPA_ID = {sql_literal(resolved)}"
        for spec in (SITE_BOUNDARIES, OU_BOUNDARIES, IC_BOUNDARIES):
            records, report = layer_records(spec, where=where, budget=budget, max_features=LOOKUP_MAX_FEATURES)
            reports.append(report)
            mapped[spec.key] = records
        if not identity["frs"]:
            frs, report = layer_records(
                FRS_SEMS,
                where=f"PGM_SYS_ID = {sql_literal(resolved)} AND PGM_SYS_ACRNM = 'SEMS'",
                budget=budget,
                max_features=50,
            )
            reports.append(report)
            identity["frs"] = frs
    reuse = None
    if identity.get("sems_id") and not identity.get("conflict"):
        records, report = layer_records(
            REUSE_POINTS, where=f"Site_ID = {int(identity['sems_id'])}", budget=budget, max_features=10
        )
        reports.append(report)
        reuse = {"listed": bool(records), "records": records, "report": report}
    statuses = []
    if identity["point"]:
        statuses.append(identity["point"]["status"])
    statuses += [record["status"] for record in mapped.get("site_boundaries", [])]
    if identity["dmap"]:
        statuses.append(identity["dmap"]["status"])
    statuses += [record["status"] for record in identity["frs"]]
    site_found = bool(identity["point"] or identity["dmap"] or mapped.get("site_boundaries"))
    return _result(
        reports,
        warnings,
        requested={"epa_id": epa_id, "sems_id": sems_id, "frs_registry_id": frs_registry_id},
        identity=identity,
        mapped=mapped,
        reuse=reuse,
        area=area_summary(mapped.get("site_boundaries", [])),
        statuses=_unique_statuses(statuses),
        status_conflict=status_conflict(_listing_statuses(statuses)),
        site_found=site_found,
    )


# =============================================================================
# SHARED RECORD SOURCES (SEMS DECISIONS, FEDERAL REGISTER, SITE PROFILE LINK)
# =============================================================================

DECISION_TYPES = {
    "RO": "record_of_decision",
    "JQ": "rod_amendment",
    "EH": "explanation_of_significant_differences",
}


def _sems_operable_units(site: dict[str, Any] | None, budget: Budget, reports: list[SourceReport]) -> dict[str, dict]:
    """Group the SEMS contaminants table by operable unit: decision-document types, media, and row counts."""
    if not site:
        return {}
    rows, report = dmap_contaminant_rows(site["site_id"], DMAP_CONTAMINANT_ROWS, budget)
    report.label = "Envirofacts SEMS contaminants table (OU and decision references)"
    reports.append(report)
    units: dict[str, dict] = {}
    for row in rows:
        ou_id = str(row.get("operable_unit_num") or "").strip()
        if not ou_id.isdigit() or len(ou_id) > 2:
            continue
        unit = units.setdefault(ou_id.zfill(2), {"decisions": set(), "media": set(), "rows": 0})
        unit["rows"] += 1
        if row.get("action_name"):
            unit["decisions"].add((str(row.get("type_code") or ""), str(row["action_name"])))
        if row.get("media_name"):
            unit["media"].add(str(row["media_name"]))
    return dict(sorted(units.items()))


def _site_names(identity: dict[str, Any]) -> list[str]:
    names = [identity.get("name"), (identity.get("dmap") or {}).get("name")]
    return sorted({normalize_name(name) for name in names if name} - {""}, key=len)


def _federal_register(
    identity: dict[str, Any], budget: Budget, reports: list[SourceReport], published_on_or_after: str | None = None
) -> list[dict[str, Any]]:
    """EPA Federal Register documents that contain the site's name, marked by where the name appears."""
    # The shortest published name finds the most notices; every name variant is used to judge association.
    published = [name for name in (identity.get("name"), (identity.get("dmap") or {}).get("name")) if name]
    phrase = " ".join(re.sub(r"[^A-Za-z0-9 .&'-]+", " ", min(published, key=len) if published else "").split())[:100]
    if len(phrase) < 3:
        reports.append(
            SourceReport(
                "federal_register",
                "Federal Register API (EPA documents)",
                "unsupported",
                note="No site name was resolved.",
            )
        )
        return []
    documents, report = federal_register_documents(phrase, budget, published_on_or_after)
    reports.append(report)
    names = _site_names(identity)
    dates = (identity.get("point") or {}).get("dates", {})
    milestones = {value["iso"]: key for key, value in dates.items() if value.get("iso")}
    for document in documents:
        heading = normalize_name(f"{document['title']} {document['action']}")
        named = any(f" {name} " in f" {heading} " for name in names)
        milestone = milestones.get(document["published"]) if "national priorities list" in heading else None
        if named:
            association = "candidate (site named in the document title or action)"
        elif milestone:
            association = f"candidate (NPL rule published on this site's {milestone.replace('_', ' ')} date)"
        else:
            association = "site mentioned in the document text only; relation to this site unverified"
        document["association"] = association
        document["named_in_heading"] = named
        document["milestone_match"] = milestone
    # Text-only mentions (often multi-site NPL rules) sort after documents tied to this site.
    documents.sort(key=lambda d: not (d["named_in_heading"] or d["milestone_match"]))
    return documents


def _profile_report(identity: dict[str, Any]) -> SourceReport:
    """State plainly that EPA's site-profile pages are not retrieved, with the official link for a person."""
    point = identity.get("point") or {}
    url = ((point.get("links") or {}).get("site_progress_profile") or {}).get("url")
    return SourceReport("epa_site_profile", "EPA site profile pages", "unsupported", note=NOT_RETRIEVED_NOTE, url=url)


# =============================================================================
# 4-5. OPERABLE UNITS AND INSTITUTIONAL CONTROLS
# =============================================================================

_OU_NAME_RE = re.compile(r"^\s*OU\s*-?\s*0*(\d{1,2})\b", re.IGNORECASE)


def get_epa_superfund_operable_units(epa_id: str) -> dict[str, Any]:
    epa_id = validate_epa_id(epa_id)
    budget = Budget()
    identity = resolve_identity(epa_id=epa_id, budget=budget, need_site_table=True)
    reports, warnings = list(identity.pop("reports")), list(identity.pop("warnings"))
    units = _sems_operable_units(identity["dmap"], budget, reports)
    features, report = layer_records(
        OU_BOUNDARIES, where=f"EPA_ID = {sql_literal(epa_id)}", budget=budget, max_features=LOOKUP_MAX_FEATURES
    )
    reports.append(report)
    reports.append(_profile_report(identity))
    records: list[dict[str, Any]] = [
        {
            "kind": "sems_ou",
            "ou_id": ou_id,
            "decisions": sorted(name for _code, name in unit["decisions"]),
            "media": sorted(unit["media"]),
            "rows": unit["rows"],
        }
        for ou_id, unit in units.items()
    ]
    for feature in features:
        match = _OU_NAME_RE.match(feature.get("feature_name") or "")
        candidate = match.group(1).zfill(2) if match else None
        if candidate and candidate in units:
            crosswalk = (
                f"candidate (unverified): feature name suggests OU {candidate}, which SEMS decision records list"
            )
        elif candidate:
            crosswalk = f"candidate (unverified): feature name suggests OU {candidate}; not in SEMS decision records"
        else:
            crosswalk = "none: no OU number in the feature name"
        records.append({"kind": "map_feature", "ou_id_candidate": candidate, "crosswalk": crosswalk, **feature})
    return _result(
        reports,
        warnings,
        epa_id=epa_id,
        name=identity.get("name"),
        records=records,
        sems_ou_count=len(units),
        map_feature_count=len(features),
    )


def get_epa_superfund_institutional_controls(epa_id: str) -> dict[str, Any]:
    epa_id = validate_epa_id(epa_id)
    budget = Budget()
    features, report = layer_records(
        IC_BOUNDARIES, where=f"EPA_ID = {sql_literal(epa_id)}", budget=budget, max_features=LOOKUP_MAX_FEATURES
    )
    return _result([report], [], epa_id=epa_id, records=features)


# =============================================================================
# 6. DOCUMENTS
# =============================================================================

# Title-inferred categories, most specific first: correspondence or a proposed plan about a decision is not the
# decision, and an ESD or amendment to a ROD is not the original ROD.
DOCUMENT_KEYWORDS = (
    ("correspondence", ("CORRESPONDENCE", "CONCURRENCE", "LETTER", "COMMENTS ON", "MEMORANDUM")),
    ("community_involvement", ("COMMUNITY INVOLVEMENT", "COMMUNITY UPDATE", "PUBLIC MEETING")),
    ("proposed_plan", ("PROPOSED PLAN", "PROPOSED CLEANUP PLAN")),
    ("five_year_review", ("FIVE-YEAR REVIEW", "FIVE YEAR REVIEW", "5-YEAR REVIEW")),
    ("explanation_of_significant_differences", ("EXPLANATION OF SIGNIFICANT DIFFERENCE", " ESD ")),
    (
        "rod_amendment",
        (
            "RECORD OF DECISION AMENDMENT",
            "ROD AMENDMENT",
            "AMENDED RECORD OF DECISION",
            "AMENDMENT TO THE RECORD OF DECISION",
        ),
    ),
    ("record_of_decision", ("RECORD OF DECISION", " ROD ")),
    ("institutional_controls", ("INSTITUTIONAL CONTROL",)),
    ("close_out_report", ("CLOSE OUT REPORT", "CLOSEOUT REPORT", "CLOSE-OUT REPORT")),
    ("deletion", ("DELETION", "INTENT TO DELETE")),
    ("fact_sheet", ("FACT SHEET",)),
)
LINK_LABELS = {
    "site_progress_profile": "EPA site progress profile",
    "listing_narrative": "NPL site listing narrative",
    "proposed_fr_notice": "Federal Register: proposed for NPL",
    "final_fr_notice": "Federal Register: final NPL listing",
    "notice_of_intent_to_delete_fr_notice": "Federal Register: notice of intent to delete",
    "deletion_fr_notice": "Federal Register: deletion",
    "notice_of_data_availability": "Notice of data availability",
    "restoration_fr_notice": "Federal Register: restoration",
}
FR_LINKS = tuple(
    (key, label) for key, label in LINK_LABELS.items() if key not in {"site_progress_profile", "listing_narrative"}
)


def _document_category(title: str | None, default: str = "other") -> str:
    padded = f" {(title or '').upper()} "
    for category, keywords in DOCUMENT_KEYWORDS:
        if any(keyword in padded for keyword in keywords):
            return category
    return default


def _link_date(entry: dict[str, Any]) -> str | None:
    match = re.search(r"\d{2}/\d{2}/\d{4}", entry.get("text") or "")
    return parse_mdy(match.group(0)) if match else None


def get_epa_superfund_documents(
    epa_id: str, query: str | None = None, document_type: str | None = None
) -> dict[str, Any]:
    epa_id = validate_epa_id(epa_id)
    query = validate_query(query)
    document_type = validate_document_type(document_type)
    budget = Budget()
    identity = resolve_identity(epa_id=epa_id, budget=budget, need_site_table=True)
    reports, warnings = list(identity.pop("reports")), list(identity.pop("warnings"))
    records: list[dict[str, Any]] = []
    point = identity["point"]
    if point:
        for key, label in (("listing_narrative", LINK_LABELS["listing_narrative"]), *FR_LINKS):
            entry = point["links"].get(key) or {}
            if entry.get("url"):
                records.append(
                    {
                        "title": label,
                        "category": "listing_narrative" if key == "listing_narrative" else "federal_register_notice",
                        "date": _link_date(entry),
                        "url": entry["url"],
                        "source": "NPL status layer link",
                        "identifier": None,
                        "basis": "verified (published for this EPA ID)",
                    }
                )
    profile_url = _profile_report(identity).url
    for ou_id, unit in _sems_operable_units(identity["dmap"], budget, reports).items():
        for code, name in sorted(unit["decisions"]):
            records.append(
                {
                    "title": f"{name} (OU {ou_id})",
                    "category": DECISION_TYPES.get(code, _document_category(name)),
                    "date": None,
                    "url": profile_url,
                    "source": "SEMS contaminant records",
                    "identifier": None,
                    "basis": "decision type referenced by this site's contaminant records; the document itself is listed on the EPA site profile (link only)",
                }
            )
    boundaries, report = layer_records(
        SITE_BOUNDARIES, where=f"EPA_ID = {sql_literal(epa_id)}", budget=budget, max_features=LOOKUP_MAX_FEATURES
    )
    reports.append(report)
    links = {}
    for boundary in boundaries:
        for url, label in (
            (boundary["site_info_url"], "EPA site page"),
            (boundary["feature_info_url"], boundary["feature_info_label"]),
        ):
            if url and url not in links:
                links[url] = label or "Feature information"
    for url, label in links.items():
        records.append(
            {
                "title": label,
                "category": "other",
                "date": None,
                "url": url,
                "source": "Total-site boundary layer link",
                "identifier": None,
                "basis": "verified (published for this EPA ID)",
            }
        )
    for document in _federal_register(identity, budget, reports):
        records.append(
            {
                "title": document["title"],
                "category": _document_category(f"{document['title']} {document['action']}", "federal_register_notice"),
                "date": document["published"],
                "url": document["url"],
                "source": f"Federal Register {document['type'] or 'document'}",
                "identifier": document["document_number"],
                "basis": document["association"],
                "text_only": not (document["named_in_heading"] or document["milestone_match"]),
            }
        )
    reports.append(_profile_report(identity))
    if query:
        records = [doc for doc in records if query.casefold() in (doc["title"] or "").casefold()]
    if document_type:
        records = [doc for doc in records if doc["category"] == document_type]
    records.sort(
        key=lambda doc: (
            doc.get("text_only", False),
            doc["date"] is None,
            _invert(doc["date"] or ""),
            doc["title"] or "",
        )
    )
    return _result(
        reports,
        warnings,
        epa_id=epa_id,
        name=identity.get("name"),
        query=query,
        document_type=document_type,
        records=records,
        profile_url=profile_url,
    )


def _invert(iso: str) -> str:
    """Sort key placing later ISO dates first."""
    return "".join(chr(0x7F - ord(character)) for character in iso)


# =============================================================================
# 7. CLEANUP ACTIONS
# =============================================================================

POINT_MILESTONES = (
    ("proposed", "Proposed to the NPL"),
    ("listed", "Finalized on the NPL"),
    ("construction_completion", "Construction completion milestone"),
    ("notice_of_intent_to_delete", "Notice of intent to delete"),
    ("deleted", "Deleted from the NPL"),
)


def get_epa_superfund_cleanup_actions(epa_id: str, operable_unit: str | None = None) -> dict[str, Any]:
    epa_id = validate_epa_id(epa_id)
    operable_unit = validate_operable_unit(operable_unit)
    budget = Budget()
    identity = resolve_identity(epa_id=epa_id, budget=budget, need_site_table=True)
    reports, warnings = list(identity.pop("reports")), list(identity.pop("warnings"))
    records: list[dict[str, Any]] = []
    point = identity["point"]
    if point and operable_unit is None:
        for key, label in POINT_MILESTONES:
            value = point["dates"][key]
            if value["raw"]:
                records.append(
                    {"kind": "npl_milestone", "label": label, "date": value["iso"], "raw": value["raw"], "ou_id": None}
                )
    for ou_id, unit in _sems_operable_units(identity["dmap"], budget, reports).items():
        if operable_unit is not None and ou_id != operable_unit:
            continue
        for _code, name in sorted(unit["decisions"]):
            records.append({"kind": "sems_decision", "label": name, "date": None, "raw": None, "ou_id": ou_id})
    if operable_unit is None:
        for document in _federal_register(identity, budget, reports):
            if document["named_in_heading"] or document["milestone_match"]:
                records.append(
                    {
                        "kind": "federal_register_action",
                        "label": document["action"] or document["title"],
                        "date": document["published"],
                        "raw": document["document_number"],
                        "ou_id": None,
                        "url": document["url"],
                    }
                )
    reports.append(_profile_report(identity))
    records.sort(key=lambda r: (r["date"] is None, r["date"] or "", r["ou_id"] or "", r["label"]))
    return _result(
        reports,
        warnings,
        epa_id=epa_id,
        name=identity.get("name"),
        operable_unit=operable_unit,
        records=records,
    )


# =============================================================================
# 8. CONTAMINANTS
# =============================================================================


def get_epa_superfund_contaminants(
    epa_id: str, operable_unit: str | None = None, media: str | None = None
) -> dict[str, Any]:
    epa_id = validate_epa_id(epa_id)
    operable_unit = validate_operable_unit(operable_unit)
    media = validate_media(media)
    budget = Budget()
    site, site_report = _dmap_site("epa_id", epa_id, budget)
    reports, warnings = [site_report], []
    records: list[dict[str, Any]] = []
    query_url = None
    if site:
        rows, report = dmap_contaminant_rows(site["site_id"], DMAP_CONTAMINANT_ROWS, budget)
        reports.append(report)
        query_url = report.url
        records = [
            row
            for row in rows
            if (operable_unit is None or str(row.get("operable_unit_num") or "").strip().zfill(2) == operable_unit)
            and (media is None or str(row.get("media_name") or "").casefold() == media.casefold())
        ]
        records.sort(
            key=lambda row: (
                str(row.get("operable_unit_num") or ""),
                str(row.get("media_name") or "").casefold(),
                str(row.get("preferred_contaminant_name") or "").casefold(),
                str(row.get("action_name") or ""),
                row.get("seq") if isinstance(row.get("seq"), int) else 0,
            )
        )
    elif site_report.status == "empty":
        warnings.append("This EPA ID is not in the Envirofacts SEMS site table, so no contaminant join was possible.")
    return _result(
        reports,
        warnings,
        epa_id=epa_id,
        site=site,
        operable_unit=operable_unit,
        media=media,
        records=records,
        query_url=query_url,
    )


# =============================================================================
# 9. PUBLIC NOTICES
# =============================================================================

NPL_LINK_KINDS = {
    "proposed_fr_notice": "npl_listing",
    "final_fr_notice": "npl_listing",
    "notice_of_intent_to_delete_fr_notice": "deletion",
    "deletion_fr_notice": "deletion",
    "notice_of_data_availability": "data_availability",
    "restoration_fr_notice": "restoration",
}
NOTICE_KINDS = (
    ("extension", ("EXTEND", "EXTENSION")),
    ("partial_deletion", ("PARTIAL DELETION", "PARTIAL NPL DELETION", "PARTIALLY DELETE")),
    ("deletion", ("DELET",)),
    ("settlement", ("SETTLEMENT", "CONSENT DECREE", "COST RECOVERY", "PROSPECTIVE PURCHASER")),
    ("npl_listing", ("NATIONAL PRIORITIES LIST", "NPL")),
    ("cleanup_proposal", ("PROPOSED PLAN", "CLEANUP PLAN", "PROPOSED CLEANUP", "CLEANUP PROPOSAL")),
    ("five_year_review", ("FIVE-YEAR REVIEW", "FIVE YEAR REVIEW")),
    ("meeting", ("MEETING",)),
)


def _notice_kind(value: str | None) -> str:
    upper = (value or "").upper()
    return next((kind for kind, keywords in NOTICE_KINDS if any(keyword in upper for keyword in keywords)), "other")


def _notice_stage(document_type: str | None, value: str | None) -> str:
    upper = f"{document_type or ''} {value or ''}".upper()
    if "PROPOSED RULE" in upper or any(
        word in upper for word in ("PROPOS", "INTENT TO DELETE", "REQUEST FOR PUBLIC COMMENT")
    ):
        return "proposed"
    if upper.startswith("RULE") or "FINAL RULE" in upper or "NOTICE OF DELETION" in upper:
        return "final"
    return "not stated"


def _due_status(due: str, as_of: str) -> str:
    """Date-only deadlines carry time-zone uncertainty, so a deadline within a day of today stays ambiguous."""
    gap = (datetime.fromisoformat(as_of) - datetime.fromisoformat(due)).days
    if gap >= 2:
        return "comment period closed"
    if gap >= -1:
        return "comment period closes today or within time-zone uncertainty"
    return "comment period open per the published close date"


def get_epa_superfund_public_notices(epa_id: str, published_on_or_after: str | None = None) -> dict[str, Any]:
    epa_id = validate_epa_id(epa_id)
    published_on_or_after = validate_date(published_on_or_after, "published_on_or_after")
    budget = Budget()
    identity = resolve_identity(epa_id=epa_id, budget=budget, need_site_table=True)
    reports, warnings = list(identity.pop("reports")), list(identity.pop("warnings"))
    as_of = datetime.now(UTC).date().isoformat()
    events: list[dict[str, Any]] = []
    point = identity["point"]
    if point:
        for key, label in FR_LINKS:
            entry = point["links"].get(key) or {}
            if entry.get("url"):
                events.append(
                    {
                        "kind": NPL_LINK_KINDS.get(key, "npl_listing"),
                        "stage": "not stated",
                        "title": label,
                        "published": _link_date(entry),
                        "comments_due": None,
                        "dockets": [],
                        "url": entry["url"],
                        "association": "verified (NPL status layer link for this EPA ID)",
                    }
                )
    for document in _federal_register(identity, budget, reports, published_on_or_after):
        heading = f"{document['title']} {document['action']}"
        twin = next((event for event in events if document["url"] and event["url"] == document["url"]), None)
        if twin is not None:
            twin["federal_register_url"] = document["url"]
            twin["dockets"] = document["docket_ids"]
            continue
        named = document["named_in_heading"] or bool(document["milestone_match"])
        events.append(
            {
                "kind": _notice_kind(heading) if named else "federal_register_mention",
                "stage": _notice_stage(document["type"], document["action"]) if named else "not stated",
                "text_only": not named,
                "title": document["title"],
                "action": document["action"],
                "published": document["published"],
                "comments_due": document["comments_close_on"],
                "dockets": document["docket_ids"],
                "url": document["url"],
                "association": document["association"],
            }
        )
    for event in events:
        if event["comments_due"]:
            event["status"] = _due_status(event["comments_due"], as_of)
    _relate_extensions(events)
    if published_on_or_after:
        events = [
            event for event in events if event["published"] is None or event["published"] >= published_on_or_after
        ]
        for event in events:
            event["publication_date_unknown"] = event["published"] is None
    events.sort(key=lambda e: (e["published"] or "", e["title"] or ""), reverse=True)
    events.sort(key=lambda e: e.get("text_only", False))
    reports.append(_profile_report(identity))
    reports.append(
        SourceReport(
            "epa_notice_search",
            "EPA public notice and news-release searches",
            "unsupported",
            note=(
                "Not queried: www.epa.gov/robots.txt disallows these search pages. Local five-year-review "
                "announcements, meetings, and comment extensions posted only there may be missing."
            ),
        )
    )
    return _result(
        reports,
        warnings,
        epa_id=epa_id,
        name=identity.get("name"),
        as_of=as_of,
        published_on_or_after=published_on_or_after,
        events=events,
    )


def _relate_extensions(events: list[dict[str, Any]]) -> None:
    """Point an extension at possible earlier notices; nothing is overwritten and no pairing is asserted."""
    for event in events:
        if event["kind"] == "extension":
            event["may_revise"] = [
                other["title"]
                for other in events
                if other is not event
                and other["kind"] in {"cleanup_proposal", "deletion", "partial_deletion", "settlement"}
            ]


# =============================================================================
# FORMATTERS
# =============================================================================


def _status_line(status: NplStatus) -> str:
    raw = md(status.raw, 60) if status.raw else "null"
    label = f" ({md(status.label, 60)})" if status.label and status.label != status.raw else ""
    if status.source == "frs_sems":
        dated = f", FRS record updated {status.source_date}" if status.source_date else ""
        return f"FRS program-interest label `{raw}`{dated} (not listing evidence)"
    dated = f", feature last edited {status.source_date}" if status.source_date else ""
    return (
        f"{STATUS_TEXT[status.normalized]} — {SOURCE_SHORT.get(status.source, status.source)} raw `{raw}`{label}{dated}"
    )


def _no_records(result: dict[str, Any], sentence: str) -> list[str]:
    """Say 'none' only when every queried source completed; otherwise say what was not determined."""
    if result.get("data_unavailable"):
        return []
    unresolved = [f"{md(r.label, 80)} ({r.status})" for r in result["reports"] if not r.usable]
    if unresolved:
        return [f"No records from the sources that responded. Not determined for: {'; '.join(unresolved)}.", ""]
    return [sentence, ""]


def _sources(reports: list[SourceReport]) -> list[str]:
    lines = ["### Sources", "", "| Source | State | Records | Note |", "|---|---|---|---|"]
    for report in reports:
        label = link(report.label, report.url, 90)
        note = md(report.note, 260) or "—"
        lines.append(f"| {label} | {report.status} | {report.record_count} | {note} |")
    return lines + [""]


def _header(title: str, result: dict[str, Any], lines: list[str]) -> list[str]:
    out = [f"## {title}", "", *lines, f"**Retrieved:** {result['retrieved_at']}", ""]
    if result.get("result_fingerprint") and any(key in result for key in ("sites", "records", "events")):
        out += [
            f"**Result fingerprint:** `{result['result_fingerprint']}`",
            "",
            "Reuse this as result_fingerprint with the same filters on subsequent pages. "
            "Changed evidence or source coverage requires restarting. This is not an atomic upstream snapshot.",
            "",
        ]
    if result.get("data_unavailable"):
        out += [
            "> ⚠️ Every queried source failed or was skipped. These results are unavailable, not a no-hit finding.",
            "",
        ]
    for warning in result.get("warnings", []):
        out += [f"> Warning: {md(warning, 400)}", ""]
    return out


def _paged(
    items: list[Any], offset: int, limit: int, render: Callable[[Any], list[str]], noun: str, lower_bound: bool
) -> list[str]:
    page = Page(items, offset, limit)
    total = f"{page.total}{' (lower bound)' if lower_bound else ''}"
    if not items:
        return []
    if not page.window:
        return [f"No {noun} at result_offset={offset}; {total} {noun} are available.", ""]
    lines = [f"### {noun.capitalize()} ({offset + 1}–{page.end} of {total})", ""]
    for item in page.window:
        lines += render(item)
    lines.append("")
    if page.end < page.total:
        lines += [f"More {noun} are available. Call again with result_offset={page.end} and max_results={limit}.", ""]
    return lines


def _site_line(site: dict[str, Any]) -> list[str]:
    point = site.get("point") or {}
    profile = (point.get("links") or {}).get("site_progress_profile") or {}
    identifier = (
        f"FRS candidate {md(site['epa_id'][4:], 30)}"
        if site["epa_id"].startswith("FRS:")
        else f"EPA ID {site['epa_id']}"
    )
    pieces = [f"- **{md(site['name'] or 'Unnamed site', 120)}** — {identifier}"]
    location = ", ".join(filter(None, [md(site.get("city"), 60), site.get("state_code")]))
    if location:
        pieces.append(location)
    pieces.append(f"resolution: {site['resolution'].replace('_', ' ')}")
    if site.get("match_basis"):
        pieces.append(
            f"match: {site['match_basis']}{' + FRS interest' if site.get('frs_matched') and site['match_basis'] != 'frs_candidate' else ''}"
        )
    if site.get("distance_miles") is not None:
        if site["distance_basis"] == "inside_site_polygon":
            pieces.append(f"ROI center inside a mapped '{md(site.get('inside_feature_type'), 60)}' feature")
        else:
            approx = (
                " (approx.; nearest generalized boundary vertex, the boundary may be closer)"
                if site["distance_basis"] == "nearest_polygon_vertex_approximate"
                else ""
            )
            pieces.append(f"{site['distance_miles']:.3f} mi{approx}")
    line = " — ".join(pieces)
    if profile.get("url"):
        line += f" — {link('EPA site profile', profile['url'])}"
    lines = [line]
    for status in site["statuses"]:
        lines.append(f"  - Status: {_status_line(status)}")
    if site["status_conflict"]:
        lines.append("  - ⚠️ Sources disagree on listing status; none was selected.")
    if site.get("boundary_feature_count"):
        types = ", ".join(md(value, 60) for value in site["boundary_feature_types"])
        lines.append(f"  - Mapped total-site features: {site['boundary_feature_count']} ({types})")
    program = []
    if site.get("federal_facility"):
        program.append(f"federal facility: {md(site['federal_facility'], 80)}")
    if site.get("construction_completion"):
        program.append(f"construction completion milestone {site['construction_completion']}")
    if site.get("deleted"):
        program.append(f"deleted from NPL {site['deleted']}")
    area = site.get("area")
    if area and area["acres"] is not None:
        program.append(f"largest published feature area {area['acres']:g} acres ({md(area['feature_type'], 40)})")
    if program:
        lines.append("  - " + "; ".join(program))
    if area and area["flags"]:
        lines.append("  - ⚠️ Area: " + "; ".join(area["flags"]))
    if point.get("partial_deletion", {}).get("value") == "yes":
        lines.append("  - Partial deletion flagged in the NPL status layer (the deleted portion is not mapped)")
    dmap = site.get("dmap")
    if dmap:
        indicators = [f"archived {dmap['archived']['indicator'] or 'not published'}"]
        if dmap["non_npl_status"]["code"]:
            indicators.append(
                f"non-NPL status {md(dmap['non_npl_status']['name'], 160)} ({dmap['non_npl_status']['code']})"
            )
        if dmap["saa_agreement_site_ind"] == "Y":
            indicators.append("Superfund Alternative Approach agreement indicator Y")
        lines.append(f"  - SEMS site table: SEMS id {dmap['site_id']}; " + "; ".join(indicators))
    for record in site.get("frs") or []:
        lines.append(
            f"  - FRS registry {record['registry_id'] or 'not published'} / program id {md(record['program_id'], 20)} "
            f"({md(record['interest_type'], 40)}) — facility-interest record, not SEMS site identity"
        )
    if site["resolution"] == "frs_candidate_only":
        lines.append("  - Unresolved candidate: no NPL point, boundary, or SEMS site row matched this FRS interest.")
    if not site["has_coordinates"] and not site.get("has_geometry"):
        lines.append("  - No published coordinates or mapped geometry in the matched records.")
    return lines


def format_search_results(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    filters = ", ".join(
        f"{name}={md(value, 100)}"
        for name, value in (
            ("query", result["query"]),
            ("state", result["state"]),
            ("npl_status", result["npl_status"]),
        )
        if value
    )
    lines = _header(
        "EPA Superfund Site Search",
        result,
        [
            f"**Filters:** {filters}",
            f"**Inventory scope:** `{result['inventory_scope']}` — {SCOPE_NOTE[result['inventory_scope']]}",
        ],
    )
    sites = result["sites"]
    counts = {}
    for site in sites:
        counts[site["resolution"]] = counts.get(site["resolution"], 0) + 1
    lower = _lower_bound(result["reports"])
    lines += [f"**Sites:** {len(sites)}{' (lower bound)' if lower else ''}", ""]
    if counts:
        lines += [", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in sorted(counts.items())), ""]
    if result["undetermined_status_epa_ids"]:
        ids = ", ".join(result["undetermined_status_epa_ids"][:20])
        lines += [
            f"**Status eligibility undetermined:** {len(result['undetermined_status_epa_ids'])} matching boundary record(s) "
            f"publish no NPL status and were not counted as matching npl_status: {ids}",
            "",
        ]
    if not sites:
        lines += _no_records(
            result,
            "No matching records in the queried inventories. This does not establish that no Superfund site matches.",
        )
    lines += _paged(sites, result_offset, max_results, _site_line, "sites", lower)
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: 'Not on the NPL' is a listing state, not a cleanup outcome. Superfund Alternative Approach participation is "
        "reported only from the SEMS site table's explicit indicator (use get_epa_superfund_site).",
        NOT_A_DETERMINATION,
    ]
    return "\n".join(lines)


def format_roi_results(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    center = result["center"]
    lines = _header(
        "EPA Superfund Sites in ROI",
        result,
        [
            f"**Location:** ({center['latitude']}, {center['longitude']})",
            f"**Buffer:** {result['buffer_miles']} miles",
            f"**Inventory scope:** `{result['inventory_scope']}` — {SCOPE_NOTE[result['inventory_scope']]}",
        ],
    )
    sites = result["sites"]
    lower = _lower_bound(result["reports"])
    basis_counts: dict[str, int] = {}
    for site in sites:
        basis_counts[site["match_basis"]] = basis_counts.get(site["match_basis"], 0) + 1
    lines += [f"**Sites:** {len(sites)}{' (lower bound)' if lower else ''}", ""]
    if basis_counts:
        lines += ["Match basis: " + ", ".join(f"{key}: {value}" for key, value in sorted(basis_counts.items())), ""]
    if not sites:
        lines += _no_records(
            result,
            "No published NPL points or total-site boundaries intersect the ROI. This cannot exclude unmapped sites, "
            "offsite impacts, or land-use restrictions.",
        )
    lines += _paged(sites, result_offset, max_results, _site_line, "sites", lower)
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: An NPL point is a reference location, not a footprint. A total-site polygon is a published research lead, "
        "not a survey, parcel boundary, or contamination extent; federal-facility polygons may follow the facility perimeter.",
        "Note: Polygon-only matches can occur when a site's representative point is outside the ROI or unpublished.",
        "Note: Most SEMS site-table records (including non-NPL and archived sites) publish no coordinates, so they "
        "cannot be found by location; use search_epa_superfund_sites with a name, city, county, or state.",
        NOT_A_DETERMINATION,
    ]
    return "\n".join(lines)


def format_site(result: dict[str, Any]) -> str:
    identity = result["identity"]
    point, dmap = identity["point"], identity["dmap"]
    lines = _header(
        "EPA Superfund Site",
        result,
        [f"**Requested:** {', '.join(f'{k}={v}' for k, v in result['requested'].items() if v)}"],
    )
    if not result["site_found"]:
        if identity["frs"]:
            lines += [
                "Only FRS SEMS facility-interest record(s) resolved. This is an unresolved candidate, not a full site profile.",
                "",
            ]
            for record in identity["frs"]:
                lines.append(
                    f"- FRS registry {record['registry_id']} / program id {md(record['program_id'], 20)} — {md(record['name'], 100)}"
                )
            lines.append("")
        else:
            lines += _no_records(result, "No site record resolved for this identifier in the queried sources.")
        return "\n".join(lines + _sources(result["reports"]) + [NOT_A_DETERMINATION])
    lines += [
        "### Identity",
        "",
        f"- EPA ID: {identity['epa_id']}",
        f"- SEMS site id: {identity['sems_id'] or 'not resolved'}"
        + (" (⚠️ crosswalk conflict)" if identity["conflict"] else ""),
        f"- Name: {md(identity['name'], 150) or 'not published'}",
        f"- Region: {identity['region'] or 'not published'}; state: {identity['state_code'] or 'not published'}",
    ]
    for record in identity["frs"]:
        lines.append(
            f"- FRS registry {record['registry_id']} (program {md(record['program_system'], 10)} {md(record['program_id'], 20)}); "
            "FRS identity is a facility-interest record, distinct from SEMS site identity"
        )
    lines += ["", "### Listing status by source", ""]
    lines += [f"- {_status_line(status)}" for status in result["statuses"]] or ["- No listing status published."]
    if result["status_conflict"]:
        lines.append("- ⚠️ Sources disagree; none was selected as authoritative.")
    if point:
        lines += ["", "### NPL milestones (NPL status layer)", ""]
        for key, label in POINT_MILESTONES:
            value = point["dates"][key]
            lines.append(f"- {label}: {value['iso'] or md(value['raw'], 40) or 'not published'}")
        if point["status"].normalized == "final" and point["dates"]["deleted"]["raw"]:
            lines.append(
                "  - ⚠️ The layer lists this site as final NPL but also publishes a deletion date; check the restoration notice."
            )
        if point["dates"]["construction_completion"]["raw"]:
            lines.append(
                "  - Construction completion is a named milestone, not completion of all cleanup or achievement of cleanup goals."
            )
        deletion = point["partial_deletion"]
        partial = {
            "yes": "flagged in the NPL status layer (the deleted portion is not mapped here)",
            "no": "not flagged in the NPL status layer (absence of a flag is not proof)",
        }.get(deletion["value"], "not determinable from the published value")
        lines.append(
            f"- Partial deletion: {partial}"
            + (f" — {link('EPA partial-deletion list', deletion['url'])}" if deletion["url"] else "")
        )
    lines += ["", "### Program indicators", ""]
    boundaries = result["mapped"].get("site_boundaries", [])
    federal = sorted({b["federal_facility"]["label"] or "not published" for b in boundaries})
    if federal:
        lines.append(f"- Federal facility (boundary layer): {', '.join(federal)}")
    if dmap:
        lines += [
            f"- Federal facility indicator (SEMS site table): {dmap['federal_facility_ind'] or 'not published'}",
            f"- Archived (SEMS site table): {dmap['archived']['indicator'] or 'not published'}"
            + (
                f", date {dmap['archived']['date']['iso'] or md(dmap['archived']['date']['raw'], 30)}"
                if dmap["archived"]["date"]["raw"]
                else ""
            )
            + (
                " (⚠️ indicator N but an archive date is published)"
                if dmap["archived"]["indicator"] == "N" and dmap["archived"]["date"]["raw"]
                else ""
            ),
            f"- Non-NPL status: {md(dmap['non_npl_status']['name'], 80) or 'none published'}"
            + (
                f" ({dmap['non_npl_status']['code']}, {dmap['non_npl_status']['date']['iso']})"
                if dmap["non_npl_status"]["code"]
                else ""
            ),
            f"- Superfund Alternative Approach agreement indicator: {dmap['saa_agreement_site_ind'] or 'not published'}",
        ]
    for record in identity["frs"]:
        lines.append(f"- FRS federal-facility code: {record['federal_facility_code'] or 'not published'}")
    lines += ["", "### Mapped evidence", ""]
    for spec in (SITE_BOUNDARIES, OU_BOUNDARIES, IC_BOUNDARIES):
        records = result["mapped"].get(spec.key)
        if records is None:
            continue
        types: dict[str, int] = {}
        for record in records:
            types[record["feature_type"] or "(none)"] = types.get(record["feature_type"] or "(none)", 0) + 1
        detail = ", ".join(f"{md(k, 60)}: {v}" for k, v in sorted(types.items())) or "none"
        lines.append(f"- {SOURCE_SHORT[spec.key]} features: {len(records)} ({detail})")
    areas = [f"{b['gis_area']:g} {md(b['gis_area_units'], 20)}" for b in boundaries if b["gis_area"] is not None]
    if areas:
        lines.append(
            f"- Source-reported GIS_AREA per total-site feature: {', '.join(areas[:10])} (published values, not calculated)"
        )
    if result.get("area") and result["area"]["flags"]:
        lines.append("- ⚠️ Area: " + "; ".join(result["area"]["flags"]))
    reuse = result.get("reuse")
    if reuse is not None:
        lines += ["", "### Reuse", ""]
        if reuse["report"].status in {"complete", "empty"}:
            if reuse["listed"]:
                summary = next((r["summary_url"] for r in reuse["records"] if r["summary_url"]), None)
                lines.append(
                    "- Listed on EPA's Superfund Sites in Reuse map (EPA reports some reuse at the site)"
                    + (f" — {link('EPA reuse summary', summary)}" if summary else "")
                )
            else:
                lines.append("- Not on EPA's Superfund Sites in Reuse map; this is not evidence that no reuse exists.")
            lines.append(
                "  - Reuse listing is not a determination that the site is suitable for any particular new use."
            )
        else:
            lines.append(f"- Reuse map not determined ({reuse['report'].status}).")
    lines += ["", "### Links", ""]
    if point:
        for key, entry in point["links"].items():
            if entry["url"]:
                lines.append(f"- {LINK_LABELS.get(key, key)}: {link(entry['text'] or 'link', entry['url'])}")
    for boundary in boundaries[:1]:
        if boundary["site_info_url"]:
            lines.append(f"- EPA site page: {link('site page', boundary['site_info_url'])}")
    lines.append("")
    lines += _sources(result["reports"])
    lines += ["---", "", NOT_A_DETERMINATION]
    return "\n".join(lines)


def _ou_line(record: dict[str, Any]) -> list[str]:
    if record["kind"] == "sems_ou":
        scope = " (sitewide grouping, not a physical area)" if record["ou_id"] == "00" else ""
        decisions = "; ".join(md(name, 60) for name in record["decisions"]) or "none recorded"
        media = ", ".join(md(name, 30) for name in record["media"]) or "not published"
        return [
            f"- **OU {record['ou_id']}** (SEMS decision records){scope} — decision documents: {decisions} — "
            f"media: {media} — no geometry in this source"
        ]
    feature_type = record["feature_type"] or "type not published"
    if (record["feature_type"] or "").casefold() == "deleted area boundary":
        feature_type = "mapped deleted-area boundary (not an active OU)"
    return [
        f"- **Map feature {record['object_id']}** — {md(record['feature_name'] or 'unnamed feature', 120)} — "
        f"{md(feature_type, 80)} — class {record['feature_class']} — site status on feature: "
        f"{_status_line(record['status'])} — OU crosswalk {md(record['crosswalk'], 140)} — geometry not returned by "
        "this tool"
        + (
            f" — {link(record['feature_info_label'] or 'feature info', record['feature_info_url'])}"
            if record["feature_info_url"]
            else ""
        )
    ]


def format_operable_units(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    lines = _header(
        "EPA Superfund Operable Units",
        result,
        [
            f"**EPA ID:** {result['epa_id']}" + (f" — {md(result['name'], 120)}" if result.get("name") else ""),
            f"**OUs in SEMS decision records:** {result['sems_ou_count']} · "
            f"**Mapped OU-layer features:** {result['map_feature_count']}",
        ],
    )
    if not result["records"]:
        lines += _no_records(
            result,
            "No OU records were returned by the queried sources. Both sources are partial; an empty result does not "
            "mean the site has no operable units.",
        )
    lines += _paged(
        result["records"],
        result_offset,
        max_results,
        _ou_line,
        "operable-unit records",
        _lower_bound(result["reports"]),
    )
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: SEMS decision records list OUs that have a recorded decision document; the OU map layer covers a small "
        "subset of sites. Neither is a complete OU inventory, and a map feature name is not a nationally unique OU "
        "number.",
    ]
    return "\n".join(lines)


def _ic_line(record: dict[str, Any]) -> list[str]:
    area = (
        f" — source GIS_AREA {record['gis_area']:g} {md(record['gis_area_units'], 20)}"
        if record["gis_area"] is not None
        else ""
    )
    return [
        f"- **Feature {record['object_id']}** — {md(record['feature_type'] or 'type not published', 80)} "
        f"(class {record['feature_class']}) — {md(record['feature_name'] or record['site_name'] or 'unnamed', 120)} — "
        f"last change {record['last_change_date']['iso'] or 'not published'}{area}"
        + (
            f" — {link(record['feature_info_label'] or 'feature info', record['feature_info_url'])}"
            if record["feature_info_url"]
            else ""
        ),
        *([f"  - Description: {md(record['feature_description'], 300)}"] if record["feature_description"] else []),
    ]


def format_institutional_controls(
    result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0
) -> str:
    lines = _header("EPA Superfund Institutional-Control Map Records", result, [f"**EPA ID:** {result['epa_id']}"])
    if not result["records"]:
        lines += _no_records(
            result,
            "No mapped control-related features for this EPA ID. The map layer is not a complete control registry; "
            "this is not evidence that no institutional controls apply.",
        )
    lines += _paged(
        result["records"],
        result_offset,
        max_results,
        _ic_line,
        "mapped control records",
        _lower_bound(result["reports"]),
    )
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: These are mapped control-related areas, not executed covenants, deed restrictions, ordinances, or "
        "groundwater-use limits, and not verification that a restriction is in force. The layer publishes no instrument "
        "identity or status. Check remedy decisions, IC plans, site records, and the applicable land-records repository.",
    ]
    return "\n".join(lines)


def _document_line(doc: dict[str, Any]) -> list[str]:
    when = doc["date"] or "date not published"
    identifier = f" — FR doc {md(doc['identifier'], 20)}" if doc["identifier"] else ""
    label = "EPA site profile" if doc["source"] == "SEMS contaminant records" else "official record"
    official = f" — {link(label, doc['url'])}" if doc["url"] else ""
    inferred = " (title-inferred)" if doc["source"].startswith("Federal Register") else ""
    return [
        f"- **{md(doc['title'] or 'Untitled', 200)}** — {when} — {doc['category'].replace('_', ' ')}{inferred} — "
        f"{md(doc['source'], 60)}{identifier}{official} — {md(doc['basis'], 120)}"
    ]


def format_documents(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    filters = ", ".join(
        f"{k}={md(v, 100)}" for k, v in (("query", result["query"]), ("document_type", result["document_type"])) if v
    )
    lines = _header(
        "EPA Superfund Documents",
        result,
        [
            f"**EPA ID:** {result['epa_id']}" + (f" — {md(result['name'], 120)}" if result.get("name") else ""),
            *([f"**Filters:** {filters}"] if filters else []),
        ],
    )
    if not result["records"]:
        lines += _no_records(result, "No document entries in the supported sources for this request.")
        if result.get("profile_url") and (result["query"] or result["document_type"]):
            lines += [
                "Five-year reviews, remedy decisions, and other site documents are listed on the "
                f"{link('EPA site profile', result['profile_url'])}, which this tool does not retrieve.",
                "",
            ]
    lines += _paged(
        result["records"], result_offset, max_results, _document_line, "documents", _lower_bound(result["reports"])
    )
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: Filters apply to titles only; this is not a full-text search. Entries are references and links; "
        "document contents were not read. Site document collections on EPA's profile pages are not retrieved "
        "because EPA's robots.txt disallows automated access.",
        "Note: A Superfund Record of Decision is a cleanup remedy decision, not a NEPA decision, and a title does "
        "not show that a remedy remains unchanged.",
    ]
    return "\n".join(lines)


def _action_line(record: dict[str, Any]) -> list[str]:
    if record["kind"] == "sems_decision":
        return [
            f"- **{md(record['label'], 100)}** (OU {record['ou_id']}) — decision recorded in SEMS; date not published"
        ]
    if record["kind"] == "federal_register_action":
        return [
            f"- **{md(record['label'], 160)}** — {record['date'] or 'date not published'} — Federal Register "
            f"{md(record['raw'], 20)} — {link('official notice', record.get('url'))}"
        ]
    when = record["date"] or f"unparsed source value '{md(record['raw'], 30)}'"
    return [f"- **{md(record['label'], 100)}** (NPL status layer milestone) — {when}"]


def format_cleanup_actions(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    lines = _header(
        "EPA Superfund Cleanup Milestones and Decisions",
        result,
        [
            f"**EPA ID:** {result['epa_id']}" + (f" — {md(result['name'], 120)}" if result.get("name") else ""),
            *([f"**Operable unit filter:** {result['operable_unit']}"] if result["operable_unit"] else []),
        ],
    )
    if not result["records"]:
        lines += _no_records(result, "No published milestones or decision records for this request.")
    lines += _paged(
        result["records"], result_offset, max_results, _action_line, "records", _lower_bound(result["reports"])
    )
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: These are NPL milestones, decision documents recorded in SEMS, and Federal Register actions that "
        "name the site. EPA's detailed cleanup schedule (remedial design and action phases, five-year review "
        "windows) is on its site-profile pages, which are not retrieved because EPA's robots.txt disallows "
        "automated access. A missing record is not evidence that an action did not occur, and a construction "
        "completion milestone is not completion of all cleanup.",
    ]
    return "\n".join(lines)


def _contaminant_line(row: dict[str, Any]) -> list[str]:
    return [
        f"- **{md(row.get('preferred_contaminant_name'), 100)}** — media {md(row.get('media_name'), 40)} — "
        f"OU {md(row.get('operable_unit_num'), 4)} — {md(row.get('action_name'), 60)} ({md(row.get('type_code'), 4)}) — "
        f"seq {row.get('seq')}"
    ]


def format_contaminants(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    site = result["site"]
    filters = ", ".join(
        f"{k}={md(v, 40)}" for k, v in (("operable_unit", result["operable_unit"]), ("media", result["media"])) if v
    )
    lines = _header(
        "EPA Superfund Contaminant Associations",
        result,
        [
            f"**EPA ID:** {result['epa_id']}"
            + (f" — SEMS site id {site['site_id']} — {md(site['name'], 120)}" if site else ""),
            *([f"**Filters:** {filters}"] if filters else []),
        ],
    )
    records = result["records"]
    if records:
        by_media: dict[str, int] = {}
        for row in records:
            by_media[str(row.get("media_name"))] = by_media.get(str(row.get("media_name")), 0) + 1
        lines += ["By media: " + ", ".join(f"{md(k, 40)}: {v}" for k, v in sorted(by_media.items())), ""]
    elif site:
        lines += _no_records(
            result,
            "No contaminant associations published for this request. This does not establish absence of contamination.",
        )
    lines += _paged(
        records,
        result_offset,
        max_results,
        _contaminant_line,
        "contaminant associations",
        _lower_bound(result["reports"]),
    )
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: Each row is a published contaminant/media/OU/decision-document-type association from the SEMS "
        "contaminants table, not a sample concentration, exposure finding, or current extent, and it may not include "
        "later decision documents. The table does not publish: "
        + ", ".join(CONTAMINANT_UNAVAILABLE_FIELDS)
        + ". The same chemical in different media or actions is separate evidence; `seq` is not a unique ID.",
    ]
    return "\n".join(lines)


def _notice_line(event: dict[str, Any]) -> list[str]:
    dates = ", ".join(
        filter(
            None,
            [
                f"published {event['published']}" if event["published"] else None,
                f"comments close {event['comments_due']} (date only; time zone not stated)"
                if event["comments_due"]
                else None,
            ],
        )
    )
    stage = f" ({event['stage']})" if event.get("stage") and event["stage"] != "not stated" else ""
    dockets = f" — docket {', '.join(md(d, 40) for d in event['dockets'])}" if event.get("dockets") else ""
    lines = [
        f"- **{md(event['title'] or 'Untitled', 200)}** — {event['kind'].replace('_', ' ')}{stage}"
        + (f" — {dates}" if dates else "")
        + (f" — {event['status']}" if event.get("status") else "")
        + f"{dockets} — {event['association']} — {link('official notice', event['url'])}"
    ]
    if event.get("action"):
        lines.append(f"  - Federal Register action: {md(event['action'], 300)}")
    if event.get("federal_register_url"):
        lines.append(
            f"  - Same-day Federal Register document: {link('federalregister.gov', event['federal_register_url'])}"
        )
    if event.get("publication_date_unknown"):
        lines.append("  - Publication date unknown; kept so the date filter does not hide it")
    if event["kind"] == "extension":
        candidates = "; ".join(md(title, 120) for title in event.get("may_revise") or [])
        lines.append(
            f"  - Possible earlier notice(s), unverified: {candidates}"
            if candidates
            else "  - The original deadline is not in the retrieved sources"
        )
    return lines


def format_public_notices(result: dict[str, Any], *, max_results: int = MAX_PAGE_SIZE, result_offset: int = 0) -> str:
    lines = _header(
        "EPA Superfund Public Notices",
        result,
        [
            f"**EPA ID:** {result['epa_id']}" + (f" — {md(result['name'], 120)}" if result.get("name") else ""),
            f"**Status evaluated as of:** {result['as_of']} (UTC date)",
            *(
                [f"**Published on or after:** {result['published_on_or_after']}"]
                if result["published_on_or_after"]
                else []
            ),
        ],
    )
    if not result["events"]:
        lines += _no_records(result, "No notices found in the supported sources.")
    lines += _paged(
        result["events"], result_offset, max_results, _notice_line, "notices", _lower_bound(result["reports"])
    )
    lines += _sources(result["reports"])
    lines += [
        "---",
        "",
        "Note: Federal Register notices are matched by site name, so each is a candidate until its text is checked. "
        "Local notices (newspapers, state agencies, EPA web announcements) are not covered. Close dates are "
        "reproduced as published and never derived from a statutory period. A proposal is not a final cleanup or "
        "deletion decision. This tool does not submit comments or create subscriptions.",
    ]
    return "\n".join(lines)
