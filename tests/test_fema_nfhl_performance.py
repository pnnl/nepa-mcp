"""
Performance / scaling tests for the FEMA NFHL API layer.

These are hermetic (``requests.get`` mocked) and assert algorithmic behavior at
larger synthetic feature counts: zone summaries aggregate correctly across many
records, pagination respects the max-features cap, and parsing stays bounded in
time. They do not hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "fema_nfhl"

FLOOD_ZONES_LAYER = 28


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def _load_fema_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_fema_perf_"):
            sys.modules.pop(module_name, None)
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    module_path = SERVER_DIR / "src" / "apis" / "fema_nfhl_api.py"
    spec = importlib.util.spec_from_file_location("_fema_perf_api", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fema_perf_api"] = module
    spec.loader.exec_module(module)
    return module


def _single_page(fema_api, monkeypatch, features):
    """Serve all features on one page (exceededTransferLimit False)."""

    def fake_get(url: str, *, params: dict[str, Any], timeout: int):
        return _FakeResponse({"exceededTransferLimit": False, "features": features})

    monkeypatch.setattr(fema_api.requests, "get", fake_get)


class TestSummaryAggregationScaling:
    def test_many_zones_aggregate_by_class(self, monkeypatch):
        fema_api = _load_fema_api()
        # 1000 records across 4 distinct zone classes; half are SFHA.
        classes = ["AE", "X", "VE", "D"]
        features = [
            {"attributes": {"FLD_ZONE": classes[i % 4], "SFHA_TF": "T" if i % 2 == 0 else "F"}} for i in range(1000)
        ]
        _single_page(fema_api, monkeypatch, features)
        result = fema_api.get_flood_zones(29.95, -90.07)
        assert result["total_zones"] == 1000
        assert sum(result["summary"]["zone_counts"].values()) == 1000
        assert len(result["summary"]["zone_counts"]) == 4
        assert result["summary"]["sfha_count"] == 500
        assert result["summary"]["sfha_percentage"] == 50.0


class TestPaginationCap:
    def test_max_features_truncates_and_warns(self, monkeypatch):
        fema_api = _load_fema_api()
        # Every page reports more available; the cap must stop pagination.
        page = {"attributes": {"OBJECTID": 1}}

        def fake_get(url: str, *, params: dict[str, Any], timeout: int):
            count = params["resultRecordCount"]
            return _FakeResponse({"exceededTransferLimit": True, "features": [dict(page) for _ in range(count)]})

        monkeypatch.setattr(fema_api.requests, "get", fake_get)
        result = fema_api._query_nfhl_layer_result(FLOOD_ZONES_LAYER, 29.95, -90.07, max_features=100)
        assert len(result.records) == 100
        assert result.truncated is True
        assert any("reached max_features" in w for w in result.warnings)


class TestParsingThroughput:
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        fema_api = _load_fema_api()
        features = [{"attributes": {"FLD_ZONE": "AE", "SFHA_TF": "T"}} for _ in range(5000)]
        _single_page(fema_api, monkeypatch, features)
        start = time.perf_counter()
        result = fema_api.get_flood_zones(29.95, -90.07)
        elapsed = time.perf_counter() - start
        assert result["total_zones"] == 5000
        # Pure in-memory parse of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_screening_bounded(self, monkeypatch):
        fema_api = _load_fema_api()
        features = [{"attributes": {"FLD_ZONE": "AE", "SFHA_TF": "T"}} for _ in range(1000)]
        _single_page(fema_api, monkeypatch, features)
        start = time.perf_counter()
        fema_api.analyze_flood_risk(29.95, -90.07)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0
