"""MCP contract-to-formatter integration tests for all BLM MLRS tools."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "blm_mlrs"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_blm_mlrs_int"):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_blm_mlrs_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result():
    base = {
        "query_type": "roi",
        "retrieved_at": "2026-08-28T00:00:00Z",
        "retrieval_status": "ok",
        "listing_complete": True,
        "total_matching_feature_count": 1,
        "known_matching_feature_count": 1,
        "returned_feature_count": 1,
        "returned_unique_case_count": 1,
        "returned_record_count": 1,
        "screening_boundary": "Screening evidence only.",
        "sources": [
            {
                "source_title": "Verified BLM Source",
                "source_key": "example",
                "record_role": "authorization",
                "source_endpoint": "https://gis.blm.gov/nlsdb/rest/services/example/FeatureServer/0",
                "source_note": "Example source.",
                "retrieval_status": "ok",
                "listing_complete": True,
                "total_matching_feature_count": 1,
                "matching_counts_by_disposition": {"Authorized": 1},
                "selected_object_id_count": 1,
                "selected_object_ids": [1],
                "fetched_feature_count": 1,
                "raw_feature_count": 1,
                "returned_feature_count": 1,
                "returned_unique_case_count": 1,
                "returned_record_count": 1,
                "has_more": False,
                "next_result_offset": None,
                "records": [
                    {
                        "source_object_id": 1,
                        "source_object_ids": [1],
                        "case_serial_number": "NVNV106037549",
                        "source_disposition": "Authorized",
                        "product": "Solar Development Grant",
                        "date_quality": {},
                        "source_feature_count": 1,
                    }
                ],
                "warnings": [],
            }
        ],
    }
    base.update(
        {
            "center": {"latitude": 38.0, "longitude": -117.0},
            "buffer_miles": 25.0,
            "max_results_per_source": 25,
            "result_offset_per_source": 0,
        }
    )
    return base


async def _call(module, tool_name, arguments):
    async with Client(module.mcp) as client:
        response = await client.call_tool(tool_name, arguments)
    return response.data


async def _tool_names(module):
    async with Client(module.mcp) as client:
        tools = await client.list_tools()
    return {tool.name for tool in tools}


def test_server_exposes_only_the_three_retained_tools():
    module = _load_server()
    assert asyncio.run(_tool_names(module)) == {
        "get_blm_mlrs_land_use_authorizations_in_roi",
        "get_blm_mlrs_locatable_operations_in_roi",
        "get_blm_mlrs_energy_leases_in_roi",
    }


def test_all_roi_tools_execute_through_mcp(monkeypatch):
    module = _load_server()
    getter_names = {
        "get_blm_mlrs_land_use_authorizations_in_roi": "get_land_use_authorizations_in_roi",
        "get_blm_mlrs_locatable_operations_in_roi": "get_locatable_operations_in_roi",
        "get_blm_mlrs_energy_leases_in_roi": "get_energy_leases_in_roi",
    }
    for tool_name, getter_name in getter_names.items():
        monkeypatch.setattr(module, getter_name, lambda *_a, **_k: _result())
        output = asyncio.run(
            _call(
                module,
                tool_name,
                {
                    "latitude": 38.0,
                    "longitude": -117.0,
                    "buffer_miles": 25.0,
                    "max_results_per_source": 25,
                    "result_offset_per_source": 0,
                },
            )
        )
        assert "NVNV106037549" in output
        assert "Screening evidence only" in output
