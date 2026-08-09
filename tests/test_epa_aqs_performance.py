"""
Performance / scaling tests for the EPA AQS API layer.

These are hermetic (HTTP + ArcGIS mocked) and assert algorithmic behavior at
larger synthetic record counts: monitor deduplication collapses many fragments
to few unique sites, NAAQS aggregation stays bounded in time, and parallel box
queries do not block. They do not hit the network, so they are deterministic in
CI.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BBOX = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}


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


class TestMonitorDeduplicationScaling:
    def test_many_duplicate_monitors_collapse(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        # 1000 records but only 5 distinct sites per param.
        def fake_sync(_endpoint, _params, max_retries=3):
            return {
                "Data": [{"state_code": "35", "county_code": "001", "site_number": f"{i % 5:04d}"} for i in range(1000)]
            }

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        monitors = asyncio.run(api.get_monitors_by_box(BBOX, "20240101", "20241231", ["88101"]))
        assert len(monitors) == 5


class TestNaaqsAggregationThroughput:
    def test_large_record_set_aggregates_quickly(self):
        api = _load_aqs_api()
        records = [
            {"parameter_code": "88101", "arithmetic_mean": str(5.0 + (i % 3)), "site_number": f"{i % 50}"}
            for i in range(10000)
        ]
        start = time.perf_counter()
        result = api.assess_naaqs_compliance(records)
        elapsed = time.perf_counter() - start
        assert result["PM2.5"]["num_records"] == 10000
        assert result["PM2.5"]["num_monitors"] == 50
        # Pure in-memory aggregation of 10k records should be well under a second.
        assert elapsed < 1.0

    def test_monitors_summary_formatting_bounded(self):
        api = _load_aqs_api()
        monitors = [
            {
                "parameter": "PM2.5",
                "local_site_name": f"Site {i}",
                "state_code": "35",
                "county_code": "001",
                "site_number": f"{i:04d}",
            }
            for i in range(5000)
        ]
        start = time.perf_counter()
        out = api.format_monitors_summary(monitors, 34.5, -106.5, 25.0)
        elapsed = time.perf_counter() - start
        assert "Total Monitors**: 5000" in out
        assert elapsed < 1.0


class TestParallelQueryScaling:
    def test_many_param_year_queries_complete(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def fake_sync(_endpoint, params, max_retries=3):
            return {"Data": [{"parameter_code": params["param"], "arithmetic_mean": "5.0"}]}

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        params = ["88101", "85101", "44201", "42602", "42401", "42101"]
        start = time.perf_counter()
        # 6 params x 5 years = 30 queries fanned out under a semaphore.
        data = asyncio.run(api.get_annual_data_by_box(BBOX, 2020, 2024, params))
        elapsed = time.perf_counter() - start
        assert len(data) == 30
        assert elapsed < 5.0
