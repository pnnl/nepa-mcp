"""
Unit tests for the Census API layer (``census/src/apis/simplified_census_api.py``).

These exercise the pure parsing/formatting logic with the network (``requests``
and the ArcGIS buffer helper) mocked, so no calls are made. They follow the same
dynamic per-server import pattern used by the USACE template tests.

The census api talks to three HTTP endpoints via ``requests.get``:
  * TIGERweb (counties intersecting the ROI),
  * the ACS profile API (per-county variables), and
  * the ACS ``variables.json`` metadata (industry/occupation labels).
A single router-style fake ``requests.get`` handles all three.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "census"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

# Default per-variable raw values keyed by ACS variable code.
DEFAULT_VALUE_MAP = {
    "DP03_0062E": "55000",  # median household income  -> $55,000
    "DP03_0088E": "30000",  # per capita income        -> $30,000
    "DP03_0128PE": "12.5",  # families below poverty   -> 12.5%
    "DP03_0134PE": "15.0",  # people below poverty     -> 15.0%
    "DP03_0009PE": "6.2",  # unemployment rate        -> 6.2%
    "DP03_0008E": "300000",  # civilian labor force    -> 300,000
    "DP03_0004E": "280000",  # employed                -> 280,000
}

# Minimal ACS profile variables metadata for industry/occupation extraction.
DEFAULT_VARIABLES_META = {
    "DP03_0033PE": {
        "label": "Estimate!!INDUSTRY!!Civilian employed population 16 years and over!!Agriculture, forestry, fishing"
    },
    "DP03_0034PE": {"label": "Estimate!!INDUSTRY!!Civilian employed population 16 years and over!!Construction"},
    "DP03_0027PE": {
        "label": "Estimate!!OCCUPATION!!Civilian employed population 16 years and over!!Management, business, science"
    },
    "DP03_0028PE": {
        "label": "Estimate!!OCCUPATION!!Civilian employed population 16 years and over!!Service occupations"
    },
}

INDUSTRY_OCCUPATION_VALUES = {
    "DP03_0033PE": "20.0",
    "DP03_0034PE": "8.0",
    "DP03_0027PE": "35.0",
    "DP03_0028PE": "18.0",
}


def _load_census_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_census_unit_api",
            SERVER_DIR / "src" / "apis" / "simplified_census_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_census_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _make_router(api, counties, value_map=None, variables_meta=None):
    """Build a fake ``requests.get`` routing across the three census endpoints."""
    value_map = {**DEFAULT_VALUE_MAP, **(value_map or {})}
    variables_meta = variables_meta if variables_meta is not None else DEFAULT_VARIABLES_META

    def fake_get(url, params=None, timeout=None, **_kwargs):
        params = params or {}
        low = url.lower()
        if "tigerweb" in low:
            features = [{"attributes": attrs} for attrs in counties]
            return _FakeResponse({"features": features})
        if url.endswith("variables.json"):
            return _FakeResponse({"variables": variables_meta})
        # ACS profile per-county fetch.
        requested = params.get("get", "").split(",") if params.get("get") else []
        headers = requested + ["state", "county"]
        values = [value_map.get(var, "-888888888") for var in requested] + ["35", "001"]
        return _FakeResponse([headers, values])

    return fake_get


def _patch_network(api, monkeypatch, counties, value_map=None, variables_meta=None):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    monkeypatch.setattr(api.requests, "get", _make_router(api, counties, value_map, variables_meta))


BERNALILLO = {"NAME": "Bernalillo County", "GEOID": "35001"}


# ---------------------------------------------------------------------------
# API key handling
# ---------------------------------------------------------------------------


class TestApiKeyHandling:
    def test_missing_key_raises_census_error(self, monkeypatch):
        api = _load_census_api()
        monkeypatch.delenv("CENSUS_API_KEY", raising=False)
        try:
            api.SimplifiedCensusAPI()
        except api.CensusError as exc:
            assert "API key" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected CensusError when no key present")

    def test_explicit_key_is_accepted(self, monkeypatch):
        api = _load_census_api()
        monkeypatch.delenv("CENSUS_API_KEY", raising=False)
        client = api.SimplifiedCensusAPI(api_key="unit-test-key")
        assert client.api_key == "unit-test-key"

    def test_env_key_is_used(self, monkeypatch):
        api = _load_census_api()
        monkeypatch.setenv("CENSUS_API_KEY", "env-key")
        client = api.SimplifiedCensusAPI()
        assert client.api_key == "env-key"


# ---------------------------------------------------------------------------
# County lookup
# ---------------------------------------------------------------------------


class TestCountyLookup:
    def test_parses_county_fields(self, monkeypatch):
        api = _load_census_api()
        _patch_network(api, monkeypatch, [BERNALILLO])
        client = api.SimplifiedCensusAPI(api_key="k")
        counties = client._get_counties(34.5, -106.5, 25.0)
        assert len(counties) == 1
        county = counties[0]
        assert county["name"] == "Bernalillo County"
        assert county["geoid"] == "35001"
        assert county["state_fips"] == "35"
        assert county["county_fips"] == "001"
        assert county["state_abbr"] == "NM"

    def test_short_geoid_is_skipped(self, monkeypatch):
        api = _load_census_api()
        _patch_network(api, monkeypatch, [{"NAME": "Bad", "GEOID": "35"}])
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._get_counties(34.5, -106.5, 25.0) == []

    def test_counties_sorted_by_state_and_name(self, monkeypatch):
        api = _load_census_api()
        _patch_network(
            api,
            monkeypatch,
            [
                {"NAME": "Santa Fe County", "GEOID": "35049"},
                {"NAME": "Bernalillo County", "GEOID": "35001"},
            ],
        )
        client = api.SimplifiedCensusAPI(api_key="k")
        counties = client._get_counties(34.5, -106.5, 25.0)
        assert [c["name"] for c in counties] == ["Bernalillo County", "Santa Fe County"]


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------


class TestFormatValue:
    def test_currency(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._format_value("55000", "currency") == "$55,000"

    def test_percentage(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._format_value("6.2", "percentage") == "6.2%"

    def test_count(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._format_value("300000", "count") == "300,000"

    def test_invalid_sentinel_is_na(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._format_value("-888888888", "currency") == "N/A"

    def test_none_is_na(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._format_value(None, "count") == "N/A"

    def test_non_numeric_is_na(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        assert client._format_value("abc", "count") == "N/A"


# ---------------------------------------------------------------------------
# Label cleaning and top-N selection
# ---------------------------------------------------------------------------


class TestLabelCleaning:
    def test_strips_industry_prefix(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        label = "Estimate!!INDUSTRY!!Civilian employed population 16 years and over!!Construction"
        assert client._clean_label(label) == "Construction"


class TestPickTopN:
    def test_picks_highest_and_respects_limit(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        var_list = [("V1", "Agriculture"), ("V2", "Construction"), ("V3", "Retail")]
        raw = {"V1": "20.0", "V2": "8.0", "V3": "35.0"}
        picked = client._pick_top_n(raw, var_list, top_n=2)
        assert [p["category"] for p in picked] == ["Retail", "Agriculture"]

    def test_excludes_total_keyword(self, monkeypatch):
        api = _load_census_api()
        client = api.SimplifiedCensusAPI(api_key="k")
        var_list = [("V1", "Total civilian employed"), ("V2", "Construction")]
        raw = {"V1": "90.0", "V2": "8.0"}
        picked = client._pick_top_n(raw, var_list, top_n=5)
        assert [p["category"] for p in picked] == ["Construction"]


# ---------------------------------------------------------------------------
# End-to-end data assembly
# ---------------------------------------------------------------------------


class TestGetCensusDataByCoordinates:
    def test_returns_indicators_for_county(self, monkeypatch):
        api = _load_census_api()
        _patch_network(api, monkeypatch, [BERNALILLO])
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["status"] == "success"
        assert data["total_counties"] == 1
        assert data["center"] == {"latitude": 34.5, "longitude": -106.5}
        assert data["acs_period"] == "2019-2023"
        county = data["counties"][0]
        assert county["name"] == "Bernalillo County"
        assert county["indicators"]["Median household income"] == "$55,000"
        assert county["indicators"]["Unemployment rate"] == "6.2%"

    def test_no_counties_is_success_with_empty_list(self, monkeypatch):
        api = _load_census_api()
        _patch_network(api, monkeypatch, [])
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["status"] == "success"
        assert data["total_counties"] == 0
        assert data["counties"] == []

    def test_includes_industries_and_occupations(self, monkeypatch):
        api = _load_census_api()
        _patch_network(
            api,
            monkeypatch,
            [BERNALILLO],
            value_map=INDUSTRY_OCCUPATION_VALUES,
        )
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0, include_industries=True, top_n=1)
        county = data["counties"][0]
        assert county["industries"][0]["category"] == "Agriculture, forestry, fishing"
        assert county["occupations"][0]["category"] == "Management, business, science"


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatCensusSummary:
    def test_renders_expected_sections(self, monkeypatch):
        api = _load_census_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "acs_period": "2019-2023",
            "total_counties": 1,
            "counties": [
                {
                    "name": "Bernalillo County",
                    "state": "NM",
                    "fips": "35001",
                    "indicators": {"Median household income": "$55,000"},
                    "status": "success",
                }
            ],
            "status": "success",
        }
        out = api.format_census_summary(data)
        assert "Location: (34.5, -106.5)" in out
        assert "Total Counties: 1" in out
        assert "Bernalillo County, NM" in out
        assert "Median household income: $55,000" in out
        assert "U.S. Census Bureau ACS 5-Year Estimates" in out

    def test_empty_counties_message(self, monkeypatch):
        api = _load_census_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "acs_period": "2019-2023",
            "counties": [],
        }
        out = api.format_census_summary(data)
        assert "No counties found in the region of interest." in out

    def test_county_error_status_surfaced(self, monkeypatch):
        api = _load_census_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "acs_period": "2019-2023",
            "counties": [
                {
                    "name": "Bernalillo County",
                    "state": "NM",
                    "fips": "35001",
                    "indicators": {},
                    "status": "error",
                    "error_message": "No data returned",
                }
            ],
        }
        out = api.format_census_summary(data)
        assert "Error: No data returned" in out
