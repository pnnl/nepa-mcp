"""
Performance / scaling tests for the GIS/ROI API layer.

These are hermetic (ArcGIS buffer mocked) and assert that geometry parsing,
area calculation, and GeoJSON assembly stay bounded in time even for large
synthetic buffer rings. They do not hit the network, so they are deterministic
in CI.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_roi_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "gis"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_gis_perf_api", server_dir / "src" / "apis" / "roi_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_gis_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _dense_ring_geometry(vertices: int) -> dict:
    """Build a circular buffer polygon with ``vertices`` points."""
    ring = []
    for i in range(vertices):
        theta = 2 * math.pi * i / vertices
        ring.append([-106.5 + 0.5 * math.cos(theta), 34.5 + 0.5 * math.sin(theta)])
    ring.append(ring[0])  # close the ring
    return {"rings": [ring], "spatialReference": {"wkid": 4326}}


class TestAreaCalculationThroughput:
    def test_large_ring_area_is_fast(self, monkeypatch):
        api = _load_roi_api()
        geom = _dense_ring_geometry(50_000)
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: geom)
        start = time.perf_counter()
        sq_miles, acres = api.calculate_roi_area(34.5, -106.5, 25.0)
        elapsed = time.perf_counter() - start
        assert sq_miles > 0 and acres > 0
        # A 50k-vertex ring should parse well under a second.
        assert elapsed < 1.0


class TestGeojsonThroughput:
    def test_large_ring_geojson_is_bounded(self, monkeypatch):
        api = _load_roi_api()
        geom = _dense_ring_geometry(50_000)
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: geom)
        start = time.perf_counter()
        gj = api.get_roi_geojson(34.5, -106.5, 25.0)
        elapsed = time.perf_counter() - start
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"][1]["geometry"]["coordinates"][0]) == 50_001
        assert elapsed < 1.5

    def test_repeated_calls_are_bounded(self, monkeypatch):
        api = _load_roi_api()
        geom = _dense_ring_geometry(1000)
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: geom)
        start = time.perf_counter()
        for _ in range(200):
            api.get_roi_geojson(34.5, -106.5, 25.0)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0
