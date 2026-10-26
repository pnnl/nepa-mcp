"""
Performance / scaling tests for the EPA Superfund server.

Hermetic (network mocked) checks that grouping, sorting, parsing, and
formatting stay bounded at large synthetic record counts, and that 100-record
pages keep Markdown output size flat while totals stay complete.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_superfund"


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_superfund_perf_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location(
        "_epa_superfund_perf_api", SERVER_DIR / "src" / "apis" / "superfund_api.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_superfund_perf_api"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api():
    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: {"rings": []})
    return _load_api()


def _polygons(count):
    features = []
    for index in range(count):
        x, y = -100 + (index % 100) * 0.01, 40 + (index // 100) * 0.01
        ring = [[x, y], [x + 0.005, y], [x + 0.005, y + 0.005], [x, y + 0.005], [x, y]]
        features.append(
            {
                "attributes": {
                    "OBJECTID": index,
                    "EPA_ID": f"TXD{index // 2:09d}",
                    "SITE_NAME": f"SITE {index // 2}",
                    "NPL_STATUS_CODE": "F",
                },
                "geometry": {"rings": [ring]},
            }
        )
    return features


def _roi(api, count, monkeypatch):
    polygons = _polygons(count)
    monkeypatch.setattr(
        ArcGISService, "query_object_ids", lambda url, *_a, **_k: list(range(count)) if "Site_Boundaries" in url else []
    )
    ArcGISService.query_features = staticmethod(
        lambda url, *a, **k: ArcGISFeatureQueryResult(
            [polygons[int(i)] for i in k["extra_params"]["objectIds"].split(",")], [], False
        )
    )
    return api.get_epa_superfund_sites_in_roi(40.2, -99.5, 50)


def test_roi_grouping_and_sorting_stay_bounded(api, monkeypatch):
    monkeypatch.setattr(api, "ROI_MAX_FEATURES", 5000)
    started = time.perf_counter()
    result = _roi(api, 5000, monkeypatch)
    assert time.perf_counter() - started < 15.0
    assert len(result["sites"]) == 2500
    distances = [site["distance_miles"] for site in result["sites"]]
    assert distances == sorted(distances)


def test_page_output_size_is_flat_while_totals_stay_complete(api, monkeypatch):
    small = api.format_roi_results(_roi(api, 400, monkeypatch))
    large = api.format_roi_results(_roi(api, 4000, monkeypatch))
    assert "of 200)" in small and "of 2000)" in large
    assert len(large) < len(small) * 1.2


def test_contaminant_filtering_scales(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    rows = [
        {
            "fk_site_id": "0200397",
            "preferred_contaminant_name": f"CHEM {i}",
            "media_name": ("Soil", "Groundwater")[i % 2],
            "operable_unit_num": f"{i % 9:02d}",
            "action_name": "Record of Decision",
            "type_code": "RO",
            "seq": i,
        }
        for i in range(5000)
    ]

    def rows_for(url, **_kwargs):
        return rows if "contaminants" in url else [{"site_id": "0200397", "epa_id": "NJD063157150", "name": "BOG"}]

    monkeypatch.setattr(adapters, "get_json_rows", rows_for)
    started = time.perf_counter()
    result = api.get_epa_superfund_contaminants("NJD063157150", media="Groundwater")
    text = api.format_contaminants(result)
    assert time.perf_counter() - started < 3.0
    assert len(result["records"]) == 2500 and "of 2500)" in text
