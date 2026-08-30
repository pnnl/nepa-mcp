"""Unit tests for BLM MLRS parsing, source selection, and pagination."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "blm_mlrs"
SIMPLE_GEOMETRY = {
    "rings": [[[-117.3, 38.0], [-117.1, 38.0], [-117.1, 38.2], [-117.3, 38.2], [-117.3, 38.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_blm_mlrs_unit"):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_blm_mlrs_unit_api",
            SERVER_DIR / "src" / "apis" / "blm_mlrs_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def _attrs(serial: str = "NVNV106037549", **overrides):
    values = {
        "OBJECTID": 1,
        "CSE_NR": serial,
        "LEG_CSE_NR": "NVN 012345",
        "CSE_NAME": "Crescent Dunes Solar Plant",
        "BLM_PROD": "Solar Development Grant",
        "CSE_TYPE_NR": "285003",
        "CSE_DISP": "Authorized",
        "CSE_DISP_DT": 1416614340000,
        "CMMDTY": "SOLAR ENERGY FACILITIES",
        "ADMIN_STATE": "NV",
        "GEO_STATE": "NV",
        "RCRD_ACRS": 2094.27,
        "SRC": "MIGRATE",
        "QLTY": "8.3: Map to entire section Freeform (RENDER)",
        "Created": 1687444870000,
        "Modified": 1787321142000,
        "CSE_JURIS_DESC": "Tonopah Field Office",
    }
    values.update(overrides)
    return values


def test_parse_record_preserves_source_semantics_and_normalizes_quality():
    api = _load_api()
    record = api._parse_record(_attrs(), api.ROW_SOURCE)

    assert record["case_family"] == "right_of_way"
    assert record["record_role"] == "authorization"
    assert record["case_serial_number"] == "NVNV106037549"
    assert record["source_disposition"] == "Authorized"
    assert record["geometry_quality_code"] == "8.3"
    assert record["geometry_quality"] == "mapped_to_section"
    assert record["source_case_acres"] == 2094.27
    assert record["jurisdiction"] == "Tonopah Field Office"
    assert record["date_quality"]["disposition_date"] == "plausible"
    assert "case_name" not in record
    assert "CUST_NM_SEC" not in record
    assert "CSE_META" not in record
    assert "SF_ID" not in record


@pytest.mark.parametrize(
    ("raw", "code", "category"),
    [
        ("0: direct", "0", "direct_plss_match"),
        ("4.1: calculated", "4.1", "calculated_plss_match"),
        ("8.2", "8.2", "mapped_to_section"),
        ("15; mixed", "15", "mixed_mapped_unmapped"),
        ("25 mapped", "25", "mapped_to_county"),
        ("100: edited", "100", "staff_improved_geometry"),
        ("unexpected", None, "unknown"),
    ],
)
def test_geometry_quality_groups(raw, code, category):
    api = _load_api()
    assert api._normalize_geometry_quality(raw) == (code, category)


def test_implausible_future_date_is_preserved_and_flagged():
    api = _load_api()
    value, quality = api._parse_epoch_millis(33245078338000)
    assert value.startswith("3023-")
    assert quality == "implausible_future"


def test_future_expiration_date_is_expected_not_implausible():
    api = _load_api()
    future = datetime.now(UTC) + timedelta(days=730)
    value, quality = api._parse_epoch_millis(future.timestamp() * 1000, "expiration_date")
    assert value is not None
    assert quality == "expected_future"


def test_duplicate_features_are_collapsed_by_case_and_document():
    api = _load_api()
    first = api._parse_record(_attrs(), api.ROW_SOURCE)
    second = api._parse_record(_attrs(), api.ROW_SOURCE)
    assert first is not None and second is not None
    collapsed = api._collapse_records([first, second])
    assert len(collapsed) == 1
    assert collapsed[0]["source_feature_count"] == 2


def test_source_window_slices_complete_object_ids_and_reports_more(monkeypatch):
    api = _load_api()
    captured = {}

    def query_object_ids(*args, **kwargs):
        captured["id_args"] = args
        captured["id_kwargs"] = kwargs
        return list(range(1, 81))

    def query_features(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        object_ids = [int(value) for value in kwargs["extra_params"]["objectIds"].split(",")]
        features = [
            {"attributes": _attrs(f"NVNV{object_id:09d}", OBJECTID=object_id)} for object_id in reversed(object_ids)
        ]
        return ArcGISFeatureQueryResult(features=features, warnings=[], truncated=False)

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", query_object_ids)
    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
    result = api._query_source(
        api.ROW_SOURCE,
        geometry=SIMPLE_GEOMETRY,
        max_results=3,
        result_offset=75,
        source_dispositions=("Authorized",),
        where="1=1",
    )

    assert captured["id_kwargs"]["where"] == "(CSE_DISP = 'Authorized')"
    assert captured["id_kwargs"]["max_attempts"] == 2
    assert captured["kwargs"]["extra_params"]["objectIds"] == "76,77,78"
    assert captured["kwargs"]["max_attempts"] == 2
    assert captured["kwargs"]["max_features"] == 3
    assert captured["kwargs"]["page_size"] == 3
    assert result["total_matching_feature_count"] == 80
    assert result["matching_counts_by_disposition"] == {"Authorized": 80}
    assert result["returned_record_count"] == 3
    assert [record["source_object_id"] for record in result["records"]] == [76, 77, 78]
    assert result["has_more"] is True
    assert result["next_result_offset"] == 78
    assert result["retrieval_status"] == "ok"
    assert result["listing_complete"] is False


def test_include_closed_changes_authorization_source_filter(monkeypatch):
    api = _load_api()
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    seen = []

    def query_object_ids(*args, **kwargs):
        seen.append(kwargs["where"])
        return []

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", query_object_ids)
    api.get_land_use_authorizations_in_roi(38.0, -117.0, include_closed=False)
    assert all("Closed" not in where for where in seen)
    assert len(seen) == 6
    seen.clear()
    api.get_land_use_authorizations_in_roi(38.0, -117.0, include_closed=True)
    assert len(seen) == 8
    assert sum("Closed" in where for where in seen) == 2


def test_exact_disposition_overrides_include_closed(monkeypatch):
    api = _load_api()
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    seen = []

    def query_object_ids(*args, **kwargs):
        seen.append(kwargs["where"])
        return []

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", query_object_ids)
    api.get_energy_leases_in_roi(
        38.0,
        -117.0,
        include_closed=True,
        source_dispositions=["Pending"],
    )
    assert len(seen) == 2
    assert all("Pending" in where and "Closed" not in where for where in seen)


def test_default_authorization_page_prioritizes_pending_then_interim(monkeypatch):
    api = _load_api()

    def query_object_ids(*_args, **kwargs):
        where = kwargs["where"]
        if "Pending" in where:
            return [30]
        if "Interim" in where:
            return [20]
        if "Authorized" in where:
            return [10]
        return []

    captured = {}

    def query_features(*_args, **kwargs):
        captured["objectIds"] = kwargs["extra_params"]["objectIds"]
        return ArcGISFeatureQueryResult(
            features=[
                {"attributes": _attrs("NVNV000000030", OBJECTID=30, CSE_DISP="Pending")},
                {"attributes": _attrs("NVNV000000020", OBJECTID=20, CSE_DISP="Interim")},
            ],
            warnings=[],
        )

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", query_object_ids)
    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
    result = api._query_source(
        api.ROW_SOURCE,
        geometry=SIMPLE_GEOMETRY,
        max_results=2,
        result_offset=0,
        source_dispositions=("Authorized", "Pending", "Interim"),
        where="1=1",
        prefer_pending_interim=True,
    )

    assert captured["objectIds"] == "30,20"
    assert result["selected_object_ids"] == [30, 20]
    assert result["retrieval_status"] == "ok"
    assert result["listing_complete"] is False
    assert result["has_more"] is True


def test_tool_specific_filters_select_sources_and_build_bounded_where(monkeypatch):
    api = _load_api()
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    calls = []

    def query_object_ids(service_url, *_args, **kwargs):
        calls.append((service_url, kwargs["where"]))
        return []

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", query_object_ids)
    result = api.get_locatable_operations_in_roi(
        38.0,
        -117.0,
        source_dispositions=["Pending"],
        operation_family="notice",
        commodity_filter="Lithium",
    )
    assert len(calls) == 1
    assert calls[0][0] == api.MLRS_LOCATABLE_NOTICES_URL
    assert "UPPER(CMMDTY) LIKE '%LITHIUM%'" in calls[0][1]
    assert result["source_counts_by_family"] == {"locatable_notice": 0}


def test_formatter_keeps_unavailable_distinct_from_empty():
    api = _load_api()
    result = api._finish_result(
        {
            "query_type": "roi",
            "center": {"latitude": 38.0, "longitude": -117.0},
            "buffer_miles": 25.0,
            "max_results_per_source": 25,
            "result_offset_per_source": 0,
            "retrieved_at": "2026-08-28T00:00:00Z",
            "screening_boundary": "Screen only.",
        },
        [api._unavailable_source(api.ROW_SOURCE, "Timed out; not a no-hit finding.")],
    )
    output = api.format_land_use_authorizations_summary(result)
    assert "Retrieval health:** unavailable" in output
    assert "Listing complete:** false" in output
    assert "No absence finding can be made" in output
    assert "No matching geospatially represented records" not in output
