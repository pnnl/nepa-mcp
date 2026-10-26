"""
Unit tests for the EPA Superfund server's normalization, adapters, and tool logic.

Fixtures are trimmed copies of live EPA responses captured on 2026-10-21 (Bog
Creek Farm NJD063157150 / SEMS 0200397, Hopewell Precision NYD066813064 /
0201588, Central City-Clear Creek COD980717557). The network boundaries
(``ArcGISService.query_object_ids``, ``query_features``, ``get_json_rows``, and ``get_json``) are
replaced by an in-memory fake, so no network calls are made.
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_superfund"
ROI = {
    "rings": [[[-74.3, 40.0], [-74.0, 40.0], [-74.0, 40.3], [-74.3, 40.3], [-74.3, 40.0]]],
    "spatialReference": {"wkid": 4326},
}

L1_BOG = {
    "attributes": {
        "ObjectId2": 651,
        "Site_Name": "Bog Creek Farm",
        "Site_EPA_ID": "NJD063157150",
        "SEMS_ID": 200397,
        "Region_ID": 2,
        "State": "New Jersey",
        "City": "Howell Township",
        "County": "Monmouth",
        "Status": "NPL Site",
        "Latitude": 40.150831,
        "Longitude": -74.161111,
        "Proposed_Date": "12/30/1982",
        "Listing_Date": "09/08/1983",
        "Construction_Completion_Date": "06/30/1994",
        "Construction_Completion_Number": 241,
        "NOID_Date": None,
        "Deletion_Date": None,
        "Site_Listing_Narrative": '<a href="https://semspub.epa.gov/src/document/02/363615" target="_blank">NJD063157150 (PDF)</a>',
        "Site_Progress_Profile": '<a href="https://cumulis.epa.gov/supercpad/cursites/csitinfo.cfm?id=0200397" target="_blank">Bog Creek Farm</a>',
        "Proposed_FR_Notice": '<a href="https://semspub.epa.gov/src/document/11/189619" target="_blank">12/30/1982 (PDF)</a>',
        "Final_FR_Notice": '<a href="https://semspub.epa.gov/src/document/11/189620" target="_blank">09/08/1983 (PDF)</a>',
        "Site_has_had_a_Partial_Deletion": "No",
    },
    "geometry": {"x": -74.161111, "y": 40.150831},
}
PARTIAL_DELETION_HTML = (
    '<a href="https://www.epa.gov/superfund/partially-deleted-national-priorities-list-npl-sites-site-name" '
    'target="_blank">Yes</a>'
)
L1_ALABAMA = {
    "attributes": {
        "ObjectId2": 5,
        "Site_Name": "T.H. Agriculture & Nutrition Co. (Montgomery Plant)",
        "Site_EPA_ID": "ALD007454085",
        "SEMS_ID": 404285,
        "Region_ID": 4,
        "State": "Alabama",
        "Status": "Deleted NPL Site",
        "Site_has_had_a_Partial_Deletion": PARTIAL_DELETION_HTML,
    },
    "geometry": {"x": -86.29, "y": 32.37},
}


def _boundary(object_id, epa_id, name, status, feature_type="Comprehensive Site Area", ring=None, **extra):
    attributes = {
        "OBJECTID": object_id,
        "EPA_ID": epa_id,
        "SITE_NAME": name,
        "REGION_CODE": 2,
        "EPA_PROGRAM": "Superfund Remedial",
        "SITE_FEATURE_CLASS": 5,
        "SITE_FEATURE_TYPE": feature_type,
        "SITE_FEATURE_NAME": "Site Boundary",
        "NPL_STATUS_CODE": status,
        "FEDERAL_FACILITY_DETER_CODE": "N",
        "LAST_CHANGE_DATE": 1629676800000,
        "STATE_CODE": "NJ",
        "URL_ALIAS_TXT": "www.epa.gov/superfund/bog-creek-farm",
        "GIS_AREA": 7.67,
        "GIS_AREA_UNITS": "Acres",
        **extra,
    }
    return {"attributes": attributes, "geometry": {"rings": [ring]} if ring else None}


BOG_RING = [[-74.1614, 40.1505], [-74.1586, 40.1505], [-74.1586, 40.1523], [-74.1614, 40.1523], [-74.1614, 40.1505]]
L2_BOG = _boundary(137, "NJD063157150", "BOG CREEK FARM", "F", ring=BOG_RING)
L3_COD = {
    "attributes": {
        "OBJECTID": 144,
        "EPA_ID": "COD980717557",
        "SITE_NAME": "CENTRAL CITY, CLEAR CREEK",
        "SITE_FEATURE_CLASS": 4,
        "SITE_FEATURE_TYPE": "Operable Unit Boundary",
        "SITE_FEATURE_NAME": "OU 4: Alva Adams Waste Rock Pile Cover",
        "NPL_STATUS_CODE": "F",
        "LAST_CHANGE_DATE": 1588032000000,
        "GIS_AREA": 0.4115861,
        "GIS_AREA_UNITS": "Acres",
    }
}
L3_DELETED = {
    "attributes": {
        "OBJECTID": 200,
        "EPA_ID": "COD980717557",
        "SITE_NAME": "CENTRAL CITY, CLEAR CREEK",
        "SITE_FEATURE_CLASS": 4,
        "SITE_FEATURE_TYPE": "Deleted Area Boundary",
        "SITE_FEATURE_NAME": "OU 7: Deleted portion",
        "NPL_STATUS_CODE": "F",
    }
}
L4_COD = {
    "attributes": {
        "OBJECTID": 134,
        "EPA_ID": "COD980717557",
        "SITE_NAME": "CENTRAL CITY, CLEAR CREEK",
        "SITE_FEATURE_CLASS": 3,
        "SITE_FEATURE_TYPE": "Institutional Control Boundary ",
        "NPL_STATUS_CODE": "F",
        "LAST_CHANGE_DATE": None,
        "SITE_FEATURE_DESCRIPTION": "OU4 - Environmental Covenant. CCC OU4 WRK - Iroquois Dam (HMCOV00061)",
        "GIS_AREA": 0.01198081,
        "GIS_AREA_UNITS": "Acres",
    }
}
L5_BOG = {
    "attributes": {
        "OBJECTID": 13477,
        "REGISTRY_ID": "110060469979",
        "PRIMARY_NAME": "BOG CREEK FARM",
        "STATE_CODE": "NJ",
        "LATITUDE83": 40.150831,
        "LONGITUDE83": -74.161110999999991,
        "PGM_SYS_ID": "NJD063157150",
        "PGM_SYS_ACRNM": "SEMS",
        "INTEREST_TYPE": "SUPERFUND NPL",
        "ACTIVE_STATUS": "CURRENTLY ON THE FINAL NPL",
        "UPDATE_DATE": 1637761731000,
    },
    "geometry": {"x": -74.161111, "y": 40.150831},
}
DMAP_BOG = {
    "archived_date": None,
    "archived_ind": "N",
    "city_name": "HOWELL TOWNSHIP",
    "county_name": "MONMOUTH",
    "epa_id": "NJD063157150",
    "federal_facility_ind": "N",
    "fk_ref_region_code": "02",
    "fk_ref_state_code": "NJ",
    "name": "BOG CREEK FARM",
    "non_npl_status_code": None,
    "non_npl_status_date": None,
    "non_npl_status_name": None,
    "npl_status_code": "F",
    "npl_status_name": "Currently on the Final NPL",
    "primary_latitude_decimal_val": "40.150831",
    "primary_longitude_decimal_val": "-74.161111",
    "saa_agreement_site_ind": "N",
    "site_id": "0200397",
}
CONTAMINANTS = [
    {
        "action_name": "Record of Decision",
        "fk_site_id": "0200397",
        "media_name": "Soil",
        "operable_unit_num": "01",
        "preferred_contaminant_name": "CHROMIUM",
        "seq": 1,
        "type_code": "RO",
    },
    {
        "action_name": "Record of Decision",
        "fk_site_id": "0200397",
        "media_name": "Sediment",
        "operable_unit_num": "01",
        "preferred_contaminant_name": "CHROMIUM",
        "seq": 1,
        "type_code": "RO",
    },
    {
        "action_name": "Explanation of Significant Differences",
        "fk_site_id": "0200397",
        "media_name": "Soil",
        "operable_unit_num": "02",
        "preferred_contaminant_name": "LEAD",
        "seq": 3,
        "type_code": "EH",
    },
]
FR_DOCS = {
    "count": 60,
    "results": [
        {
            "document_number": "97-28534",
            "title": "National Oil and Hazardous Substances Contingency Plan; National Priorities List Update",
            "action": "Notice of deletion of the Bog Creek Farm Superfund Site from the National Priorities List (NPL).",
            "type": "Rule",
            "abstract": None,
            "publication_date": "1997-10-29",
            "comments_close_on": None,
            "docket_ids": ["FRL-5914-3"],
            "html_url": "https://www.federalregister.gov/documents/1997/10/29/97-28534/npl-update",
        },
        {
            "document_number": "97-23901",
            "title": "National Priorities List; Extension of Comment Period for Bog Creek Farm",
            "action": "Notice of intent to delete; extension of comment period.",
            "type": "Proposed Rule",
            "abstract": None,
            "publication_date": "1997-09-10",
            "comments_close_on": "2099-10-10",
            "docket_ids": ["FRL-5886-1"],
            "html_url": "https://www.federalregister.gov/documents/1997/09/10/97-23901/npl",
        },
        {
            "document_number": "96-15220",
            "title": "National Priorities List for Uncontrolled Hazardous Waste Sites",
            "action": "Final rule.",
            "type": "Rule",
            "abstract": None,
            "publication_date": "1996-06-17",
            "comments_close_on": None,
            "docket_ids": ["FRL-5520-2"],
            "html_url": "javascript:alert(1)",
        },
    ],
}


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_superfund_unit_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location(
        "_epa_superfund_unit_api", SERVER_DIR / "src" / "apis" / "superfund_api.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_superfund_unit_api"] = module
    spec.loader.exec_module(module)
    return module


class Upstream:
    """In-memory sources: ArcGIS features by layer, DMAP rows by URL fragment, and Federal Register results."""

    LAYERS = {
        "Superfund_National_Priorities": "npl",
        "Site_Boundaries": "l2",
        "Operable_Unit": "l3",
        "Institutional_Control": "l4",
        "FRS_INTERESTS_SEMS": "l5",
        "Superfund_Sites_In_Reuse": "reuse",
    }

    def __init__(self, monkeypatch, api, *, layers=None, dmap=None, federal_register=None):
        self.layers = {key: [] for key in ("npl", "l2", "l3", "l4", "l5", "reuse")} | (layers or {})
        self.dmap = dmap or {}
        self.federal_register = federal_register if federal_register is not None else {"count": 0, "results": []}
        self.calls: list[tuple[str, str]] = []
        self.adapters = sys.modules["src.apis.adapters"]
        ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: ROI)
        ArcGISService.query_features = staticmethod(self.query_features)
        monkeypatch.setattr(ArcGISService, "query_object_ids", self.query_object_ids)
        monkeypatch.setattr(self.adapters, "get_json_rows", self.get_json_rows)
        monkeypatch.setattr(self.adapters, "get_json", self.get_json)
        self.api = api

    def query_object_ids(self, service_url, layer_id, geometry, **kwargs):
        features = ArcGISService.query_features(
            service_url, layer_id, geometry, extra_params={"where": kwargs["where"]}
        ).features
        oid_field = (
            "ObjectId2" if "Superfund_National" in service_url else "FID" if "Reuse" in service_url else "OBJECTID"
        )
        return sorted({f["attributes"][oid_field] for f in features})

    def query_features(self, service_url, layer_id, geometry, **kwargs):
        key = next(value for fragment, value in self.LAYERS.items() if fragment in service_url)
        where = kwargs["extra_params"]["where"]
        self.calls.append((key, where))
        features = self.layers[key]
        if isinstance(features, Exception):
            raise features
        sems = re.search(r"Site_ID = (\d+)", where)
        if sems:
            features = [f for f in features if f["attributes"].get("Site_ID") == int(sems.group(1))]
        literal = re.search(r"(?:EPA_ID|PGM_SYS_ID) = '([^']+)'", where)
        if literal:
            id_field = {"npl": "Site_EPA_ID", "l5": "PGM_SYS_ID"}.get(key, "EPA_ID")
            features = [f for f in features if f["attributes"].get(id_field) == literal.group(1)]
        selected = kwargs["extra_params"].get("objectIds")
        if selected is not None:
            oid_field = {"npl": "ObjectId2", "reuse": "FID"}.get(key, "OBJECTID")
            features = [f for f in features if str(f["attributes"][oid_field]) in selected.split(",")]
        return ArcGISFeatureQueryResult(features=copy.deepcopy(features), warnings=[], truncated=False)

    def get_json_rows(self, url, **_kwargs):
        self.calls.append(("dmap", url))
        for fragment, rows in self.dmap.items():
            if fragment in url:
                if isinstance(rows, Exception):
                    raise rows
                return copy.deepcopy(rows)
        return []

    def get_json(self, url, *, params=None, **_kwargs):
        self.calls.append(("federal_register", params["conditions[term]"]))
        if isinstance(self.federal_register, Exception):
            raise self.federal_register
        return copy.deepcopy(self.federal_register)


@pytest.fixture
def api():
    return _load_api()


def _norm():
    return sys.modules["src.core.normalization"]


# ---------------------------------------------------------------------------
# Identifiers, statuses, dates, and sanitizing
# ---------------------------------------------------------------------------


def test_identifier_validation_preserves_leading_zeros(api):
    norm = _norm()
    assert norm.validate_epa_id(" njd063157150 ") == "NJD063157150"
    assert norm.validate_sems_id("200397") == "0200397"
    assert norm.validate_sems_id("0200397") == "0200397"
    assert norm.validate_operable_unit("1") == "01"
    assert norm.validate_frs_registry_id("110060469979") == "110060469979"
    for bad in ("NJD0631571", "NJD063157150' OR 1=1--", "12D063157150", ""):
        with pytest.raises(ValueError, match="epa_id"):
            norm.validate_epa_id(bad)
    with pytest.raises(ValueError, match="sems_id"):
        norm.validate_sems_id("02003970")


def test_listing_status_keeps_raw_values_for_every_source(api):
    norm = _norm()
    point = norm.normalize_npl_status("Deleted NPL Site", "npl_points")
    coded = norm.normalize_npl_status("A", "site_boundaries", "2024-01-01")
    frs = norm.normalize_npl_status("SITE IS PART OF NPL SITE", "frs_sems")
    unknown = norm.normalize_npl_status("Z", "site_boundaries")
    missing = norm.normalize_npl_status(None, "ou_boundaries")
    assert (point.normalized, point.raw) == ("deleted", "Deleted NPL Site")
    assert (coded.normalized, coded.label, coded.source_date) == (
        "part_of_npl_site",
        "Site is Part of NPL Site",
        "2024-01-01",
    )
    assert frs.normalized == "part_of_npl_site"
    assert (unknown.normalized, unknown.raw) == ("unknown", "Z")
    assert (missing.normalized, missing.raw) == ("unknown", None)
    assert norm.status_conflict([point, coded]) is True
    assert norm.status_conflict([point, missing]) is False
    assert norm.raw_status_values("not_on_npl", "npl_points") == []


def test_partial_deletion_html_and_link_validation(api):
    norm = _norm()
    yes = norm.parse_partial_deletion(PARTIAL_DELETION_HTML)
    assert yes["value"] == "yes" and yes["url"].startswith("https://www.epa.gov/superfund/")
    assert norm.parse_partial_deletion("No")["value"] == "no"
    garbage = norm.parse_partial_deletion('<a href="javascript:alert(1)">maybe</a>')
    assert garbage == {"value": "unknown", "raw": "maybe", "url": None}
    assert norm.epa_url("http://www.epa.gov/x") is None
    assert norm.epa_url("https://evil.example/epa.gov") is None
    assert norm.epa_url("https://www.epa.gov.evil.com/") is None
    assert norm.epa_url("www.epa.gov/superfund/bog-creek-farm") == "https://www.epa.gov/superfund/bog-creek-farm"


def test_markdown_rendering_neutralizes_source_markup(api):
    rendered = _norm().md("<script>x</script>[click](https://evil.example) **bold** | pipe", 200)
    assert "<script>" not in rendered and "](" not in rendered.replace("\\](", "")
    assert "\\[click\\]" in rendered and "\\*\\*bold\\*\\*" in rendered and "\\|" in rendered


# ---------------------------------------------------------------------------
# Search and ROI discovery
# ---------------------------------------------------------------------------


def test_search_merges_sources_and_reports_undetermined_status(api, monkeypatch):
    anniston = _boundary(940, "ALD000400123", "ANNISTON PCB SITE", "N", STATE_CODE="AL")
    no_status = _boundary(941, "NJD000000001", "BOG PLACE", None)
    Upstream(monkeypatch, api, layers={"npl": [L1_BOG], "l2": [L2_BOG, anniston, no_status]})
    result = api.search_epa_superfund_sites(query="bog")
    sites = {site["epa_id"]: site for site in result["sites"]}
    assert sites["NJD063157150"]["resolution"] == "npl_status_point"
    assert {s.source for s in sites["NJD063157150"]["statuses"]} == {"npl_points", "site_boundaries"}
    assert sites["ALD000400123"]["resolution"] == "boundary_only"

    filtered = api.search_epa_superfund_sites(query="bog", npl_status="not_on_npl")
    reports = {report.key: report for report in filtered["reports"]}
    assert reports["npl_points"].status == "unsupported"
    assert "site_boundaries_unknown_status" in reports
    with pytest.raises(ValueError, match="provide a query"):
        api.search_epa_superfund_sites()


def test_sems_candidate_scope_keeps_frs_and_sems_rows_distinct(api, monkeypatch):
    frs_only = copy.deepcopy(L5_BOG)
    frs_only["attributes"].update(
        OBJECTID=999, REGISTRY_ID="110000000001", PGM_SYS_ID="NJN000000002", PRIMARY_NAME="BOG ROAD DUMP"
    )
    no_coordinates = {
        **DMAP_BOG,
        "site_id": "0209999",
        "epa_id": "NJN000000003",
        "name": "BOG LANE",
        "npl_status_code": "N",
        "primary_latitude_decimal_val": None,
    }
    upstream = Upstream(
        monkeypatch,
        api,
        layers={"npl": [L1_BOG], "l5": [L5_BOG, frs_only]},
        dmap={"sems.envirofacts_site": [DMAP_BOG, no_coordinates]},
    )
    result = api.search_epa_superfund_sites(query="bog creek's", inventory_scope="sems_candidates")
    sites = {site["epa_id"]: site for site in result["sites"]}
    assert sites["NJN000000002"]["resolution"] == "frs_candidate_only"
    assert sites["NJN000000003"]["resolution"] == "sems_site_record" and not sites["NJN000000003"]["has_coordinates"]
    dmap_url = next(url for kind, url in upstream.calls if kind == "dmap")
    assert "/name/like/@BOG%20CREEK@S@/" in dmap_url and "'" not in dmap_url
    text = api.format_search_results(result)
    assert "Unresolved candidate" in text and "not SEMS site identity" in text


def test_roi_groups_by_epa_id_and_orders_nearest_first(api, monkeypatch):
    salt_a = _boundary(
        1913,
        "AK0001897602",
        "SALT CHUCK MINE",
        "F",
        "Current Ground Boundary",
        ring=[[-74.20, 40.20], [-74.19, 40.20], [-74.19, 40.21], [-74.20, 40.21], [-74.20, 40.20]],
    )
    salt_b = _boundary(
        1914,
        "AK0001897602",
        "SALT CHUCK MINE",
        None,
        "Current Ground Boundary",
        ring=[[-74.20, 40.21], [-74.19, 40.21], [-74.19, 40.22], [-74.20, 40.22], [-74.20, 40.21]],
    )
    point_only = copy.deepcopy(L1_ALABAMA)
    point_only["geometry"] = {"x": -74.15, "y": 40.16}
    Upstream(monkeypatch, api, layers={"npl": [L1_BOG, point_only], "l2": [L2_BOG, salt_a, salt_b]})
    result = api.get_epa_superfund_sites_in_roi(40.151, -74.160, 10)
    order = [site["epa_id"] for site in result["sites"]]
    assert order == ["NJD063157150", "ALD007454085", "AK0001897602"]
    bog, alabama, salt = result["sites"]
    assert bog["match_basis"] == "point+polygon" and bog["distance_basis"] == "inside_site_polygon"
    assert alabama["match_basis"] == "point"
    assert salt["match_basis"] == "polygon" and salt["boundary_feature_count"] == 2
    text = api.format_roi_results(result, max_results=1)
    assert "Sites (1–1 of 3)" in text and "result_offset=1" in text


def test_roi_buffer_failure_is_unavailable_not_empty(api, monkeypatch):
    Upstream(monkeypatch, api)

    def boom(*_args, **_kwargs):
        raise RuntimeError("geometry down")

    ArcGISService.create_roi_buffer = staticmethod(boom)
    result = api.get_epa_superfund_sites_in_roi(40.0, -74.0, 5)
    text = api.format_roi_results(result)
    assert result["data_unavailable"] and "not a no-hit finding" in text
    assert "No published NPL points" not in text and "geometry down" not in text


# ---------------------------------------------------------------------------
# Site lookup
# ---------------------------------------------------------------------------


def test_site_lookup_by_each_identifier_mode(api, monkeypatch):
    Upstream(
        monkeypatch,
        api,
        layers={"npl": [L1_BOG], "l2": [L2_BOG], "l5": [L5_BOG]},
        dmap={"site_id/equals/0200397": [DMAP_BOG], "epa_id/equals/NJD063157150": [DMAP_BOG]},
    )
    by_epa = api.get_epa_superfund_site(epa_id="NJD063157150")
    assert by_epa["identity"]["sems_id"] == "0200397" and not by_epa["status_conflict"]
    by_sems = api.get_epa_superfund_site(sems_id="200397")
    assert by_sems["identity"]["epa_id"] == "NJD063157150"
    text = api.format_site(api.get_epa_superfund_site(frs_registry_id="110060469979"))
    assert "Construction completion is a named milestone" in text
    assert "Superfund Alternative Approach agreement indicator: N" in text
    assert "7.67 Acres (published values, not calculated)" in text
    for arguments in ({}, {"epa_id": "NJD063157150", "sems_id": "0200397"}):
        with pytest.raises(ValueError, match="exactly one"):
            api.get_epa_superfund_site(**arguments)


def test_site_reports_crosswalk_conflicts_and_partial_deletion(api, monkeypatch):
    conflicting = {**DMAP_BOG, "site_id": "0299999", "npl_status_code": "F"}
    alabama = copy.deepcopy(L1_ALABAMA)
    alabama["attributes"]["Site_EPA_ID"] = "NJD063157150"
    Upstream(monkeypatch, api, layers={"npl": [alabama]}, dmap={"epa_id/equals/NJD063157150": [conflicting]})
    result = api.get_epa_superfund_site(epa_id="NJD063157150")
    assert result["identity"]["conflict"] and result["status_conflict"]
    text = api.format_site(result)
    assert "crosswalk conflict" in text and "Sources disagree" in text
    assert "Partial deletion: flagged in the NPL status layer" in text
    bog = api.format_site(api.get_epa_superfund_site(epa_id="NJD063157150"))
    assert "absence of a flag is not proof" not in bog  # the conflicting fixture above has no plain "No" record


def test_frs_only_resolution_is_a_candidate(api, monkeypatch):
    orphan = copy.deepcopy(L5_BOG)
    orphan["attributes"].update(REGISTRY_ID="110000000009", PGM_SYS_ID="NOT-AN-EPA-ID")
    Upstream(monkeypatch, api, layers={"l5": [orphan]})
    text = api.format_site(api.get_epa_superfund_site(frs_registry_id="110000000009"))
    assert "unresolved candidate" in text


# ---------------------------------------------------------------------------
# Operable units and institutional controls
# ---------------------------------------------------------------------------


def test_institutional_controls_preserve_types_and_empty_wording(api, monkeypatch):
    Upstream(monkeypatch, api, layers={"l4": [L4_COD]})
    result = api.get_epa_superfund_institutional_controls("COD980717557")
    record = result["records"][0]
    assert record["feature_type"] == "Institutional Control Boundary"
    assert record["feature_type_raw"] == "Institutional Control Boundary "
    assert record["last_change_date"] == {"raw": None, "iso": None}
    empty = api.format_institutional_controls(api.get_epa_superfund_institutional_controls("NJD063157150"))
    assert "not evidence that no institutional controls apply" in empty


# ---------------------------------------------------------------------------
# Documents, cleanup actions, contaminants, and notices
# ---------------------------------------------------------------------------


def test_contaminants_join_filters_and_truncation(api, monkeypatch):
    upstream = Upstream(
        monkeypatch, api, dmap={"epa_id/equals/NJD063157150": [DMAP_BOG], "fk_site_id/equals/0200397": CONTAMINANTS}
    )
    result = api.get_epa_superfund_contaminants("NJD063157150")
    assert [r["media_name"] for r in result["records"]] == ["Sediment", "Soil", "Soil"]
    assert any("fk_site_id/equals/0200397/1:5001/JSON" in url for kind, url in upstream.calls)
    soil = api.get_epa_superfund_contaminants("NJD063157150", operable_unit="1", media="soil")
    assert [r["preferred_contaminant_name"] for r in soil["records"]] == ["CHROMIUM"]
    text = api.format_contaminants(result)
    assert "not a sample concentration" in text and "CAS number" in text

    monkeypatch.setattr(sys.modules["src.core.sources"], "DMAP_CONTAMINANT_ROWS", 2)
    monkeypatch.setattr(api, "DMAP_CONTAMINANT_ROWS", 2)
    truncated = api.get_epa_superfund_contaminants("NJD063157150")
    assert {r.key: r.status for r in truncated["reports"]}["dmap_contaminants"] == "truncated"
    assert "(lower bound)" in api.format_contaminants(truncated)


def test_search_cross_checks_other_sources_so_filters_keep_conflicts(api, monkeypatch):
    deleted_point = copy.deepcopy(L1_BOG)
    deleted_point["attributes"].update(Status="Deleted NPL Site", Site_Name="Rowe Industries", City="Sag Harbor")
    final_boundary = _boundary(5, "NJD063157150", "ROWE INDUSTRIES GROUND WATER CONTAMINATION", "F")
    upstream = Upstream(monkeypatch, api, layers={"npl": [deleted_point], "l2": [final_boundary]})
    original = upstream.query_features

    def status_aware(service_url, layer_id, geometry, **kwargs):
        where = kwargs["extra_params"]["where"]
        if "UPPER(Status) IN" in where and "'NPL SITE'" in where:
            upstream.calls.append(("npl", where))
            return ArcGISFeatureQueryResult(features=[], warnings=[], truncated=False)
        return original(service_url, layer_id, geometry, **kwargs)

    ArcGISService.query_features = staticmethod(status_aware)
    result = api.search_epa_superfund_sites(query="rowe", npl_status="final")
    site = result["sites"][0]
    assert site["status_conflict"] and {s.normalized for s in site["statuses"]} == {"final", "deleted"}
    assert any("Site_EPA_ID IN ('NJD063157150')" in where for kind, where in upstream.calls if kind == "npl")


def test_frs_labels_are_not_listing_evidence(api, monkeypatch):
    frs_deleted = copy.deepcopy(L5_BOG)
    frs_deleted["attributes"]["ACTIVE_STATUS"] = "DELETED FROM THE FINAL NPL"
    Upstream(
        monkeypatch, api, layers={"npl": [L1_BOG], "l5": [frs_deleted]}, dmap={"sems.envirofacts_site": [DMAP_BOG]}
    )
    result = api.search_epa_superfund_sites(query="bog", inventory_scope="sems_candidates")
    site = result["sites"][0]
    assert site["resolution"] == "npl_status_point" and not site["status_conflict"]
    assert "FRS program-interest label `DELETED FROM THE FINAL NPL`" in api.format_search_results(result)


def test_text_keeps_comparison_signs_and_strips_controls(api):
    norm = _norm()
    assert norm.text("Arsenic &lt; 10 ppb and &gt; 5 ppb") == "Arsenic < 10 ppb and > 5 ppb"
    assert norm.text("TCE < 5 and > 1") == "TCE < 5 and > 1"
    assert norm.text("a\u202eb\x1b[31mc\u200b") == "ab[31mc"
    assert "www\\." in norm.md("visit www.evil.example") and "\\@" in norm.md("a@evil.example")
    assert norm.epa_url("https://www.epa.gov:99999/x") is None and norm.epa_url("https://www.epa.gov/a)b") is None


# ---------------------------------------------------------------------------
# Records from compliant sources: SEMS decisions and the Federal Register
# ---------------------------------------------------------------------------


def test_operable_units_combine_sems_decisions_and_map_features(api, monkeypatch):
    cod_point = copy.deepcopy(L1_BOG)
    cod_point["attributes"].update(Site_EPA_ID="COD980717557", SEMS_ID=800257)
    rows = [
        dict(CONTAMINANTS[0], fk_site_id="0800257", operable_unit_num="04"),
        dict(CONTAMINANTS[2], fk_site_id="0800257"),
    ]
    Upstream(
        monkeypatch,
        api,
        layers={"npl": [cod_point], "l3": [L3_COD, L3_DELETED]},
        dmap={
            "epa_id/equals/COD980717557": [dict(DMAP_BOG, site_id="0800257", epa_id="COD980717557")],
            "fk_site_id": rows,
        },
    )
    result = api.get_epa_superfund_operable_units("COD980717557")
    sems = [r for r in result["records"] if r["kind"] == "sems_ou"]
    features = {r["object_id"]: r for r in result["records"] if r["kind"] == "map_feature"}
    assert [(u["ou_id"], u["decisions"]) for u in sems] == [
        ("02", ["Explanation of Significant Differences"]),
        ("04", ["Record of Decision"]),
    ]
    assert "which SEMS decision records list" in features[144]["crosswalk"]
    assert "not in SEMS decision records" in features[200]["crosswalk"]
    assert {r.key: r.status for r in result["reports"]}["epa_site_profile"] == "unsupported"
    text = api.format_operable_units(result)
    assert "mapped deleted-area boundary (not an active OU)" in text and "validated" not in text
    assert "robots.txt disallows automated access" in text


def test_documents_list_npl_links_sems_decisions_and_federal_register(api, monkeypatch):
    upstream = Upstream(
        monkeypatch,
        api,
        layers={"npl": [L1_BOG]},
        dmap={"epa_id/equals/NJD063157150": [DMAP_BOG], "fk_site_id": CONTAMINANTS},
        federal_register=FR_DOCS,
    )
    result = api.get_epa_superfund_documents("NJD063157150")
    by_title = {d["title"]: d for d in result["records"]}
    assert by_title["Record of Decision (OU 01)"]["category"] == "record_of_decision"
    assert by_title["Explanation of Significant Differences (OU 02)"]["date"] is None
    deletion = by_title["National Oil and Hazardous Substances Contingency Plan; National Priorities List Update"]
    assert deletion["category"] == "deletion" and deletion["basis"].startswith(
        "candidate (site named in the document title"
    )
    listing = by_title["National Priorities List for Uncontrolled Hazardous Waste Sites"]
    assert listing["url"] is None and "text only" in listing["basis"]
    assert ("federal_register", '"Bog Creek Farm"') in upstream.calls
    linked = [d for d in result["records"] if not d.get("text_only")]
    assert result["records"][-1].get("text_only") and all(
        not d.get("text_only") for d in result["records"][: len(linked)]
    )
    dated = [d["date"] for d in linked if d["date"]]
    assert dated == sorted(dated, reverse=True)
    filtered = api.get_epa_superfund_documents("NJD063157150", document_type="explanation_of_significant_differences")
    assert [d["title"] for d in filtered["records"]] == ["Explanation of Significant Differences (OU 02)"]
    text = api.format_documents(result)
    assert "javascript" not in text and "not a NEPA decision" in text


def test_cleanup_actions_use_milestones_decisions_and_named_actions(api, monkeypatch):
    Upstream(
        monkeypatch,
        api,
        layers={"npl": [L1_BOG]},
        dmap={"epa_id/equals/NJD063157150": [DMAP_BOG], "fk_site_id": CONTAMINANTS},
        federal_register=FR_DOCS,
    )
    result = api.get_epa_superfund_cleanup_actions("NJD063157150")
    kinds = [r["kind"] for r in result["records"]]
    assert kinds.count("npl_milestone") == 3 and kinds.count("sems_decision") == 2
    named = [r for r in result["records"] if r["kind"] == "federal_register_action"]
    assert [r["date"] for r in named] == ["1997-09-10", "1997-10-29"]
    only_02 = api.get_epa_superfund_cleanup_actions("NJD063157150", operable_unit="2")
    assert [(r["kind"], r["ou_id"]) for r in only_02["records"]] == [("sems_decision", "02")]
    text = api.format_cleanup_actions(result)
    assert "detailed cleanup schedule" in text and "robots.txt" in text


def test_notices_from_federal_register_with_close_dates_and_extensions(api, monkeypatch):
    Upstream(monkeypatch, api, layers={"npl": [L1_BOG]}, dmap={"epa_id/equals": [DMAP_BOG]}, federal_register=FR_DOCS)
    result = api.get_epa_superfund_public_notices("NJD063157150")
    events = {e["title"]: e for e in result["events"]}
    extension = events["National Priorities List; Extension of Comment Period for Bog Creek Farm"]
    assert (extension["kind"], extension["stage"]) == ("extension", "proposed")
    assert extension["status"] == "comment period open per the published close date"
    assert extension["dockets"] == ["FRL-5886-1"] and extension["may_revise"]
    final = events["Federal Register: final NPL listing"]
    assert final["association"].startswith("verified") and final["published"] == "1983-09-08"
    recent = api.get_epa_superfund_public_notices("NJD063157150", published_on_or_after="1997-01-01")
    assert {e["published"] for e in recent["events"]} == {"1997-10-29", "1997-09-10"}
    states = {r.key: r.status for r in result["reports"]}
    assert states["epa_notice_search"] == "unsupported" and states["federal_register"] == "truncated"
    assert "comments close 2099-10-10 (date only; time zone not stated)" in api.format_public_notices(result)


def test_federal_register_failure_is_reported_not_empty(api, monkeypatch):
    Upstream(monkeypatch, api, layers={"npl": [L1_BOG]}, federal_register=RuntimeError("down"))
    result = api.get_epa_superfund_public_notices("NJD063157150")
    assert {r.key: r.status for r in result["reports"]}["federal_register"] == "failed"
    assert "down" not in api.format_public_notices(result)


def test_text_only_federal_register_mentions_are_not_given_site_kinds(api, monkeypatch):
    Upstream(monkeypatch, api, layers={"npl": [L1_BOG]}, dmap={"epa_id/equals": [DMAP_BOG]}, federal_register=FR_DOCS)
    events = {e["title"]: e for e in api.get_epa_superfund_public_notices("NJD063157150")["events"]}
    mention = events["National Priorities List for Uncontrolled Hazardous Waste Sites"]
    assert (mention["kind"], mention["stage"]) == ("federal_register_mention", "not stated")
    assert mention["association"] == "site mentioned in the document text only; relation to this site unverified"
    assert events["Federal Register: proposed for NPL"]["kind"] == "npl_listing"


def test_search_preserves_frs_candidate_without_epa_id(api, monkeypatch):
    orphan = copy.deepcopy(L5_BOG)
    orphan["attributes"]["PGM_SYS_ID"] = "UNRESOLVED"
    Upstream(monkeypatch, api, layers={"l5": [orphan]})
    result = api.search_epa_superfund_sites(query="Bog", inventory_scope="sems_candidates")
    assert len(result["sites"]) == 1
    candidate = result["sites"][0]
    assert candidate["resolution"] == "frs_candidate_only"
    assert candidate["frs"][0]["registry_id"] == "110060469979"
    text = api.format_search_results(result)
    assert "FRS candidate 110060469979" in text and "EPA ID FRS:" not in text


@pytest.mark.parametrize(("longitude", "inside"), [(180, True), (-180, True), (179.5, True), (0, False)])
def test_antimeridian_ring_contains_only_the_date_line_area(api, longitude, inside):
    rings = [[[179, 10], [-179, 10], [-179, 12], [179, 12], [179, 10]]]
    miles, basis = _norm().polygon_distance_miles(11, longitude, rings)
    assert (basis == "inside_site_polygon") is inside
    assert (miles == 0) is inside


def test_antimeridian_holes_and_boundary_are_preserved(api):
    rings = [
        [[178, 9], [-178, 9], [-178, 13], [178, 13], [178, 9]],
        [[179, 10], [-179, 10], [-179, 12], [179, 12], [179, 10]],
    ]
    assert _norm().polygon_distance_miles(11, 180, rings)[0] > 0
    assert _norm().polygon_distance_miles(11, 178, rings) == (0, "inside_site_polygon")


def test_cached_reads_keep_original_retrieval_time_and_expire(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    clock = {"seconds": 0, "stamp": "2026-10-21T20:00:00Z"}
    calls = []
    monkeypatch.setattr(adapters.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(adapters, "now_utc", lambda: clock["stamp"])
    monkeypatch.setattr(adapters, "get_json_rows", lambda *_a, **_k: calls.append(True) or [DMAP_BOG])
    args = ["epa_id", "equals", "NJD063157150"]
    _, first = adapters.dmap_sites(args, api.Budget())
    clock.update(seconds=60, stamp="2026-10-21T20:01:00Z")
    _, cached = adapters.dmap_sites(args, api.Budget())
    assert len(calls) == 1 and cached.retrieved_at == first.retrieved_at == "2026-10-21T20:00:00Z"
    assert first.retrieved_at in cached.note and "Cached response" in cached.note
    clock.update(seconds=601, stamp="2026-10-21T20:10:01Z")
    _, fresh = adapters.dmap_sites(args, api.Budget())
    assert len(calls) == 2 and fresh.retrieved_at == clock["stamp"] and not fresh.note


@pytest.mark.parametrize("results", [None, "invalid"])
def test_missing_federal_register_list_is_failed_not_empty(api, monkeypatch, results):
    upstream = Upstream(monkeypatch, api, federal_register={"count": 0, "results": results})
    rows, report = upstream.adapters.federal_register_documents("Bog Creek Farm", api.Budget())
    assert not rows and report.status == "failed"
    monkeypatch.setattr(upstream.adapters, "get_json", lambda *_a, **_k: {"count": 0, "results": []})
    rows, report = upstream.adapters.federal_register_documents("Bog Creek Farm", api.Budget())
    assert not rows and report.status == "empty"


def test_malformed_federal_register_rows_are_partial_not_complete(api, monkeypatch):
    upstream = Upstream(monkeypatch, api, federal_register={"count": 1, "results": [{"bad": "row"}]})
    rows, report = upstream.adapters.federal_register_documents("Bog Creek Farm", api.Budget())
    assert not rows and report.status == "partial" and "malformed" in report.note


def test_same_date_does_not_merge_unrelated_notice_with_verified_listing(api, monkeypatch):
    unrelated = {
        **FR_DOCS["results"][2],
        "publication_date": "1983-09-08",
        "title": "Settlement notice for a different site",
        "action": "Notice.",
        "html_url": "https://www.federalregister.gov/documents/1983/09/08/83-12345/settlement",
    }
    Upstream(monkeypatch, api, layers={"npl": [L1_BOG]}, federal_register={"count": 1, "results": [unrelated]})
    events = api.get_epa_superfund_public_notices("NJD063157150")["events"]
    same_date = [event for event in events if event["published"] == "1983-09-08"]
    assert len(same_date) == 2
    verified = next(event for event in same_date if event["association"].startswith("verified"))
    assert "federal_register_url" not in verified
    assert any(event["kind"] == "federal_register_mention" for event in same_date)


def test_layer_fetches_bounded_id_batches_in_source_order(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    id_calls, batches = [], []
    geometry = {"rings": [BOG_RING]}

    def ids(*args, **kwargs):
        id_calls.append((args, kwargs))
        return [1, 2, 3]

    def features(*args, **kwargs):
        batches.append((args, kwargs))
        selected = [int(i) for i in kwargs["extra_params"]["objectIds"].split(",")]
        return ArcGISFeatureQueryResult([_boundary(i, "NJD063157150", "Bog", "F") for i in reversed(selected)], [])

    monkeypatch.setattr(adapters, "ARCGIS_ID_BATCH_SIZE", 2)
    monkeypatch.setattr(ArcGISService, "query_object_ids", ids)
    monkeypatch.setattr(ArcGISService, "query_features", features)
    rows, report = adapters.query_layer(
        api.SITE_BOUNDARIES,
        where="STATE_CODE = 'NJ'",
        geometry=geometry,
        return_geometry=True,
        budget=api.Budget(),
        max_features=10,
    )
    assert report.status == "complete" and [r["attributes"]["OBJECTID"] for r in rows] == [1, 2, 3]
    assert len(id_calls) == 2 and all(args[2] is geometry for args, _ in id_calls)
    assert [kwargs["extra_params"]["objectIds"] for _, kwargs in batches] == ["1,2", "3"]
    for args, kwargs in batches:
        assert args[2] is None and kwargs["out_sr"] == 4326
        assert kwargs["extra_params"]["where"] == "STATE_CODE = 'NJ'"
        assert kwargs["max_features"] == kwargs["page_size"] <= 2
        assert kwargs["allow_redirects"] is False and kwargs["headers"]
    assert len(report.fingerprint) == 64


def test_layer_id_safety_cap_is_a_lower_bound(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **_k: [1, 2, 3])
    selected = []

    def features(*_a, **kwargs):
        selected.extend(kwargs["extra_params"]["objectIds"].split(","))
        return ArcGISFeatureQueryResult([_boundary(int(i), "NJD063157150", "Bog", "F") for i in selected], [])

    monkeypatch.setattr(ArcGISService, "query_features", features)
    rows, report = adapters.query_layer(api.SITE_BOUNDARIES, where="1=1", budget=api.Budget(), max_features=2)
    assert selected == ["1", "2"] and len(rows) == 2
    assert report.status == "truncated" and "lower bounds" in report.note
    selected.clear()
    changed_ids = iter([[1, 2, 3], [1, 2, 3, 4]])
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **_k: next(changed_ids))
    _, changed = adapters.query_layer(api.SITE_BOUNDARIES, where="1=1", budget=api.Budget(), max_features=2)
    assert changed.status == "truncated" and "changed during retrieval" in changed.note
    assert changed.fingerprint != report.fingerprint


def test_result_fingerprint_excludes_retrieval_and_cache_bookkeeping(api, monkeypatch):
    report = api.SourceReport("source", "Source", "complete", 1, retrieved_at="2026-10-21T00:00:00Z")
    first = api._result([report], [], records=[{"id": 1}])
    report.retrieved_at, report.note = "2026-10-21T00:01:00Z", "Cached response originally retrieved earlier"
    monkeypatch.setattr(api, "now_utc", lambda: "2026-10-21T00:01:00Z")
    assert api._result([report], [], records=[{"id": 1}])["result_fingerprint"] == first["result_fingerprint"]
    report.status = "partial"
    assert api._result([report], [], records=[{"id": 1}])["result_fingerprint"] != first["result_fingerprint"]


def test_site_reports_reuse_listing_and_flags_implausible_area(api, monkeypatch):
    reuse = {
        "attributes": {
            "FID": 7,
            "Site_ID": 200397,
            "Site_Name": "BOG CREEK FARM",
            "Snapshot": "https://www.epa.gov/superfund-redevelopment/superfund-sites-reuse-new-jersey#bogcreek",
        }
    }
    huge = _boundary(138, "NJD063157150", "BOG CREEK FARM", "F", GIS_AREA=252409.0)
    miles = _boundary(139, "NJD063157150", "BOG CREEK FARM", "F", GIS_AREA=43.5655, GIS_AREA_UNITS="Miles")
    Upstream(
        monkeypatch,
        api,
        layers={"npl": [L1_BOG], "l2": [huge, miles], "reuse": [reuse]},
        dmap={"epa_id/equals": [DMAP_BOG]},
    )
    result = api.get_epa_superfund_site(epa_id="NJD063157150")
    assert result["reuse"]["listed"] and result["area"]["acres"] == 252409.0
    text = api.format_site(result)
    assert (
        "Listed on EPA's Superfund Sites in Reuse map" in text
        and "not a determination that the site is suitable" in text
    )
    assert "likely a facility perimeter" in text and "units Miles, which are not areas" in text
    search = api.search_epa_superfund_sites(query="bog")
    row = api.format_search_results(search)
    assert "federal facility: Not a Federal Facility" in row and "construction completion milestone 1994-06-30" in row


def test_federal_register_rules_on_a_site_milestone_date_are_stronger_candidates(api, monkeypatch):
    listing = dict(FR_DOCS["results"][2], publication_date="1983-09-08", document_number="83-23701")
    Upstream(
        monkeypatch,
        api,
        layers={"npl": [L1_BOG]},
        dmap={"epa_id/equals": [DMAP_BOG]},
        federal_register={"count": 1, "results": [listing]},
    )
    events = api.get_epa_superfund_public_notices("NJD063157150")["events"]
    matched = next(
        e for e in events if e["published"] == "1983-09-08" and e["title"].startswith("National Priorities List")
    )
    assert matched["association"] == "candidate (NPL rule published on this site's listed date)"
    assert matched["kind"] == "npl_listing" and not matched["text_only"]
