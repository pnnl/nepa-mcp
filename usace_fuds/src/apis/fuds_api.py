"""Bounded, independently reported FUDS inventories; no name/proximity joins."""

import time

from nepa_mcp_common.arcgis import ArcGISService
from src.core.constants import BASE, BATCH, CAP, FIELDS, LABELS, NOTE, PROGRAM_URL
from src.core.normalization import (
    coded_values,
    epoch_date,
    fingerprint,
    geo,
    identifier,
    now,
    official_link,
    page_args,
    yes_no,
)


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + 50
        self.requests = 0

    def check(self):
        self.requests += 1
        if self.requests > 24 or time.monotonic() >= self.deadline:
            raise RuntimeError("FUDS query budget exhausted")


def query(layer, *, where="1=1", geometry=None, geometry_type="esriGeometryPolygon", budget=None):
    budget = budget or Budget()
    report = {
        "layer": layer,
        "url": f"{BASE}/{layer}",
        "name": LABELS[layer],
        "retrieved_at": now(),
        "status": "unavailable",
        "total": None,
        "total_scope": "selected source feature IDs",
        "complete": False,
        "warnings": [],
    }
    features = []
    try:

        def ids():
            budget.check()
            return ArcGISService.query_object_ids(
                BASE,
                layer,
                geometry,
                where=where,
                geometry_type=geometry_type,
                simplify_geometry=False,
                timeout=(4, 8),
                max_attempts=1,
            )

        selected = ids()
        report["total"] = len(selected)
        limited = selected[:CAP]
        if len(selected) > CAP:
            report["warnings"].append(f"{CAP}-feature safety cap reached")
        seen = set()
        for start in range(0, len(limited), BATCH):
            budget.check()
            batch = limited[start : start + BATCH]
            result = ArcGISService.query_features(
                BASE,
                layer,
                None,
                out_fields=",".join(FIELDS[layer]),
                return_geometry=layer in {1, 3, 4},
                out_sr=4326,
                page_size=len(batch),
                max_features=len(batch),
                timeout=(4, 8),
                max_attempts=1,
                extra_params={"where": where, "objectIds": ",".join(map(str, batch)), "orderByFields": "OBJECTID ASC"},
            )
            report["warnings"].extend(result.warnings)
            if result.truncated:
                report["warnings"].append("Source batch transfer limit")
            for f in result.features:
                attrs = f.get("attributes", {}) if isinstance(f, dict) else {}
                oid = attrs.get("OBJECTID")
                if oid not in batch or oid in seen:
                    report["warnings"].append("Malformed, duplicate, or unexpected source feature")
                    continue
                seen.add(oid)
                # Strip unwanted attributes even if an upstream ignores outFields.
                f = {"attributes": {k: attrs.get(k) for k in FIELDS[layer]}, "geometry": f.get("geometry")}
                if not set(FIELDS[layer]).issubset(attrs):
                    report["warnings"].append("Source field/schema change: expected fields missing")
                features.append(f)
            if not set(batch).issubset(seen):
                report["warnings"].append("Selected source IDs missing from feature batch")
        if ids() != selected:
            report["warnings"].append("Source IDs changed during retrieval; restart pagination")
        report["complete"] = len(selected) <= CAP and not report["warnings"]
        report["status"] = "ok" if report["complete"] else "partial"
    except Exception as exc:
        report["warnings"].append(f"Source retrieval failed ({type(exc).__name__}); unavailable is not empty")
        report["status"] = "partial" if features else "unavailable"
    report["returned_count"] = len(features)
    report["warnings"] = list(dict.fromkeys(report["warnings"]))
    return features, report


def result(records, reports, warnings=None, max_results=100, result_offset=0, **extra):
    page_args(max_results, result_offset)
    warnings = list(warnings or [])
    source_retrieval_complete = bool(reports) and all(r["complete"] for r in reports)
    identity_complete = not any("lacks a valid public property number" in warning for warning in warnings)
    complete = source_retrieval_complete and identity_complete
    paged = records[result_offset : result_offset + max_results]
    more = result_offset + len(paged) < len(records)
    status = (
        "unavailable"
        if reports and all(r["status"] == "unavailable" for r in reports)
        else "partial"
        if not complete or warnings
        else "ok"
        if records
        else "empty"
    )
    return {
        "status": status,
        "records": paged,
        "retrieved_at": now(),
        "sources": reports,
        "source_retrieval_complete": source_retrieval_complete,
        "identity_normalization_complete": identity_complete,
        "warnings": warnings,
        "coverage_note": NOTE,
        "program_url": PROGRAM_URL,
        "result_fingerprint": fingerprint(
            {"records": records, "sources": [(r["layer"], r["status"], r["total"]) for r in reports]}
        ),
        "pagination": {
            "max_results": max_results,
            "result_offset": result_offset,
            "returned_count": len(paged),
            "has_more": more if complete else True if more else None,
            "next_result_offset": result_offset + len(paged) if more else None,
            "total": len(records),
            "total_kind": "exact" if complete else "lower_bound",
            "retrieval_complete": complete,
        },
        **extra,
    }


def property_records(groups):
    records = {}
    warnings = []
    for layer, features in groups:
        for f in features:
            a = f["attributes"]
            raw = a.get("FUDSUNIQUEPROPERTYNUMBER")
            try:
                number = identifier(raw)
            except ValueError:
                warnings.append(f"Layer {layer} feature {a.get('OBJECTID')} lacks a valid public property number")
                continue
            pk = a.get("DODFUDSPROPERTYIDPK")
            if pk and pk != number:
                warnings.append(f"Conflicting property relationship key for {number}")
            r = records.setdefault(
                number,
                {
                    "property_number": number,
                    "match_basis": [],
                    "source_records": [],
                    "conflicts": {},
                    "boundary_available": False,
                },
            )
            basis = "point" if layer == 1 else "polygon"
            if basis not in r["match_basis"]:
                r["match_basis"].append(basis)
            r["boundary_available"] |= layer == 4
            r["source_records"].append(
                {
                    "source_url": f"{BASE}/{layer}",
                    "source_object_id": a.get("OBJECTID"),
                    "raw": a,
                    "coded_values": coded_values(a, layer),
                    "geometry_reference": {
                        "layer_url": f"{BASE}/{layer}",
                        "object_id": a.get("OBJECTID"),
                        "spatial_reference": 4326,
                        "geometry_available": bool(f.get("geometry")),
                    },
                    "has_projects": yes_no(a.get("HAS_PROJECTS" if layer == 1 else "HASPROJECTS")),
                    "official_link": official_link(a.get("EMSMGMTACTIONPLANLINK")),
                }
            )
    for r in records.values():
        for field in (
            "FEATURENAME",
            "FUDSINSTALLATIONID",
            "DODFUDSPROPERTYIDPK",
            "ELIGIBILITY",
            "USACEDISTRICT",
            "FISCALYEAR",
            "STATUS",
            "STATUSCODE",
        ):
            vals = list(
                dict.fromkeys(str(x["raw"][field]) for x in r["source_records"] if x["raw"].get(field) is not None)
            )
            if len(vals) > 1:
                r["conflicts"][field] = vals
        if r["conflicts"]:
            warnings.append(f"Conflicting source values for {r['property_number']}; preserved separately")
        r["source_records"].sort(key=lambda x: (x["source_url"], str(x["source_object_id"])))
    return sorted(records.values(), key=lambda r: r["property_number"]), warnings


def _properties(geometry=None, where="1=1", budget=None):
    budget = budget or Budget()
    groups = []
    reports = []
    for layer in (1, 4):
        rows, report = query(layer, where=where, geometry=geometry, budget=budget)
        groups.append((layer, rows))
        reports.append(report)
    records, warnings = property_records(groups)
    return records, reports, warnings


def get_usace_fuds_properties_in_roi(latitude, longitude, buffer_miles=25.0, max_results=100, result_offset=0):
    """Find point and polygon FUDS property matches; combine public identities before paging."""
    geo(latitude, longitude, buffer_miles)
    page_args(max_results, result_offset)
    try:
        roi = ArcGISService.create_roi_buffer(latitude, longitude, buffer_miles)
    except Exception:
        return result([], [], ["ROI construction unavailable"], max_results, result_offset)
    records, reports, warnings = _properties(roi)
    return result(
        records,
        reports,
        warnings,
        max_results,
        result_offset,
        roi={"latitude": latitude, "longitude": longitude, "buffer_miles": buffer_miles},
        spatial_coverage="Published points and mapped property polygons; no geometry simplification",
    )


def get_usace_fuds_property(property_number):
    """Look up a public FUDS number in both property inventories, preserving conflicting records."""
    number = identifier(property_number)
    records, reports, warnings = _properties(where=f"FUDSUNIQUEPROPERTYNUMBER = '{number}'")
    return result(records, reports, warnings, property_number=number)


def get_usace_fuds_projects(property_number, max_results=100, result_offset=0):
    """List projects using public property/foreign keys, with source dates and cost context."""
    number = identifier(property_number)
    page_args(max_results, result_offset)
    features, report = query(2, where=f"FUDSPROPERTYID = '{number}' OR DODFUDSPROPERTYIDFK = '{number}'")
    records = []
    warnings = []
    for f in features:
        a = f["attributes"]
        keys = {a.get("FUDSPROPERTYID"), a.get("DODFUDSPROPERTYIDFK")} - {None, ""}
        if keys != {number}:
            warnings.append(f"Unresolved/conflicting project crosswalk at source feature {a.get('OBJECTID')}")
        records.append(
            {
                "property_number": number,
                "relationship_verified": keys == {number},
                "project_identity": {
                    "property_number": number,
                    "site_id": a.get("FUDSSITEID"),
                    "project_number": a.get("PROJECTNUMBER"),
                    "source_object_id": a.get("OBJECTID"),
                },
                "raw": a,
                "coded_values": coded_values(a, 2),
                "milestones": {
                    k: epoch_date(a.get(k)) for k in ("REMEDYINPLACEDATE", "RESPONSECOMPLETEDATE", "SITECLOSEOUTDATE")
                },
                "cost_estimate": {
                    "raw": a.get("COSTTOCOMPLETE"),
                    "units": "not published in layer metadata",
                    "vintage": "FUDS FY24 source group; estimate-specific vintage unknown",
                    "funding_commitment": False,
                },
                "source_url": f"{BASE}/2",
                "official_link": official_link(a.get("EMSMGMTACTIONPLANLINK")),
            }
        )
    records.sort(
        key=lambda x: (
            str(x["project_identity"]["site_id"]),
            str(x["project_identity"]["project_number"]),
            str(x["project_identity"]["source_object_id"]),
        )
    )
    return result(
        records,
        [report],
        warnings,
        max_results,
        result_offset,
        property_number=number,
        source_group="FUDS FY24; project-level fiscal year not published",
    )


def get_usace_fuds_munitions_response_sites_in_roi(
    latitude, longitude, buffer_miles=25.0, max_results=100, result_offset=0
):
    """Find mapped munitions response areas, retaining published site/project identity and priority."""
    geo(latitude, longitude, buffer_miles)
    page_args(max_results, result_offset)
    try:
        roi = ArcGISService.create_roi_buffer(latitude, longitude, buffer_miles)
    except Exception:
        return result([], [], ["ROI construction unavailable"], max_results, result_offset)
    features, report = query(3, geometry=roi)
    records = []
    warnings = []
    for f in features:
        a = f["attributes"]
        try:
            number = identifier(a.get("FUDSPROPERTYID"))
        except ValueError:
            number = None
            warnings.append(f"Missing or invalid property identity in MRS {a.get('OBJECTID')}")
        records.append(
            {
                "property_number": number,
                "site_id": a.get("FUDSSITEID"),
                "project_number": a.get("PROJECTNUMBER"),
                "source_object_id": a.get("OBJECTID"),
                "match_basis": "mapped_response_area_polygon",
                "raw": a,
                "coded_values": coded_values(a, 3),
                "geometry_reference": {"layer_url": f"{BASE}/3", "object_id": a.get("OBJECTID")},
                "interpretation": "Published response area; not a precise individual hazard location. Priority is source reported, not a redevelopment score.",
            }
        )
    records.sort(
        key=lambda r: (
            str(r["property_number"]),
            str(r["site_id"]),
            str(r["project_number"]),
            str(r["source_object_id"]),
        )
    )
    return result(records, [report], warnings, max_results, result_offset)


def get_usace_fuds_program_district(property_number=None, latitude=None, longitude=None):
    """Resolve recorded FUDS assignment or intersect FUDS program districts at a coordinate."""
    property_mode = property_number is not None
    if (
        property_mode
        and (latitude is not None or longitude is not None)
        or not property_mode
        and (latitude is None or longitude is None)
    ):
        raise ValueError("Provide exactly one lookup mode: property_number or a complete latitude/longitude pair")
    reports = []
    warnings = []
    recorded = []
    geographic = []
    budget = Budget()
    if property_mode:
        number = identifier(property_number)
        props, reports, warnings = _properties(where=f"FUDSUNIQUEPROPERTYNUMBER = '{number}'", budget=budget)
        for prop in props:
            recorded.extend(
                str(x["raw"]["USACEDISTRICT"]).upper() for x in prop["source_records"] if x["raw"].get("USACEDISTRICT")
            )
        recorded = sorted(set(recorded))
        valid = [x for x in recorded if len(x) == 3 and x.isalpha() and x != "TBD"]
        if not valid:
            return result(
                [],
                reports,
                warnings + ["No resolvable recorded FUDS district assignment"],
                resolution_basis="recorded_property_assignment",
                recorded_districts=recorded,
            )
        clauses = ",".join(f"'{x}'" for x in valid)
        rows, report = query(9, where=f"DIST IN ({clauses})", budget=budget)
    else:
        geo(latitude, longitude)
        rows, report = query(
            9,
            geometry={"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}},
            geometry_type="esriGeometryPoint",
            budget=budget,
        )
        geographic = sorted({f["attributes"].get("DIST") for f in rows if f["attributes"].get("DIST")})
    reports.append(report)
    geographic_offices = []
    if property_mode:
        coordinates = set()
        for prop in props:
            for source_record in prop["source_records"]:
                raw = source_record["raw"]
                try:
                    lat, lon, _ = geo(raw.get("LATITUDE"), raw.get("LONGITUDE"))
                    coordinates.add((lat, lon))
                except ValueError:
                    continue
        if len(coordinates) > 2:
            warnings.append("Conflicting property coordinates exceed geographic office comparison budget")
        for lat, lon in sorted(coordinates)[:2]:
            candidates, geographic_report = query(
                9,
                geometry={"x": lon, "y": lat, "spatialReference": {"wkid": 4326}},
                geometry_type="esriGeometryPoint",
                budget=budget,
            )
            reports.append(geographic_report)
            geographic_offices.extend(f["attributes"] for f in candidates)
        geographic = sorted({a["DIST"] for a in geographic_offices if a.get("DIST")})
        if geographic and set(geographic) != set(recorded):
            warnings.append(
                "Recorded FUDS assignment disagrees with geographic program district candidates; neither replaced the other"
            )
    offices = []
    for f in rows:
        a = f["attributes"]
        offices.append(
            {
                "district_code": a.get("DIST"),
                "district_name": a.get("MIL_DIST"),
                "office": a.get("OFFICE"),
                "source_url": f"{BASE}/9",
                "official_url": official_link(a.get("WEB")),
                "raw": a,
            }
        )
    if property_mode and set(recorded) - {x["district_code"] for x in offices}:
        warnings.append("Some recorded assignments could not be resolved to published FUDS offices")
    return result(
        offices,
        reports,
        warnings,
        resolution_basis="recorded_property_assignment" if property_mode else "FUDS_program_boundary_intersection",
        recorded_districts=recorded,
        geographic_districts=geographic,
        geographic_office_records=geographic_offices,
    )
