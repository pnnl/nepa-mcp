"""Opt-in live FastMCP acceptance checks against direct BLM MLRS REST data.

Run explicitly with:

    RUN_BLM_MLRS_LIVE=1 ./.venv/bin/python -m pytest -q \
        tests/test_blm_mlrs_live_acceptance.py -s

Ordinary repository tests remain hermetic because this module is skipped unless
the environment variable is set.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import requests
from fastmcp import Client

from nepa_mcp_common.arcgis import ArcGISService

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "blm_mlrs"
RUN_LIVE = os.getenv("RUN_BLM_MLRS_LIVE") == "1"
pytestmark = pytest.mark.skipif(not RUN_LIVE, reason="set RUN_BLM_MLRS_LIVE=1 to run live BLM acceptance")

TONOPAH = {"latitude": 38.0692, "longitude": -117.2306, "buffer_miles": 25.0}
CARLSBAD = {"latitude": 32.4207, "longitude": -104.2288, "buffer_miles": 10.0}
DEFAULT_OPEN_DISPOSITIONS = ("Authorized", "Pending", "Interim")
SOURCE_URLS = {
    "Rights of Way": ("https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_LUA_ROW/FeatureServer/0"),
    "Leases, Permits, and Easements": (
        "https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_LUA_Leases_Permits_Esmts/FeatureServer/0"
    ),
    "Locatable Plans of Operations": (
        "https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_Locatable_Plans_Of_Operations/FeatureServer/0"
    ),
    "Locatable Notices": (
        "https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_Locatable_Notices/FeatureServer/0"
    ),
    "Geothermal Leases": (
        "https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_Geothermal_Leases/FeatureServer/0"
    ),
    "Oil and Gas Leases": (
        "https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_Oil_and_Gas_Leases/FeatureServer/0"
    ),
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_blm_mlrs_live"):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location("_blm_mlrs_live_server", SERVER_DIR / "server.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


async def _call(module, tool_name: str, arguments: dict[str, Any]) -> str:
    async with Client(module.mcp) as client:
        response = await client.call_tool(tool_name, arguments)
    assert isinstance(response.data, str)
    return response.data


def _call_tool(module, tool_name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(_call(module, tool_name, arguments))


def _geometry(location: dict[str, float]) -> dict[str, Any]:
    return ArcGISService.create_roi_buffer(
        location["latitude"],
        location["longitude"],
        location["buffer_miles"],
    )


def _direct_query(layer_url: str, data: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{layer_url}/query", data={"f": "json", **data}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    assert isinstance(payload, dict)
    assert "error" not in payload, payload.get("error")
    return payload


def _direct_ids_by_disposition(
    layer_url: str,
    geometry: dict[str, Any],
    dispositions: tuple[str, ...],
    additional_where: str = "1=1",
) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for disposition in dispositions:
        payload = _direct_query(
            layer_url,
            {
                "where": f"(CSE_DISP = '{disposition}') AND ({additional_where})",
                "geometry": json.dumps(geometry),
                "geometryType": "esriGeometryPolygon",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "returnIdsOnly": "true",
                "returnGeometry": "false",
            },
        )
        object_ids = payload.get("objectIds")
        if object_ids is None and "objectIds" in payload:
            object_ids = []
        assert isinstance(object_ids, list)
        result[disposition] = sorted({int(object_id) for object_id in object_ids})
    return result


def _direct_features(layer_url: str, object_ids: list[int], out_fields: str) -> list[dict[str, Any]]:
    if not object_ids:
        return []
    payload = _direct_query(
        layer_url,
        {
            "where": "1=1",
            "objectIds": ",".join(str(object_id) for object_id in object_ids),
            "outFields": out_fields,
            "returnGeometry": "false",
            "orderByFields": "OBJECTID ASC",
        },
    )
    features = payload.get("features")
    assert isinstance(features, list)
    return features


def _source_section(output: str, source_title: str) -> str:
    marker = f"### {source_title}\n"
    assert marker in output
    section = output.split(marker, 1)[1]
    return re.split(r"\n### |\n---\n", section, maxsplit=1)[0]


def _source_count(section: str) -> int:
    match = re.search(r"Matching source features before pagination: (\d+)", section)
    assert match is not None
    return int(match.group(1))


def _source_disposition_counts(section: str) -> dict[str, int]:
    match = re.search(r"Source dispositions before pagination: ([^\n]+)", section)
    assert match is not None
    return {name: int(value) for name, value in (item.split("=", 1) for item in match.group(1).split(", "))}


def _source_object_ids(section: str) -> list[int]:
    match = re.search(r"Selected object ID page: ([0-9][0-9, ]*)", section)
    if match is None:
        return []
    return [int(value.strip()) for value in match.group(1).split(",")]


def _assert_source_healthy(section: str) -> None:
    assert "Retrieval health: **ok**" in section
    assert "unavailable" not in section.lower()


def _combined_ids(ids_by_disposition: dict[str, list[int]]) -> list[int]:
    return sorted({object_id for object_ids in ids_by_disposition.values() for object_id in object_ids})


def test_tonopah_pending_authorizations_match_direct_counts_and_pages():
    module = _load_server()
    geometry = _geometry(TONOPAH)
    direct_open = {
        title: _direct_ids_by_disposition(SOURCE_URLS[title], geometry, DEFAULT_OPEN_DISPOSITIONS)
        for title in ("Rights of Way", "Leases, Permits, and Easements")
    }
    direct = {title: by_disposition["Pending"] for title, by_disposition in direct_open.items()}
    assert {title: len(object_ids) for title, object_ids in direct.items()} == {
        "Rights of Way": 17,
        "Leases, Permits, and Easements": 1,
    }

    default_output = _call_tool(
        module,
        "get_blm_mlrs_land_use_authorizations_in_roi",
        {**TONOPAH, "include_closed": False, "max_results_per_source": 1},
    )
    for title, by_disposition in direct_open.items():
        section = _source_section(default_output, title)
        _assert_source_healthy(section)
        assert _source_count(section) == len(_combined_ids(by_disposition))
        assert _source_disposition_counts(section) == {
            disposition: len(ids) for disposition, ids in by_disposition.items()
        }
        assert "Closed=" not in section

    common = {
        **TONOPAH,
        "source_dispositions": ["Pending"],
        "max_results_per_source": 10,
    }
    first = _call_tool(
        module,
        "get_blm_mlrs_land_use_authorizations_in_roi",
        {**common, "result_offset_per_source": 0},
    )
    second = _call_tool(
        module,
        "get_blm_mlrs_land_use_authorizations_in_roi",
        {**common, "result_offset_per_source": 10},
    )

    for title, direct_ids in direct.items():
        first_section = _source_section(first, title)
        second_section = _source_section(second, title)
        _assert_source_healthy(first_section)
        _assert_source_healthy(second_section)
        assert _source_count(first_section) == len(direct_ids)
        assert _source_disposition_counts(first_section) == {"Pending": len(direct_ids)}
        first_ids = _source_object_ids(first_section)
        second_ids = _source_object_ids(second_section)
        assert first_ids == direct_ids[:10]
        assert second_ids == direct_ids[10:20]
        assert set(first_ids).isdisjoint(second_ids)
        assert first_ids + second_ids == direct_ids
        assert "Closed" not in first_section
    print("Tonopah Pending: ROW=17; leases/permits/easements=1; two ID pages matched direct REST")


def test_tonopah_locatable_families_counts_and_future_expiration_match_direct():
    module = _load_server()
    geometry = _geometry(TONOPAH)
    titles = ("Locatable Plans of Operations", "Locatable Notices")
    direct = {
        title: _direct_ids_by_disposition(SOURCE_URLS[title], geometry, ("Authorized", "Pending")) for title in titles
    }
    assert {title: len(_combined_ids(by_disposition)) for title, by_disposition in direct.items()} == {
        "Locatable Plans of Operations": 27,
        "Locatable Notices": 36,
    }

    output = _call_tool(
        module,
        "get_blm_mlrs_locatable_operations_in_roi",
        {**TONOPAH, "max_results_per_source": 100, "result_offset_per_source": 0},
    )
    for title in titles:
        section = _source_section(output, title)
        direct_ids = _combined_ids(direct[title])
        _assert_source_healthy(section)
        assert _source_count(section) == len(direct_ids)
        assert _source_disposition_counts(section) == {
            disposition: len(ids) for disposition, ids in direct[title].items()
        }
        assert _source_object_ids(section) == direct_ids

    notice_ids = _combined_ids(direct["Locatable Notices"])
    notice_features = _direct_features(SOURCE_URLS["Locatable Notices"], notice_ids, "OBJECTID,EXP_DT")
    future_notice_ids = {
        int(feature["attributes"]["OBJECTID"])
        for feature in notice_features
        if feature.get("attributes", {}).get("EXP_DT")
        and datetime.fromtimestamp(feature["attributes"]["EXP_DT"] / 1000, tz=UTC) > datetime.now(UTC)
    }
    assert future_notice_ids
    notice_section = _source_section(output, "Locatable Notices")
    for object_id in future_notice_ids:
        if object_id in _source_object_ids(notice_section):
            record_line = next(line for line in notice_section.splitlines() if f"source object ID {object_id}" in line)
            assert "expiration date" in record_line
            assert "[expected_future]" in record_line
            assert "[implausible_future]" not in record_line
    print("Tonopah locatable operations: plans=27; notices=36; dispositions and future dates matched")


def test_carlsbad_oil_gas_count_and_first_page_match_direct():
    module = _load_server()
    geometry = _geometry(CARLSBAD)
    direct_by_disposition = _direct_ids_by_disposition(
        SOURCE_URLS["Oil and Gas Leases"],
        geometry,
        DEFAULT_OPEN_DISPOSITIONS,
    )
    direct_ids = _combined_ids(direct_by_disposition)
    assert len(direct_ids) == 272

    output = _call_tool(
        module,
        "get_blm_mlrs_energy_leases_in_roi",
        {
            **CARLSBAD,
            "lease_family": "oil_and_gas",
            "max_results_per_source": 25,
            "result_offset_per_source": 0,
        },
    )
    section = _source_section(output, "Oil and Gas Leases")
    _assert_source_healthy(section)
    assert _source_count(section) == len(direct_ids)
    assert _source_disposition_counts(section) == {
        disposition: len(ids) for disposition, ids in direct_by_disposition.items()
    }
    assert _source_object_ids(section) == direct_ids[:25]
    assert "Pagination: has_more=true | next_result_offset=25" in section
    print("Carlsbad oil and gas leases: total=272; first 25 object IDs matched direct REST")


def test_tonopah_energy_families_and_future_expirations_match_direct():
    module = _load_server()
    geometry = _geometry(TONOPAH)
    titles = ("Geothermal Leases", "Oil and Gas Leases")
    direct = {
        title: _direct_ids_by_disposition(SOURCE_URLS[title], geometry, DEFAULT_OPEN_DISPOSITIONS) for title in titles
    }
    output = _call_tool(
        module,
        "get_blm_mlrs_energy_leases_in_roi",
        {**TONOPAH, "max_results_per_source": 100, "result_offset_per_source": 0},
    )

    for title in titles:
        section = _source_section(output, title)
        direct_ids = _combined_ids(direct[title])
        _assert_source_healthy(section)
        assert _source_count(section) == len(direct_ids)
        assert _source_object_ids(section) == direct_ids[:100]

    geothermal_section = _source_section(output, "Geothermal Leases")
    assert _source_count(geothermal_section) > 0
    geothermal_ids = _combined_ids(direct["Geothermal Leases"])
    geothermal_features = _direct_features(
        SOURCE_URLS["Geothermal Leases"],
        geothermal_ids[:100],
        "OBJECTID,EXP_DT",
    )
    future_lease_ids = {
        int(feature["attributes"]["OBJECTID"])
        for feature in geothermal_features
        if feature.get("attributes", {}).get("EXP_DT")
        and datetime.fromtimestamp(feature["attributes"]["EXP_DT"] / 1000, tz=UTC) > datetime.now(UTC)
    }
    if future_lease_ids:
        assert "[expected_future]" in geothermal_section
        assert "expiration date" in geothermal_section
    print(
        "Tonopah energy leases: "
        + ", ".join(f"{title}={len(_combined_ids(direct[title]))}" for title in titles)
        + "; family separation and prospective expiration handling matched"
    )


def test_tool_specific_product_family_and_commodity_filters_match_direct():
    module = _load_server()
    geometry = _geometry(TONOPAH)

    product_where = "(UPPER(BLM_PROD) LIKE '%SOLAR%' OR UPPER(BLM_PROD) LIKE '%WIND%')"
    direct_row = _direct_ids_by_disposition(
        SOURCE_URLS["Rights of Way"],
        geometry,
        DEFAULT_OPEN_DISPOSITIONS,
        product_where,
    )
    land_output = _call_tool(
        module,
        "get_blm_mlrs_land_use_authorizations_in_roi",
        {
            **TONOPAH,
            "authorization_family": "right_of_way",
            "product_category": "solar_wind",
            "max_results_per_source": 100,
        },
    )
    land_section = _source_section(land_output, "Rights of Way")
    assert _source_count(land_section) == len(_combined_ids(direct_row))

    commodity_where = "UPPER(CMMDTY) LIKE '%LITHIUM%'"
    direct_notices = _direct_ids_by_disposition(
        SOURCE_URLS["Locatable Notices"],
        geometry,
        ("Authorized", "Pending"),
        commodity_where,
    )
    operations_output = _call_tool(
        module,
        "get_blm_mlrs_locatable_operations_in_roi",
        {
            **TONOPAH,
            "operation_family": "notice",
            "commodity_filter": "Lithium",
            "max_results_per_source": 100,
        },
    )
    notice_section = _source_section(operations_output, "Locatable Notices")
    assert _source_count(notice_section) == len(_combined_ids(direct_notices))
    assert "Locatable Plans of Operations" not in operations_output

    direct_geothermal = _direct_ids_by_disposition(
        SOURCE_URLS["Geothermal Leases"],
        geometry,
        DEFAULT_OPEN_DISPOSITIONS,
        "UPPER(CMMDTY) LIKE '%GEOTHERMAL%'",
    )
    energy_output = _call_tool(
        module,
        "get_blm_mlrs_energy_leases_in_roi",
        {
            **TONOPAH,
            "lease_family": "geothermal",
            "commodity_filter": "Geothermal",
            "max_results_per_source": 100,
        },
    )
    geothermal_section = _source_section(energy_output, "Geothermal Leases")
    assert _source_count(geothermal_section) == len(_combined_ids(direct_geothermal))
    assert "Oil and Gas Leases" not in energy_output
    print("Product, source-family, and commodity filters matched direct BLM REST counts")
