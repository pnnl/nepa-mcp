"""
Performance / scaling tests for the tigerweb_counties API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: parsing stays bounded in time and sorting handles
large inputs. They do not hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "tigerweb_counties"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_counties_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_counties_perf_api", SERVER_DIR / "src" / "apis" / "counties_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_counties_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_features(api, monkeypatch, features):
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[]),
    )


class TestParsingThroughput:
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        features = [
            {"attributes": {"NAME": f"County {i}", "STATE": f"{i % 50:02d}", "GEOID": f"{i:05d}"}} for i in range(5000)
        ]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_counties_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["total_counties"] == 5000
        # Pure in-memory parse + sort of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_sorting_is_stable_and_bounded(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        # Reverse-ordered input to exercise the sort path.
        features = [
            {"attributes": {"NAME": f"County {5000 - i:04d}", "STATE": f"{(5000 - i) % 50:02d}"}} for i in range(5000)
        ]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_counties_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["total_counties"] == 5000
        states = [c["state"] for c in result["counties"]]
        assert states == sorted(states)
        assert elapsed < 1.0


class TestFormatterThroughput:
    def test_formatter_handles_large_lists(self, monkeypatch):
        api = _load_counties_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_counties": 3000,
            "counties": [{"name": f"County {i}", "state": f"{i % 50:02d}", "fips": f"{i:05d}"} for i in range(3000)],
            "warnings": [],
        }
        start = time.perf_counter()
        out = api.format_counties_summary(data)
        elapsed = time.perf_counter() - start
        assert "Total Counties: 3000" in out
        assert elapsed < 1.0
