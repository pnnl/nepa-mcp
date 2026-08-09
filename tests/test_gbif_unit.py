"""
Unit tests for the GBIF API layer (``gbif/src/apis/gbif_api.py`` and the
``gbif/src/apis/counties_api.py`` it depends on).

These exercise the pure parsing/formatting/aggregation logic with the HTTP
layer mocked: the GBIF occurrence REST API (``requests.get``) and the counties
ArcGIS query (``ArcGISService``). No network calls are made. They follow the
same dynamic per-server import pattern used by ``test_usace_unit.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "gbif"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_gbif_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_gbif_unit_api",
            SERVER_DIR / "src" / "apis" / "gbif_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_gbif_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


# ---------------------------------------------------------------------------
# HTTP / ArcGIS mocking helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _gbif_record(
    sci="Ursus arctos",
    iucn="EN",
    key=1,
    lat=34.5,
    lon=-106.5,
    date="2020-05-01T00:00:00",
    common="Grizzly Bear",
    county="",
    state="",
):
    return {
        "key": key,
        "scientificName": sci,
        "vernacularName": common,
        "decimalLatitude": lat,
        "decimalLongitude": lon,
        "eventDate": date,
        "year": 2020,
        "month": 5,
        "iucnRedListCategory": iucn,
        "stateProvince": state,
        "county": county,
    }


def _single_page_get(records, capture=None):
    """Return a fake requests.get that yields one page then endOfRecords."""

    def fake_get(url, params=None, timeout=None):
        if capture is not None:
            capture.append(dict(params or {}))
        return _FakeResponse({"results": list(records), "endOfRecords": True})

    return fake_get


def _patch_counties(api, monkeypatch, features):
    """Patch the ArcGIS layer used by counties_api (imported by gbif_api)."""
    counties_mod = sys.modules["src.apis.counties_api"]
    monkeypatch.setattr(
        counties_mod.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    )
    monkeypatch.setattr(
        counties_mod.ArcGISService,
        "query_features",
        staticmethod(lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[])),
    )


# ---------------------------------------------------------------------------
# Bounding-box + year-range helpers (pure functions)
# ---------------------------------------------------------------------------


class TestBBoxParams:
    def test_bbox_brackets_the_center(self):
        api = _load_gbif_api()
        params = api._gbif_bbox_params(34.5, -106.5, 25.0)
        lat_min, lat_max = (float(v) for v in params["decimalLatitude"].split(","))
        lon_min, lon_max = (float(v) for v in params["decimalLongitude"].split(","))
        assert lat_min < 34.5 < lat_max
        assert lon_min < -106.5 < lon_max

    def test_near_pole_uses_full_longitude(self):
        api = _load_gbif_api()
        params = api._gbif_bbox_params(89.99, 0.0, 100.0)
        assert params["decimalLongitude"] == "-180.000000,180.000000"

    def test_year_range_ends_current_year(self):
        api = _load_gbif_api()
        from datetime import date

        assert api._gbif_year_range(2015) == f"2015,{date.today().year}"


# ---------------------------------------------------------------------------
# Occurrence parsing
# ---------------------------------------------------------------------------


class TestOccurrenceParsing:
    def test_parses_core_fields_and_maps_iucn(self, monkeypatch):
        api = _load_gbif_api()
        monkeypatch.setattr(api.requests, "get", _single_page_get([_gbif_record(iucn="CR")]))
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 1
        occ = result["occurrences"][0]
        assert occ["scientific_name"] == "Ursus arctos"
        assert occ["threat_status"] == "Critically Endangered"
        assert occ["latitude"] == 34.5
        assert occ["observation_date"] == "2020-05-01"

    def test_summary_counts_unique_species_and_status(self, monkeypatch):
        api = _load_gbif_api()
        records = [
            _gbif_record(sci="Species A", iucn="EN", key=1),
            _gbif_record(sci="Species A", iucn="EN", key=2),
            _gbif_record(sci="Species B", iucn="VU", key=3),
        ]
        monkeypatch.setattr(api.requests, "get", _single_page_get(records))
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["summary"]["unique_species"] == 2
        assert result["summary"]["by_threat_status"]["Endangered"] == 2
        assert result["summary"]["by_threat_status"]["Vulnerable"] == 1

    def test_threatened_only_adds_iucn_filter(self, monkeypatch):
        api = _load_gbif_api()
        capture = []
        monkeypatch.setattr(api.requests, "get", _single_page_get([_gbif_record()], capture))
        api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0, threatened_only=True)
        assert capture and capture[0].get("iucnRedListCategory") == api.IUCN_CATEGORIES_LIST

    def test_all_species_omits_iucn_filter(self, monkeypatch):
        api = _load_gbif_api()
        capture = []
        monkeypatch.setattr(api.requests, "get", _single_page_get([_gbif_record()], capture))
        api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0, threatened_only=False)
        assert capture and "iucnRedListCategory" not in capture[0]

    def test_empty_results_yield_zero_count(self, monkeypatch):
        api = _load_gbif_api()
        monkeypatch.setattr(api.requests, "get", _single_page_get([]))
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 0
        assert result["summary"] == {}


# ---------------------------------------------------------------------------
# Deduplication to species list
# ---------------------------------------------------------------------------


class TestSpeciesDeduplication:
    def test_collapses_occurrences_to_unique_species(self):
        api = _load_gbif_api()
        occ = [
            {"scientific_name": "Sp A", "threat_status": "EN", "observation_date": "2019-01-01"},
            {"scientific_name": "Sp A", "threat_status": "EN", "observation_date": "2021-01-01"},
            {"scientific_name": "Sp B", "threat_status": "VU", "observation_date": "2020-06-01"},
        ]
        species = api._deduplicate_to_species_list(occ)
        assert len(species) == 2
        sp_a = next(s for s in species if s["scientific_name"] == "Sp A")
        assert sp_a["observation_count"] == 2
        assert sp_a["first_seen"] == "2019-01-01"
        assert sp_a["last_seen"] == "2021-01-01"

    def test_unknown_species_are_skipped(self):
        api = _load_gbif_api()
        occ = [{"scientific_name": "Unknown"}, {"scientific_name": ""}, {"scientific_name": "Real Sp"}]
        species = api._deduplicate_to_species_list(occ)
        assert [s["scientific_name"] for s in species] == ["Real Sp"]


# ---------------------------------------------------------------------------
# County aggregation
# ---------------------------------------------------------------------------


class TestCountyAggregation:
    def test_aggregates_species_by_county(self, monkeypatch):
        api = _load_gbif_api()
        _patch_counties(
            api,
            monkeypatch,
            [
                {
                    "attributes": {
                        "NAME": "Los Angeles County",
                        "STATE": "06",
                        "BASENAME": "Los Angeles",
                        "GEOID": "06037",
                    }
                }
            ],
        )
        monkeypatch.setattr(
            api.requests, "get", _single_page_get([_gbif_record(sci="Sp A"), _gbif_record(sci="Sp B", key=2)])
        )
        result = api.get_gbif_species_by_county_sync(34.5, -118.0, 25.0)
        assert result["total_counties"] == 1
        county = result["counties"][0]
        assert county["county_name"] == "Los Angeles County"
        assert county["state"] == "California"
        assert county["state_abbr"] == "CA"
        assert county["total_species"] == 2
        assert result["total_unique_species"] == 2

    def test_no_counties_returns_empty_structure(self, monkeypatch):
        api = _load_gbif_api()
        _patch_counties(api, monkeypatch, [])
        result = api.get_gbif_species_by_county_sync(34.5, -118.0, 25.0)
        assert result["total_counties"] == 0
        assert result["counties"] == []
        assert result["total_unique_species"] == 0

    def test_county_without_state_mapping_is_dropped(self, monkeypatch):
        api = _load_gbif_api()
        # STATE "99" is not a real FIPS -> STATE_FIPS_TO_NAME miss -> county skipped.
        _patch_counties(
            api,
            monkeypatch,
            [{"attributes": {"NAME": "Nowhere County", "STATE": "99", "BASENAME": "Nowhere", "GEOID": "99001"}}],
        )
        monkeypatch.setattr(api.requests, "get", _single_page_get([_gbif_record()]))
        result = api.get_gbif_species_by_county_sync(34.5, -118.0, 25.0)
        assert result["total_counties"] == 0


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_occurrence_summary_renders_markdown(self):
        api = _load_gbif_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "occurrences": [{"scientific_name": "Ursus arctos", "common_name": "Grizzly"}],
            "summary": {"total_occurrences": 1, "unique_species": 1, "by_threat_status": {"Endangered": 1}},
        }
        out = api.format_occurrences_summary(data, 2015, True)
        assert "GBIF Georeferenced Species Occurrences" in out
        assert "Threatened/Endangered only" in out
        assert "Ursus arctos" in out
        assert "Endangered: 1" in out

    def test_occurrence_summary_all_species_label(self):
        api = _load_gbif_api()
        data = {"center": {}, "buffer_miles": 25.0, "occurrences": [], "summary": {}}
        out = api.format_occurrences_summary(data, 2015, False)
        assert "All species" in out

    def test_county_summary_renders_markdown(self):
        api = _load_gbif_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -118.0},
            "buffer_miles": 25.0,
            "counties": [
                {
                    "county_name": "Los Angeles County",
                    "state_abbr": "CA",
                    "total_species": 2,
                    "total_observations": 5,
                    "species_list": [
                        {"scientific_name": "Sp A", "common_name": "A", "observation_count": 3, "threat_status": "EN"}
                    ],
                }
            ],
            "total_counties": 1,
            "total_unique_species": 2,
            "summary": {"total_species_observations": 2, "total_observations": 5, "by_threat_status": {"EN": 2}},
        }
        out = api.format_species_by_county_summary(data, 2015, True)
        assert "GBIF Species Presence by County" in out
        assert "Los Angeles County, CA" in out
        assert "Sp A" in out
