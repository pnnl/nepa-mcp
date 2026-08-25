from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TOOL_COUNTS = {
    "blm": 3,
    "census": 1,
    "cfr": 7,
    "efh": 4,
    "epa_acres": 1,
    "epa_aqs": 3,
    "esa_ranges": 1,
    "fema_nfhl": 4,
    "gbif": 2,
    "gis": 3,
    "ipac": 1,
    "map_composer": 3,
    "nepa_assist": 1,
    "noaa": 1,
    "nrhp": 1,
    "padus": 1,
    "pcsrf": 4,
    "tigerweb_counties": 1,
    "tribal": 1,
    "usace": 4,
}

EXPECTED_TOOL_NAMES = {
    "blm": {
        "get_blm_land_use_plans_in_roi",
        "get_blm_national_monuments_in_roi",
        "get_blm_wilderness_areas_in_roi",
    },
    "census": {"get_acs_socioeconomic_indicators_in_roi"},
    "cfr": {
        "cfr_browse_structure",
        "cfr_compare_versions",
        "cfr_history",
        "cfr_resolve_citation",
        "cfr_resolve_executive_order",
        "cfr_resolve_fr_citation",
        "cfr_rulemaking",
    },
    "efh": {
        "get_efh_areas",
        "get_efh_hapc",
        "get_efh_hms_cps_groundfish",
        "get_efh_salmon",
    },
    "epa_acres": {"get_epa_acres_properties_in_roi"},
    "epa_aqs": {
        "analyze_epa_aqs_air_quality_baseline",
        "get_epa_aqs_air_quality_monitors",
        "get_epa_aqs_annual_air_quality",
    },
    "esa_ranges": {"get_esa_species_ranges_in_roi"},
    "fema_nfhl": {
        "analyze_fema_nfhl_flood_hazard_screening",
        "get_fema_nfhl_flood_zones_in_roi",
        "get_fema_nfhl_levees_in_roi",
        "get_fema_nfhl_water_areas_in_roi",
    },
    "gbif": {
        "get_gbif_species_list_by_county",
        "get_gbif_species_occurrences_in_roi",
    },
    "gis": {
        "calculate_roi_area",
        "get_roi_geojson",
        "summarize_roi_buffer",
    },
    "ipac": {"get_ipac_resources_in_roi"},
    "map_composer": {
        "compose_environmental_map",
        "export_all_layers_geojson",
        "list_available_layers",
    },
    "nepa_assist": {"analyze_nepa_assist_screening"},
    "noaa": {"get_noaa_critical_habitat_in_roi"},
    "nrhp": {"get_nrhp_properties_in_roi"},
    "padus": {"get_padus_protected_areas_in_roi"},
    "pcsrf": {
        "get_atlantic_salmon_efh_hapc_in_roi",
        "get_noaa_all_species_ranges_in_roi",
        "get_noaa_critical_habitat_20210904_in_roi",
        "get_pcsrf_projects_in_roi",
    },
    "tigerweb_counties": {"get_tigerweb_counties_in_roi"},
    "tribal": {"get_tribal_lands_in_roi"},
    "usace": {
        "analyze_usace_jurisdiction",
        "get_usace_regulatory_district",
        "get_usace_wetland_regions_in_roi",
        "get_usace_wetland_subregions_in_roi",
    },
}

GEO_SERVERS = tuple(server for server in EXPECTED_TOOL_COUNTS if server != "cfr")
SERVER_DIRS = {str((ROOT / server).resolve()) for server in EXPECTED_TOOL_COUNTS}


def _set_test_credentials() -> None:
    """Give credentialed tools deterministic test configuration."""
    os.environ.setdefault("CENSUS_API_KEY", "test-census-key")
    os.environ.setdefault("EPA_AQS_EMAIL", "test@example.com")
    os.environ.setdefault("EPA_AQS_API_KEY", "test-aqs-key")


def _clear_local_server_imports() -> None:
    """Each server has its own local `src` package; do not reuse another server's."""
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_contract_server_"):
            sys.modules.pop(module_name, None)

    sys.path[:] = [entry for entry in sys.path if entry not in SERVER_DIRS]


def _load_server(server_name: str):
    _set_test_credentials()
    _clear_local_server_imports()

    server_dir = ROOT / server_name
    server_path = server_dir / "server.py"
    module_name = f"_contract_server_{server_name}"
    sys.path.insert(0, str(server_dir))

    spec = importlib.util.spec_from_file_location(module_name, server_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


async def _list_tools(server_name: str):
    module = _load_server(server_name)
    async with Client(module.mcp) as client:
        return await client.list_tools()


@pytest.mark.parametrize(("server_name", "expected_count"), EXPECTED_TOOL_COUNTS.items())
def test_server_tool_discovery(server_name: str, expected_count: int) -> None:
    tools = asyncio.run(_list_tools(server_name))

    assert len(tools) == expected_count
    tool_names = [tool.name for tool in tools]
    assert len(tool_names) == len(set(tool_names))
    assert set(tool_names) == EXPECTED_TOOL_NAMES[server_name]
    assert all(not name.endswith("_tool") for name in tool_names)


@pytest.mark.parametrize("server_name", EXPECTED_TOOL_COUNTS)
def test_tool_schemas_are_agent_readable(server_name: str) -> None:
    tools = asyncio.run(_list_tools(server_name))

    for tool in tools:
        assert tool.description, f"{server_name}.{tool.name} needs a tool description"
        assert tool.annotations is not None
        if server_name == "map_composer" and tool.name in {
            "compose_environmental_map",
            "export_all_layers_geojson",
        }:
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.idempotentHint is False
            assert tool.annotations.openWorldHint is True
        elif server_name == "map_composer":
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.idempotentHint is True
            assert tool.annotations.openWorldHint is False
        else:
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.idempotentHint is True
            assert tool.annotations.openWorldHint is True

        schema = tool.inputSchema
        assert schema["type"] == "object"
        assert schema.get("additionalProperties") is False
        assert isinstance(schema.get("properties"), dict)

        for arg_name, arg_schema in schema["properties"].items():
            assert arg_schema.get("description"), f"{server_name}.{tool.name}.{arg_name} needs an argument description"

        output_schema = tool.outputSchema
        assert output_schema is not None
        assert output_schema["type"] == "object"
        assert output_schema["properties"]["result"]["type"] == "string"


@pytest.mark.parametrize("server_name", GEO_SERVERS)
def test_geo_tool_schemas_document_ranges_and_units(server_name: str) -> None:
    tools = asyncio.run(_list_tools(server_name))

    for tool in tools:
        properties = tool.inputSchema["properties"]
        if "latitude" not in properties:
            continue

        latitude_description = properties["latitude"]["description"].lower()
        longitude_description = properties["longitude"]["description"].lower()
        assert "wgs84" in latitude_description
        assert "-90" in latitude_description and "90" in latitude_description
        assert properties["latitude"]["minimum"] == -90
        assert properties["latitude"]["maximum"] == 90
        assert "wgs84" in longitude_description
        assert "-180" in longitude_description and "180" in longitude_description
        assert properties["longitude"]["minimum"] == -180
        assert properties["longitude"]["maximum"] == 180

        distance_name = "radius_miles" if "radius_miles" in properties else "buffer_miles"
        distance_description = properties[distance_name]["description"].lower()
        assert "mile" in distance_description
        assert "0.1" in distance_description and "100" in distance_description
        assert properties[distance_name]["minimum"] == 0.1
        assert properties[distance_name]["maximum"] == 100.0
        assert properties[distance_name]["default"] == 25.0


async def _assert_geo_validation_errors(server_name: str) -> None:
    module = _load_server(server_name)
    async with Client(module.mcp) as client:
        tools = await client.list_tools()

        for tool in tools:
            properties = tool.inputSchema["properties"]
            if "latitude" not in properties:
                continue

            distance_name = "radius_miles" if "radius_miles" in properties else "buffer_miles"

            with pytest.raises(ToolError) as invalid_latitude:
                await client.call_tool(
                    tool.name,
                    {
                        "latitude": 999,
                        "longitude": -120,
                        distance_name: 25.0,
                    },
                )
            assert "latitude" in str(invalid_latitude.value).lower()

            with pytest.raises(ToolError) as invalid_distance:
                await client.call_tool(
                    tool.name,
                    {
                        "latitude": 35,
                        "longitude": -120,
                        distance_name: 0,
                    },
                )
            assert distance_name in str(invalid_distance.value)


@pytest.mark.parametrize("server_name", GEO_SERVERS)
def test_geo_tools_reject_invalid_arguments_before_upstream_calls(server_name: str) -> None:
    asyncio.run(_assert_geo_validation_errors(server_name))
