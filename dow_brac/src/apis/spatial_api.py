"""FRS interests and opt-in historical polygons remain unresolved spatial candidates."""

from nepa_mcp_common.arcgis import ArcGISService
from src.apis.adapters import Budget
from src.core.normalization import geo, output, page
from src.core.sources import FRS, HISTORICAL

FRS_FIELDS = (
    "OBJECTID",
    "REGISTRY_ID",
    "PRIMARY_NAME",
    "STATE_CODE",
    "PGM_SYS_ACRNM",
    "PGM_SYS_ID",
    "KEY_FIELD",
    "ACTIVE_STATUS",
    "ACCURACY_VALUE",
    "COLLECT_MTH_DESC",
    "REF_POINT_DESC",
    "LATITUDE83",
    "LONGITUDE83",
    "CREATE_DATE",
    "UPDATE_DATE",
    "LAST_REPORTED_DATE",
    "FAC_URL",
    "PROGRAM_URL",
    "PGM_REPORT_URL",
)
HIST_FIELDS = ("OBJECTID", "COMPONENT", "SITE_NAME", "JOINT_BASE", "STATE_TERR", "STPOSTAL", "BRAC_SITE")


def layer(base, number, fields, geometry, where, budget=None):
    budget = budget or Budget()
    report = {
        "url": f"{base}/{number}",
        "status": "unavailable",
        "complete": False,
        "warnings": [],
        "source_feature_count": None,
    }
    records = []
    try:
        budget.check()
        ids = ArcGISService.query_object_ids(
            base, number, geometry, where=where, simplify_geometry=False, timeout=(4, 10), max_attempts=1
        )
        report["source_feature_count"] = len(ids)
        for start in range(0, min(len(ids), 2500), 250):
            budget.check()
            batch = ids[start : start + 250]
            response = ArcGISService.query_features(
                base,
                number,
                None,
                out_fields=",".join(fields),
                return_geometry=True,
                out_sr=4326,
                page_size=len(batch),
                max_features=len(batch),
                timeout=(4, 10),
                max_attempts=1,
                extra_params={"where": where, "objectIds": ",".join(map(str, batch)), "orderByFields": "OBJECTID ASC"},
            )
            report["warnings"].extend(response.warnings)
            if response.truncated:
                report["warnings"].append("Source transfer limit")
            seen = set()
            for feature in response.features:
                attrs = feature.get("attributes", {})
                if attrs.get("OBJECTID") not in batch or attrs.get("OBJECTID") in seen:
                    report["warnings"].append("Unexpected/duplicate feature")
                    continue
                seen.add(attrs["OBJECTID"])
                if not set(fields).issubset(attrs):
                    report["warnings"].append("Source schema changed: fields missing")
                records.append({"attributes": {k: attrs.get(k) for k in fields}, "geometry": feature.get("geometry")})
            if seen != set(batch):
                report["warnings"].append("Selected IDs missing from source response")
        budget.check()
        after = ArcGISService.query_object_ids(
            base, number, geometry, where=where, simplify_geometry=False, timeout=(4, 10), max_attempts=1
        )
        if after != ids:
            report["warnings"].append("Source ID set changed during retrieval")
        if len(ids) > 2500:
            report["warnings"].append("2500 feature safety cap")
        report.update(status="partial" if report["warnings"] else "ok", complete=not report["warnings"])
    except Exception:
        report.update(
            status="partial" if records else "unavailable",
            warnings=report["warnings"] + ["Official GIS source failed; this is not a no-match finding"],
        )
    return records, report


def get_brac_installations_in_roi(
    latitude, longitude, buffer_miles=25.0, include_historical_boundaries=False, max_results=100, result_offset=0
):
    geo(latitude, longitude, buffer_miles)
    page(max_results, result_offset)
    if type(include_historical_boundaries) is not bool:
        raise ValueError("include_historical_boundaries must be boolean")
    budget = Budget()
    try:
        roi = ArcGISService.create_roi_buffer(latitude, longitude, buffer_miles)
    except Exception:
        return output([], [], ["Geodesic ROI construction unavailable"], max_results, result_offset)
    features, report = layer(FRS, 5, FRS_FIELDS, roi, "PGM_SYS_ACRNM = 'BRAC'", budget)
    records = []
    reports = [report]
    for f in features:
        a = f["attributes"]
        g = f.get("geometry") or {}
        records.append(
            {
                "candidate_id": f"frs-object:{a['OBJECTID']}",
                "installation_id": None,
                "identity_resolution": "Unresolved EPA BRAC-interest candidate; no installation join by name/proximity",
                "frs_registry_id": a["REGISTRY_ID"],
                "program_identity": {"acronym": a["PGM_SYS_ACRNM"], "program_id": a["PGM_SYS_ID"]},
                "raw": a,
                "match_basis": "reference_point",
                "coordinates": {
                    "longitude": g.get("x"),
                    "latitude": g.get("y"),
                    "spatial_reference": g.get("spatialReference"),
                    "transformation": "ArcGIS outSR=4326 requested from published geometry; NAD83 attribute values preserved separately",
                },
                "activity_meaning": "ACTIVE_STATUS describes program interest, not military operations",
                "geometry_reference": {"layer": f"{FRS}/5", "object_id": a["OBJECTID"]},
            }
        )
    if include_historical_boundaries:
        features, report = layer(HISTORICAL, 0, HIST_FIELDS, roi, "UPPER(BRAC_SITE) = 'YES'", budget)
        reports.append(report)
        for f in features:
            a = f["attributes"]
            records.append(
                {
                    "candidate_id": f"historical-object:{a['OBJECTID']}",
                    "installation_id": None,
                    "identity_resolution": "Unresolved historical spatial candidate; source flag is not a corroborated current DoW action",
                    "raw": a,
                    "match_basis": "historical_polygon_intersection",
                    "source_vintage": "2010 Base Structure Report; NTAD2014 service context",
                    "geometry_reference": {"layer": f"{HISTORICAL}/0", "object_id": a["OBJECTID"]},
                }
            )
    records.sort(key=lambda r: r["candidate_id"])
    return output(
        records,
        reports,
        [
            "No verified current military-department geometry adapter; spatial completeness is limited to the selected source inventories."
        ],
        max_results,
        result_offset,
        geometry_coverage="FRS reference points"
        + ("; opt-in historical polygons" if include_historical_boundaries else ""),
        national_coverage_complete=False,
    )
