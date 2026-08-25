"""
Unit tests for the EPA ACRES API layer (``epa_acres/src/apis/acres_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS query layer
mocked, so no network calls are made. They follow the same dynamic per-server
import pattern used by ``test_padus_unit.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-80.1, 40.3], [-79.9, 40.3], [-79.9, 40.5], [-80.1, 40.5], [-80.1, 40.3]]],
    "spatialReference": {"wkid": 4326},
}

# Attribute names and shapes mirror a live response from the Envirofacts
# Brownfields layer (EMEF efpoints MapServer layer 5).
SAMPLE_ATTRIBUTES = {
    "registry_id": "110038700607",
    "primary_name": "FORMER BROOKS ARMORED CAR",
    "location_address": "1819 WHARTON",
    "city_name": "PITTSBURGH",
    "county_name": "ALLEGHENY",
    "state_code": "PA",
    "epa_region": "Region 03",
    "postal_code": "15203",
    "latitude": 40.430555,
    "longitude": -79.980113,
    "pgm_sys_id": "15332",
    "facility_url": "https://ofmpub.epa.gov/apex/cimc/f?p=CIMC:31::::Y,31,0:P31_ID:15332",
}


def _load_acres_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "epa_acres"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_epa_acres_unit_api",
            server_dir / "src" / "apis" / "acres_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_epa_acres_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, features, warnings=None, truncated=False):
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=warnings or [], truncated=truncated),
    )


# ---------------------------------------------------------------------------
# Record parsing
# ---------------------------------------------------------------------------


class TestRecordParsing:
    def test_parses_all_record_fields(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": dict(SAMPLE_ATTRIBUTES)}])
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99, 25.0)
        assert result["total"] == 1
        prop = result["properties"][0]
        assert prop["name"] == "FORMER BROOKS ARMORED CAR"
        assert prop["address"] == "1819 WHARTON"
        assert prop["city"] == "PITTSBURGH"
        assert prop["county"] == "ALLEGHENY"
        assert prop["state"] == "PA"
        assert prop["zip"] == "15203"
        assert prop["epa_region"] == "Region 03"
        assert prop["frs_registry_id"] == "110038700607"
        assert prop["acres_property_id"] == "15332"
        assert prop["latitude"] == 40.430555
        assert prop["longitude"] == -79.980113
        assert prop["distance_miles"] > 0
        assert prop["facility_url"] == SAMPLE_ATTRIBUTES["facility_url"]
        assert result["center"] == {"latitude": 40.44, "longitude": -79.99}
        assert result["buffer_miles"] == 25.0
        assert result["counts_by_state"] == {"PA": 1}

    def test_missing_fields_fall_back_to_defaults(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {"registry_id": "110000000001"}}])
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        prop = result["properties"][0]
        assert prop["name"] == "Unknown"
        assert prop["state"] == ""
        assert prop["frs_registry_id"] == "110000000001"
        assert prop["acres_property_id"] == ""
        assert prop["latitude"] is None
        assert prop["longitude"] is None
        assert prop["distance_miles"] is None

    def test_non_numeric_coordinates_coerced_to_none(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [{"attributes": {"registry_id": "110000000001", "latitude": "not-a-number", "longitude": None}}],
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        prop = result["properties"][0]
        assert prop["latitude"] is None
        assert prop["longitude"] is None
        assert prop["distance_miles"] is None

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [])
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["properties"] == []
        assert "data_unavailable" not in result

    def test_requests_brownfields_layer_without_geometry(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        captured = {}

        def query_features(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        api.get_epa_acres_properties_in_roi(40.44, -79.99)

        assert captured["args"][:2] == (api.ACRES_SERVICE_URL, api.ACRES_BROWNFIELDS_LAYER_ID)
        out_fields = captured["kwargs"]["out_fields"].split(",")
        for field in ("registry_id", "primary_name", "epa_region", "pgm_sys_id", "facility_url"):
            assert field in out_fields
        assert captured["kwargs"].get("return_geometry", False) is False
        assert "out_sr" not in captured["kwargs"]
        assert captured["kwargs"]["timeout"] == api.ACRES_QUERY_TIMEOUT_SECONDS
        assert captured["kwargs"]["max_attempts"] == api.ACRES_QUERY_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestSorting:
    def test_records_sorted_nearest_first_with_stable_text_tiebreakers(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [
                {
                    "attributes": {
                        "state_code": "PA",
                        "city_name": "FAR",
                        "primary_name": "SITE FAR",
                        "latitude": 41.0,
                        "longitude": -80.0,
                    }
                },
                {
                    "attributes": {
                        "state_code": "WV",
                        "city_name": "NEAR",
                        "primary_name": "SITE NEAR",
                        "latitude": 40.441,
                        "longitude": -79.99,
                    }
                },
                {"attributes": {"state_code": "PA", "city_name": "UNKNOWN", "primary_name": "NO COORDS"}},
            ],
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert [p["name"] for p in result["properties"]] == ["SITE NEAR", "SITE FAR", "NO COORDS"]
        assert result["properties"][0]["distance_miles"] < result["properties"][1]["distance_miles"]


# ---------------------------------------------------------------------------
# Empty vs partial vs unavailable results
# ---------------------------------------------------------------------------


class TestResultStates:
    def test_upstream_warnings_and_truncation_preserved(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [{"attributes": dict(SAMPLE_ATTRIBUTES)}],
            warnings=["EPA ACRES Brownfields layer reached the 10000 feature safety cap; results are partial."],
            truncated=True,
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["truncated"] is True
        assert result["partial"] is True
        assert result["warnings"] == [
            "EPA ACRES Brownfields layer reached the 10000 feature safety cap; results are partial."
        ]
        assert "data_unavailable" not in result

    def test_query_failure_marks_data_unavailable(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("EPA ACRES Brownfields layer upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["data_unavailable"] is True
        assert result["error"] == "EPA ACRES Brownfields data were unavailable for this request."
        assert "upstream 500" not in result["error"]
        assert any("not a no-hit finding" in warning for warning in result["warnings"])

    def test_buffer_failure_marks_data_unavailable(self, monkeypatch):
        api = _load_acres_api()

        def boom(*_a, **_k):
            raise RuntimeError("GeometryServer unavailable")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["data_unavailable"] is True
        assert result["error"] == "ArcGIS GeometryServer was unavailable for this request."


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def _data(self, properties, warnings=None, **extra):
        return {
            "center": {"latitude": 40.44, "longitude": -79.99},
            "buffer_miles": 25.0,
            "total": len(properties),
            "properties": properties,
            "warnings": warnings or [],
            "truncated": False,
            **extra,
        }

    def _property(self, **overrides):
        prop = {
            "name": "FORMER BROOKS ARMORED CAR",
            "address": "1819 WHARTON",
            "city": "PITTSBURGH",
            "county": "ALLEGHENY",
            "state": "PA",
            "zip": "15203",
            "epa_region": "Region 03",
            "frs_registry_id": "110038700607",
            "acres_property_id": "15332",
            "latitude": 40.430555,
            "longitude": -79.980113,
            "distance_miles": 0.75,
            "facility_url": SAMPLE_ATTRIBUTES["facility_url"],
        }
        prop.update(overrides)
        return prop

    def test_summary_renders_header_and_property_fields(self):
        api = _load_acres_api()
        out = api.format_epa_acres_summary(self._data([self._property()]))
        assert "## EPA ACRES Brownfields Properties" in out
        assert "**Total ACRES Properties:** 1" in out
        assert "### Properties by State" in out
        assert "- **PA:** 1 property" in out
        assert "#### PA (1 property shown)" in out
        assert "**FORMER BROOKS ARMORED CAR**" in out
        assert "1819 WHARTON, PITTSBURGH, ALLEGHENY, 15203" in out
        assert "Region 03" in out
        assert "FRS Registry ID 110038700607" in out
        assert "ACRES ID 15332" in out
        assert "(40.430555, -79.980113)" in out
        assert "0.750 mi from center" in out
        assert f"[EPA property record]({SAMPLE_ATTRIBUTES['facility_url']})" in out

    def test_summary_handles_empty_with_inventory_caveat(self):
        api = _load_acres_api()
        out = api.format_epa_acres_summary(self._data([]))
        assert "**Total ACRES Properties:** 0" in out
        assert "No ACRES Brownfields properties were identified within the ROI buffer." in out
        assert "An empty result is not evidence that the area" in out

    def test_summary_surfaces_warnings(self):
        api = _load_acres_api()
        out = api.format_epa_acres_summary(self._data([], warnings=["upstream degraded"]))
        assert "> Warning: upstream degraded" in out

    def test_summary_marks_unavailable_results_without_no_hit_claim(self):
        api = _load_acres_api()
        out = api.format_epa_acres_summary(
            self._data([], data_unavailable=True, error="ACRES data unavailable: upstream 500")
        )
        assert "unavailable for this request, not a no-hit finding" in out
        assert "Error during query: ACRES data unavailable: upstream 500" in out
        assert "No ACRES Brownfields properties were identified" not in out

    def test_summary_paginates_nearest_first_listing(self):
        api = _load_acres_api()
        properties = [self._property(name=f"SITE {i:03d}") for i in range(api.MAX_PAGE_SIZE + 5)]
        data = self._data(properties)
        out = api.format_epa_acres_summary(data)
        assert f"Property Details (1–{api.MAX_PAGE_SIZE} of {len(properties)})" in out
        assert f"result_offset={api.MAX_PAGE_SIZE}" in out
        assert "SITE 000" in out
        assert f"SITE {api.MAX_PAGE_SIZE + 4:03d}" not in out

        second_page = api.format_epa_acres_summary(data, result_offset=api.MAX_PAGE_SIZE)
        assert f"Property Details ({api.MAX_PAGE_SIZE + 1}–{len(properties)} of {len(properties)})" in second_page
        assert "SITE 000" not in second_page
        assert f"SITE {api.MAX_PAGE_SIZE + 4:03d}" in second_page

    def test_summary_keeps_complete_state_counts_when_page_omits_a_state(self):
        api = _load_acres_api()
        properties = [self._property(name=f"PA {i:03d}", state="PA") for i in range(101)]
        properties.append(self._property(name="WV SITE", state="WV"))
        out = api.format_epa_acres_summary(self._data(properties))
        assert "- **PA:** 101 properties" in out
        assert "- **WV:** 1 property" in out
        assert "WV SITE" not in out

    def test_summary_lists_everything_at_exactly_the_cap(self):
        api = _load_acres_api()
        properties = [self._property(name=f"SITE {i:03d}") for i in range(api.MAX_PAGE_SIZE)]
        out = api.format_epa_acres_summary(self._data(properties))
        assert f"SITE {api.MAX_PAGE_SIZE - 1:03d}" in out
        assert "More records are available" not in out

    def test_summary_labels_upstream_truncation_as_a_lower_bound(self):
        api = _load_acres_api()
        out = api.format_epa_acres_summary(self._data([self._property()], truncated=True))
        assert "**Returned ACRES Properties:** 1" in out
        assert "returned count is a lower bound" in out

    def test_summary_states_acres_limitations(self):
        api = _load_acres_api()
        out = api.format_epa_acres_summary(self._data([self._property()]))
        assert "not a complete inventory of brownfields or contaminated sites" in out
        assert "not a determination that land is contaminated, available, or suitable for development" in out
        assert "EPA Envirofacts Brownfields ArcGIS layer" in out
