"""
Unit tests for the EPA AQS API layer (``epa_aqs/src/apis/aqs_api.py``).

These exercise the pure parsing / statistics / formatting logic plus the async
box-query helpers with the HTTP layer (``_query_aqs_api_sync``) and the ArcGIS
buffer service mocked, so no network calls are made. They follow the same
dynamic per-server import pattern used by ``test_epa_aqs_screening.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_aqs_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_test_epa_"):
            sys.modules.pop(module_name, None)

    server_dir = ROOT / "epa_aqs"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    module_path = server_dir / "src" / "apis" / "aqs_api.py"
    spec = importlib.util.spec_from_file_location("_test_epa_aqs_api", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_epa_aqs_api"] = module
    spec.loader.exec_module(module)
    return module


def _set_creds(monkeypatch):
    monkeypatch.setenv("EPA_AQS_EMAIL", "test@example.com")
    monkeypatch.setenv("EPA_AQS_API_KEY", "test-aqs-key")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_returns_email_and_key(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        email, key = api.get_aqs_credentials()
        assert email == "test@example.com"
        assert key == "test-aqs-key"

    def test_missing_credentials_raise_value_error(self, monkeypatch):
        api = _load_aqs_api()
        monkeypatch.delenv("EPA_AQS_EMAIL", raising=False)
        monkeypatch.delenv("EPA_AQS_API_KEY", raising=False)
        import pytest

        with pytest.raises(ValueError):
            api.get_aqs_credentials()


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------


class TestBoundingBox:
    def test_extent_derived_from_buffer(self, monkeypatch):
        api = _load_aqs_api()
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
        bbox = api.calculate_bounding_box(34.5, -106.5, 25.0)
        assert bbox["minlat"] == 34.0
        assert bbox["maxlat"] == 35.0
        assert bbox["minlon"] == -107.0
        assert bbox["maxlon"] == -106.0


# ---------------------------------------------------------------------------
# Date ranges
# ---------------------------------------------------------------------------


class TestSplitDateRanges:
    def test_single_year(self):
        api = _load_aqs_api()
        assert api.split_date_ranges(2024, 2024) == [("20240101", "20241231")]

    def test_multi_year(self):
        api = _load_aqs_api()
        ranges = api.split_date_ranges(2022, 2024)
        assert ranges == [
            ("20220101", "20221231"),
            ("20230101", "20231231"),
            ("20240101", "20241231"),
        ]


# ---------------------------------------------------------------------------
# NAAQS screening
# ---------------------------------------------------------------------------


class TestNaaqsCompliance:
    def test_annual_standard_above(self, monkeypatch):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [
                {
                    "parameter_code": "88101",  # PM2.5 (annual standard 9.0)
                    "arithmetic_mean": "10.5",
                    "first_max_value": "24.0",
                    "primary_exceedance_count": "0",
                    "site_number": "001",
                }
            ]
        )
        assert result["PM2.5"]["comparison_status"] == "above"
        assert result["PM2.5"]["exceeds_standard"] is True
        assert result["PM2.5"]["exceedance_percent"] > 0

    def test_annual_standard_at_or_below(self, monkeypatch):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [
                {
                    "parameter_code": "88101",
                    "arithmetic_mean": "5.0",
                    "first_max_value": "12.0",
                    "primary_exceedance_count": "0",
                    "site_number": "001",
                }
            ]
        )
        assert result["PM2.5"]["comparison_status"] == "at_or_below"
        assert result["PM2.5"]["exceeds_standard"] is False
        assert result["PM2.5"]["exceedance_percent"] == 0

    def test_short_duration_standard_not_evaluated(self):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [
                {
                    "parameter_code": "44201",  # Ozone (8-hour only)
                    "arithmetic_mean": "0.030",
                    "first_max_value": "0.080",
                    "primary_exceedance_count": "0",
                    "site_number": "002",
                }
            ]
        )
        assert result["Ozone"]["comparison_status"] == "not_evaluated"
        assert result["Ozone"]["exceeds_standard"] is None

    def test_averages_across_records_and_counts_monitors(self):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [
                {"parameter_code": "88101", "arithmetic_mean": "8.0", "site_number": "001"},
                {"parameter_code": "88101", "arithmetic_mean": "12.0", "site_number": "002"},
            ]
        )
        assert result["PM2.5"]["avg_annual_mean"] == 10.0
        assert result["PM2.5"]["num_records"] == 2
        assert result["PM2.5"]["num_monitors"] == 2

    def test_non_numeric_means_are_skipped(self):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [
                {"parameter_code": "88101", "arithmetic_mean": "bad", "site_number": "001"},
            ]
        )
        # No parseable mean => pollutant is dropped from the comparison.
        assert "PM2.5" not in result

    def test_empty_input_returns_empty(self):
        api = _load_aqs_api()
        assert api.assess_naaqs_compliance([]) == {}


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_monitors_summary_renders_markdown(self):
        api = _load_aqs_api()
        out = api.format_monitors_summary(
            [
                {
                    "parameter_code": "44201",
                    "parameter_name": "Ozone",
                    "local_site_name": "Kennewick",
                    "state_code": "53",
                    "county_code": "005",
                    "site_number": "0003",
                    "poc": 1,
                    "open_date": "2015-06-10",
                    "close_date": None,
                }
            ],
            34.5,
            -106.5,
            25.0,
        )
        assert "EPA Air Quality Monitors" in out
        assert "Total Monitors**: 1" in out
        assert "### Ozone" in out
        assert "Kennewick" in out
        assert "POC: 1" in out
        assert "Active: 2015-06-10 - Present" in out
        assert "Unknown" not in out

    def test_monitors_summary_maps_parameter_code_when_name_is_absent(self):
        api = _load_aqs_api()
        out = api.format_monitors_summary(
            [
                {
                    "parameter_code": "88101",
                    "state_code": "53",
                    "county_code": "005",
                    "site_number": "0003",
                    "first_year_of_data": "2010",
                    "last_year_of_data": "2024",
                }
            ],
            34.5,
            -106.5,
            25.0,
        )
        assert "### PM2.5" in out
        assert "Active: 2010 - 2024" in out

    def test_monitors_summary_handles_empty(self):
        api = _load_aqs_api()
        out = api.format_monitors_summary([], 34.5, -106.5, 25.0)
        assert "No monitors found in the specified area." in out

    def test_air_quality_summary_handles_no_compliance(self):
        api = _load_aqs_api()
        out = api.format_air_quality_summary([], {}, 34.5, -106.5, 25.0, 2024, 2024)
        assert "No air quality data available for NAAQS screening comparison." in out

    def test_air_quality_summary_reports_above_status(self):
        api = _load_aqs_api()
        compliance = {
            "PM2.5": {
                "avg_annual_mean": 10.5,
                "max_value": 24.0,
                "naaqs_standard": 9.0,
                "naaqs_units": "µg/m³",
                "naaqs_averaging_time": "Annual Mean",
                "exceeds_standard": True,
                "comparison_status": "above",
                "comparison_note": "Annual mean screening comparison.",
                "exceedance_percent": 16.7,
                "total_exceedance_days": 0,
                "num_records": 1,
                "num_monitors": 1,
            }
        }
        out = api.format_air_quality_summary([{"parameter_code": "88101"}], compliance, 34.5, -106.5, 25.0, 2024, 2024)
        assert "Air Quality Baseline Assessment" in out
        assert "above selected standard value" in out.lower()
        assert "Pollutants above selected annual NAAQS value**: 1" in out


# ---------------------------------------------------------------------------
# Async box queries (HTTP layer mocked)
# ---------------------------------------------------------------------------


class TestAsyncBoxQueries:
    def test_monitors_preserve_pollutants_at_same_site(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def fake_sync(_endpoint, params, max_retries=3):
            parameter_code = params["param"]
            return {
                "Data": [
                    {
                        "state_code": "35",
                        "county_code": "001",
                        "site_number": "0001",
                        "parameter_code": parameter_code,
                        "parameter_name": {"88101": "PM2.5", "44201": "Ozone"}[parameter_code],
                    }
                ]
            }

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        bbox = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}
        monitors = asyncio.run(api.get_monitors_by_box(bbox, "20240101", "20241231", ["88101", "44201"]))

        assert len(monitors) == 2
        assert {monitor["parameter_code"] for monitor in monitors} == {"88101", "44201"}

        summary = api.format_monitors_summary(monitors, 34.5, -106.5, 25.0)
        assert "### PM2.5" in summary
        assert "### Ozone" in summary

    def test_monitors_preserve_pocs_at_same_site_and_pollutant(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def fake_sync(_endpoint, _params, max_retries=3):
            return {
                "Data": [
                    {
                        "state_code": "35",
                        "county_code": "001",
                        "site_number": "0001",
                        "parameter_code": "88101",
                        "parameter_name": "PM2.5",
                        "poc": 1,
                    },
                    {
                        "state_code": "35",
                        "county_code": "001",
                        "site_number": "0001",
                        "parameter_code": "88101",
                        "parameter_name": "PM2.5",
                        "poc": 2,
                    },
                ]
            }

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        bbox = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}
        monitors = asyncio.run(api.get_monitors_by_box(bbox, "20240101", "20241231", ["88101"]))

        assert len(monitors) == 2
        assert {monitor["poc"] for monitor in monitors} == {1, 2}

        summary = api.format_monitors_summary(monitors, 34.5, -106.5, 25.0)
        assert "POC: 1" in summary
        assert "POC: 2" in summary

    def test_monitors_dedup_same_aqs_monitor(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        monitor = {
            "state_code": "35",
            "county_code": "001",
            "site_number": "0001",
            "parameter_code": "88101",
            "parameter_name": "PM2.5",
            "poc": 1,
        }

        def fake_sync(_endpoint, _params, max_retries=3):
            return {"Data": [dict(monitor), dict(monitor)]}

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        bbox = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}
        monitors = asyncio.run(api.get_monitors_by_box(bbox, "20240101", "20241231", ["88101"]))

        assert len(monitors) == 1

    def test_annual_data_aggregates_all_records(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def fake_sync(_endpoint, params, max_retries=3):
            return {"Data": [{"parameter_code": params["param"], "arithmetic_mean": "5.0"}]}

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        bbox = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}
        data = asyncio.run(api.get_annual_data_by_box(bbox, 2023, 2024, ["88101", "85101"]))
        # 2 params x 2 years = 4 records.
        assert len(data) == 4

    def test_one_param_failure_does_not_abort_others(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def fake_sync(_endpoint, params, max_retries=3):
            if params["param"] == "85101":
                raise api.AQSAPIError("boom")
            return {"Data": [{"state_code": "35", "county_code": "001", "site_number": "0001"}]}

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        bbox = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}
        monitors = asyncio.run(api.get_monitors_by_box(bbox, "20240101", "20241231", ["88101", "85101"]))
        # Failing param is skipped; the good one still returns.
        assert len(monitors) == 1
