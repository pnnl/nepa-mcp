"""
Resilience tests for the EPA Superfund server.

Simulate upstream failures, error payloads, malformed records, transfer
limits, exhausted time budgets, and adversarial source text, and
assert that each source reports its own state while failures never read as
no-hit findings.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
import time
from pathlib import Path

import pytest
import requests

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService
from nepa_mcp_common.http import UpstreamServiceError

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_superfund"
POINT = {
    "attributes": {
        "ObjectId2": 1,
        "Site_EPA_ID": "NJD063157150",
        "Site_Name": "Bog Creek Farm",
        "SEMS_ID": 200397,
        "Status": "NPL Site",
    },
    "geometry": {"x": -74.16, "y": 40.15},
}


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_superfund_res_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location(
        "_epa_superfund_res_api", SERVER_DIR / "src" / "apis" / "superfund_api.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_superfund_res_api"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api(monkeypatch):
    module = _load_api()

    def query_object_ids(service_url, *_args, **_kwargs):
        features = ArcGISService.query_features(service_url).features
        field = "ObjectId2" if "Superfund_National" in service_url else "OBJECTID"
        return sorted(
            {
                f["attributes"][field]
                for f in features
                if isinstance(f, dict) and isinstance(f.get("attributes"), dict) and field in f["attributes"]
            }
        )

    monkeypatch.setattr(ArcGISService, "query_object_ids", query_object_ids)
    ArcGISService.create_roi_buffer = staticmethod(
        lambda *_a, **_k: {"rings": [[[-74.2, 40.1], [-74.1, 40.1], [-74.1, 40.2], [-74.2, 40.1]]]}
    )
    return module


def _by_layer(responses):
    def query(service_url, *_args, **_kwargs):
        value = next(v for key, v in responses.items() if key in service_url)
        if isinstance(value, Exception):
            raise value
        return value

    return staticmethod(query)


def _states(result):
    return {report.key: report.status for report in result["reports"]}


def test_one_failed_layer_does_not_hide_another(api):
    ArcGISService.query_features = _by_layer(
        {"Superfund_National": ArcGISFeatureQueryResult([POINT], [], False), "Site_Boundaries": RuntimeError("boom")}
    )
    result = api.get_epa_superfund_sites_in_roi(40.15, -74.16, 5)
    assert _states(result) == {"npl_points": "complete", "site_boundaries": "failed"}
    text = api.format_roi_results(result)
    assert "Bog Creek Farm" in text and "(lower bound)" in text and not result["data_unavailable"]


def test_all_sources_failing_is_unavailable(api):
    ArcGISService.query_features = _by_layer({"": requests.Timeout("slow")})
    result = api.search_epa_superfund_sites(query="bog")
    text = api.format_search_results(result)
    assert result["data_unavailable"] and "not a no-hit finding" in text and "No matching records" not in text


def test_malformed_and_truncated_features_are_reported(api):
    malformed = [{"attributes": None}, "junk", {"attributes": {"OBJECTID": 2}}]
    ArcGISService.query_features = _by_layer(
        {"Institutional_Control": ArcGISFeatureQueryResult(malformed, ["cap"], True)}
    )
    result = api.get_epa_superfund_institutional_controls("NJD063157150")
    report = result["reports"][0]
    assert report.status == "truncated" and report.record_count == 0
    assert "lower bounds" in report.note and "Skipped" in report.note
    text = api.format_institutional_controls(result)
    assert "Not determined for" not in text and "not evidence that no institutional controls apply" in text


def test_dmap_error_is_failed_and_empty_is_empty(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    monkeypatch.setattr(
        adapters, "get_json_rows", lambda *_a, **_k: (_ for _ in ()).throw(UpstreamServiceError("HTTP 500"))
    )
    failed = api.get_epa_superfund_contaminants("NJD063157150")
    assert _states(failed) == {"dmap_site": "failed"} and failed["data_unavailable"]
    assert "No contaminant associations" not in api.format_contaminants(failed)
    monkeypatch.setattr(adapters, "get_json_rows", lambda *_a, **_k: [])
    empty = api.get_epa_superfund_contaminants("NJD063157150")
    assert _states(empty) == {"dmap_site": "empty"} and any(
        "not in the Envirofacts SEMS site table" in w for w in empty["warnings"]
    )


def test_budget_exhaustion_skips_later_sources(api, monkeypatch):
    sources = sys.modules["src.core.sources"]
    ArcGISService.query_features = _by_layer({"": ArcGISFeatureQueryResult([], [], False)})
    monkeypatch.setattr(sources.Budget, "remaining", lambda self: 0.0)
    result = api.get_epa_superfund_institutional_controls("NJD063157150")
    assert _states(result) == {"ic_boundaries": "skipped"} and result["data_unavailable"]


def test_markup_in_identifier_fields_is_never_rendered(api, monkeypatch):
    monkeypatch.setattr(sys.modules["src.apis.adapters"], "get_json_rows", lambda *_a, **_k: [])
    hostile = copy.deepcopy(POINT)
    hostile["attributes"]["Site_EPA_ID"] = "NJD063157150**[Click](https://evil.example/x)**"
    frs = {
        "attributes": {
            "REGISTRY_ID": "[x](https://evil.example)",
            "PGM_SYS_ID": "NJD063157150",
            "PGM_SYS_ACRNM": "SEMS",
        }
    }
    ArcGISService.query_features = _by_layer(
        {
            "Superfund_National": ArcGISFeatureQueryResult([hostile], [], False),
            "FRS_INTERESTS": ArcGISFeatureQueryResult([frs], [], False),
            "": ArcGISFeatureQueryResult([], [], False),
        }
    )
    text = api.format_search_results(api.search_epa_superfund_sites(query="bog", inventory_scope="sems_candidates"))
    assert "evil.example" not in text


def test_adversarial_source_text_is_cleaned_in_bounded_time(api):
    normalization = sys.modules["src.core.normalization"]
    started = time.perf_counter()
    normalization.text("<" * 200_000)
    normalization.md("<a " * 50_000 + "[x](https://evil.example)", 300)
    assert time.perf_counter() - started < 9.0


def test_id_membership_change_keeps_original_selection_and_reports_partial(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    selections = iter([[1, 2], [2, 3]])
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **_k: next(selections))
    monkeypatch.setattr(
        ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult([{"attributes": {"ObjectId2": i}} for i in [2, 1]], []),
    )
    rows, report = adapters.query_layer(api.NPL_POINTS, where="1=1", budget=api.Budget(), max_features=10)
    assert [r["attributes"]["ObjectId2"] for r in rows] == [1, 2]
    assert report.status == "partial" and "changed during retrieval" in report.note


def test_missing_duplicate_and_unselected_features_are_not_silently_paged(api, monkeypatch):
    adapters = sys.modules["src.apis.adapters"]
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **_k: [1, 2, 3])
    monkeypatch.setattr(
        ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(
            [{"attributes": {"ObjectId2": i}} for i in [1, 1, 99]] + [{"attributes": None}], []
        ),
    )
    rows, report = adapters.query_layer(api.NPL_POINTS, where="1=1", budget=api.Budget(), max_features=10)
    assert [r["attributes"]["ObjectId2"] for r in rows] == [1]
    assert report.status == "partial" and "2 selected IDs were missing" in report.note
    assert "Skipped 3" in report.note


@pytest.mark.parametrize("failure", ["batch", "final_ids", "budget"])
def test_interrupted_id_first_retrieval_retains_earlier_features(api, monkeypatch, failure):
    adapters = sys.modules["src.apis.adapters"]
    monkeypatch.setattr(adapters, "ARCGIS_ID_BATCH_SIZE", 1)
    id_calls, feature_calls = [], []

    def ids(*_a, **_k):
        id_calls.append(True)
        if failure == "final_ids" and len(id_calls) == 2:
            raise requests.Timeout("private error detail")
        return [1, 2]

    def features(*_a, **kwargs):
        feature_calls.append(True)
        if failure == "batch" and len(feature_calls) == 2:
            raise requests.Timeout("private error detail")
        return ArcGISFeatureQueryResult([{"attributes": {"ObjectId2": int(kwargs["extra_params"]["objectIds"])}}], [])

    monkeypatch.setattr(ArcGISService, "query_object_ids", ids)
    monkeypatch.setattr(ArcGISService, "query_features", features)
    if failure == "budget":
        monkeypatch.setattr(api.Budget, "allows", lambda self, _seconds: not feature_calls)
    rows, report = adapters.query_layer(api.NPL_POINTS, where="1=1", budget=api.Budget(), max_features=10)
    assert rows and rows[0]["attributes"]["ObjectId2"] == 1
    assert report.status == "partial" and "private error detail" not in report.note
