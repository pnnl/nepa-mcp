"""
Integration tests for the IPaC MCP server.

These load ``ipac/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the ArcGIS buffer
layer and the ``requests.post`` call to IPaC mocked. This mirrors the loading
approach in ``test_usace_integration.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "ipac"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {"get_ipac_resources_in_roi"}


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as req_mod

            raise req_mod.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _sample_resources():
    return {
        "populationsBySid": {
            "POP1": {
                "population": {
                    "sid": {"val": "POP1"},
                    "optionalCommonName": "Whooping Crane",
                    "optionalScientificName": "Grus americana",
                    "listingStatusName": "Endangered",
                    "listingStatusCode": "E",
                    "criticalHabitat": "Final",
                },
                "optionalFederalRegisterCrithabStatus": {
                    "date": "1978-05-15",
                    "displayType": "Final Rule",
                    "url": "https://www.federalregister.gov/whooping-crane",
                },
            }
        },
        "migbirds": [
            {
                "phenologySpecies": {
                    "commonName": "Bald Eagle",
                    "scientificName": "Haliaeetus leucocephalus",
                    "code": "BAEA",
                },
                "level": {"name": "BCC Rangewide"},
                "bcc": True,
            }
        ],
        "wetlands": {
            "items": [
                {
                    "wetlandCode": "PEM1A",
                    "attributes": {"SYSTEM_NAME": "Palustrine", "CLASS_NAME": "Emergent"},
                }
            ]
        },
        "refuges": {"items": []},
        "fieldOffices": [{"officeName": "New Mexico ESFO", "officeCode": "NMESFO"}],
        "crithabs": [{"populationSid": {"val": "POP1"}, "type": "Final", "speciesInFootprint": True}],
    }


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_ipac_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_ipac_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ipac_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mocks(resources=None, status_code=200):
    """Patch the shared ArcGISService and requests.post used by the api module."""
    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.simplify_polygon_geometry = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)

    api = sys.modules.get("src.apis.ipac_api")
    payload = {"resources": resources if resources is not None else _sample_resources()}
    if api is not None:
        api.requests.post = lambda *_a, **_k: _FakeResponse(payload, status_code=status_code)


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
    def test_tool_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestResourcesTool:
    def test_returns_markdown_with_species(self, monkeypatch):
        module = _load_server()
        _install_mocks()
        result = asyncio.run(
            _call(
                module,
                "get_ipac_resources_in_roi",
                {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25},
            )
        )
        text = _text(result)
        assert "USFWS IPaC Resources within ROI" in text
        assert "Whooping Crane" in text
        assert "Bald Eagle" in text

    def test_empty_resources_is_graceful(self, monkeypatch):
        module = _load_server()
        empty = {
            "populationsBySid": {},
            "migbirds": [],
            "wetlands": {"items": []},
            "refuges": {"items": []},
            "fieldOffices": [],
            "crithabs": [],
        }
        _install_mocks(resources=empty)
        result = asyncio.run(_call(module, "get_ipac_resources_in_roi", {"latitude": 34.5, "longitude": -106.5}))
        text = _text(result)
        assert "Threatened/Endangered Species: 0" in text
        assert "Critical Habitat Units: 0" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_ipac_resources_in_roi", {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    "get_ipac_resources_in_roi",
                    {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0},
                )
            )
