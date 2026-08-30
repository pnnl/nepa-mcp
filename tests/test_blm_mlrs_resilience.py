"""Resilience tests for mixed BLM MLRS source availability."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "blm_mlrs"
SIMPLE_GEOMETRY = {
    "rings": [[[-117.3, 38.0], [-117.1, 38.0], [-117.1, 38.2], [-117.3, 38.2], [-117.3, 38.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_blm_mlrs_res"):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_blm_mlrs_res_api",
            SERVER_DIR / "src" / "apis" / "blm_mlrs_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def test_one_failed_source_makes_combined_retrieval_degraded(monkeypatch, caplog):
    api = _load_api()
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)

    def query_object_ids(service_url, *_args, **kwargs):
        if service_url == api.MLRS_ROW_URL:
            raise RuntimeError("upstream URL and infrastructure detail")
        return [7] if "Authorized" in kwargs["where"] else []

    def query_features(service_url, *_args, **_kwargs):
        return ArcGISFeatureQueryResult(
            features=[
                {
                    "attributes": {
                        "OBJECTID": 7,
                        "CSE_NR": "NVNV106352249",
                        "CSE_DISP": "Authorized",
                        "BLM_PROD": "LEASES SEC 302 FEDERAL LAND POLICY AND MANAGEMENT ACT",
                    }
                }
            ],
            warnings=[],
        )

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", query_object_ids)
    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
    result = api.get_land_use_authorizations_in_roi(38.0, -117.0)
    output = api.format_land_use_authorizations_summary(result)

    assert result["retrieval_status"] == "degraded"
    assert result["listing_complete"] is False
    assert result["sources"][0]["retrieval_status"] == "unavailable"
    assert result["sources"][1]["retrieval_status"] == "ok"
    assert "infrastructure detail" not in output
    assert "infrastructure detail" not in caplog.text
    assert "not a no-hit finding" in output


def test_buffer_failure_marks_every_source_unavailable(monkeypatch, caplog):
    api = _load_api()
    monkeypatch.setattr(
        api.ArcGISService,
        "create_roi_buffer",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("sensitive upstream detail")),
    )
    result = api.get_locatable_operations_in_roi(38.0, -117.0)
    assert result["retrieval_status"] == "unavailable"
    assert result["listing_complete"] is False
    assert all(source["retrieval_status"] == "unavailable" for source in result["sources"])
    assert "sensitive upstream detail" not in caplog.text


def test_malformed_and_valid_features_degrade_retrieval(monkeypatch):
    api = _load_api()
    monkeypatch.setattr(api.ArcGISService, "query_object_ids", lambda *_a, **_k: [1, 2, 3])
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(
            features=[
                {},
                {"attributes": None},
                {"attributes": {"OBJECTID": 3, "CSE_NR": "NVNV106037549", "CSE_DISP": "Authorized"}},
            ],
            warnings=[],
        ),
    )
    result = api._query_source(
        api.ROW_SOURCE,
        geometry=SIMPLE_GEOMETRY,
        max_results=25,
        result_offset=0,
        source_dispositions=("Authorized",),
        where="1=1",
    )
    assert result["retrieval_status"] == "degraded"
    assert result["listing_complete"] is False
    assert result["returned_record_count"] == 1
    assert any("Skipped 2" in warning for warning in result["warnings"])
    assert any("omitted 2" in warning for warning in result["warnings"])


def test_malformed_only_is_unavailable_not_a_valid_empty_result(monkeypatch):
    api = _load_api()
    monkeypatch.setattr(api.ArcGISService, "query_object_ids", lambda *_a, **_k: [1])
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{"attributes": None}], warnings=[]),
    )
    result = api._query_source(
        api.ROW_SOURCE,
        geometry=SIMPLE_GEOMETRY,
        max_results=25,
        result_offset=0,
        source_dispositions=("Authorized",),
        where="1=1",
    )
    assert result["retrieval_status"] == "unavailable"
    assert result["listing_complete"] is False
    assert any("not a no-hit finding" in warning for warning in result["warnings"])
