"""
Integration tests for the GBIF MCP server.

These load ``gbif/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the HTTP layer
mocked: the GBIF occurrence REST API (``requests.get``) and the counties
ArcGIS query (``ArcGISService``). This mirrors ``test_usace_integration.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "gbif"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "get_gbif_species_occurrences_in_roi",
    "get_gbif_species_list_by_county",
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_gbif_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_gbif_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_gbif_int_server"] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _gbif_record(sci="Ursus arctos", iucn="EN", key=1):
    return {
        "key": key,
        "scientificName": sci,
        "vernacularName": "Grizzly Bear",
        "decimalLatitude": 34.5,
        "decimalLongitude": -106.5,
        "eventDate": "2020-05-01T00:00:00",
        "year": 2020,
        "month": 5,
        "iucnRedListCategory": iucn,
        "stateProvince": "",
        "county": "",
    }


def _install_mock_gbif(module, records):
    """Patch requests.get on the loaded gbif_api module to return one page."""
    api = sys.modules["src.apis.gbif_api"]

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"results": list(records), "endOfRecords": True})

    api.requests.get = fake_get


def _install_mock_counties(module, features):
    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.query_features = staticmethod(
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[])
    )


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        result = await client.call_tool(tool_name, args)
    return result


def _text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class TestToolRegistration:
    def test_both_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestOccurrencesTool:
    def test_returns_markdown_with_species(self):
        module = _load_server()
        _install_mock_gbif(module, [_gbif_record(sci="Ursus arctos", iucn="EN")])
        result = asyncio.run(
            _call(
                module,
                "get_gbif_species_occurrences_in_roi",
                {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25},
            )
        )
        text = _text(result)
        assert "GBIF Georeferenced Species Occurrences" in text
        assert "Ursus arctos" in text

    def test_empty_result_is_graceful(self):
        module = _load_server()
        _install_mock_gbif(module, [])
        result = asyncio.run(
            _call(module, "get_gbif_species_occurrences_in_roi", {"latitude": 34.5, "longitude": -106.5})
        )
        text = _text(result)
        assert "Total Occurrences: 0" in text


class TestSpeciesByCountyTool:
    def test_returns_markdown_with_county(self):
        module = _load_server()
        _install_mock_counties(
            module,
            [
                {
                    "attributes": {
                        "NAME": "Los Angeles County",
                        "STATE": "06",
                        "BASENAME": "Los Angeles",
                        "GEOID": "06037",
                    }
                }
            ],
        )
        _install_mock_gbif(module, [_gbif_record(sci="Sp A"), _gbif_record(sci="Sp B", key=2)])
        result = asyncio.run(_call(module, "get_gbif_species_list_by_county", {"latitude": 34.5, "longitude": -118.0}))
        text = _text(result)
        assert "GBIF Species Presence by County" in text
        assert "Los Angeles County, CA" in text

    def test_no_counties_is_graceful(self):
        module = _load_server()
        _install_mock_counties(module, [])
        result = asyncio.run(_call(module, "get_gbif_species_list_by_county", {"latitude": 34.5, "longitude": -118.0}))
        assert "Total Counties: 0" in _text(result)


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_gbif_species_occurrences_in_roi", {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    "get_gbif_species_occurrences_in_roi",
                    {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0},
                )
            )
