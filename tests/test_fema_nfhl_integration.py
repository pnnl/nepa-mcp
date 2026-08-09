"""
Integration tests for the FEMA NFHL MCP server.

These load ``fema_nfhl/server.py`` through a real ``fastmcp.Client`` and
exercise the full tool -> api -> formatter -> Markdown path, with only the
network layer (``requests.get``) mocked. This mirrors the loading approach used
by the USACE integration suite.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "fema_nfhl"

FLOOD_ZONES_LAYER = 28
LEVEES_LAYER = 23
WATER_AREAS_LAYER = 32

_TOOL_NAMES = {
    "get_fema_nfhl_flood_zones_in_roi",
    "get_fema_nfhl_levees_in_roi",
    "get_fema_nfhl_water_areas_in_roi",
    "analyze_fema_nfhl_flood_hazard_screening",
}


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_fema_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_fema_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fema_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _features(attr_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"attributes": attrs} for attrs in attr_list]


def _install_requests_mock(module, layer_features):
    """Patch ``requests.get`` on the api module the server imported."""
    api = sys.modules.get("src.apis.fema_nfhl_api", module)

    def fake_get(url: str, *, params: dict[str, Any], timeout: int):
        layer_id = int(url.rstrip("/").split("/")[-2])
        attrs = layer_features.get(layer_id, [])
        return _FakeResponse({"exceededTransferLimit": False, "features": _features(attrs)})

    api.requests.get = fake_get


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
    def test_all_four_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestFloodZonesTool:
    def test_returns_markdown_with_zones(self):
        module = _load_server()
        _install_requests_mock(
            module,
            {FLOOD_ZONES_LAYER: [{"FLD_ZONE": "AE", "SFHA_TF": "T"}, {"FLD_ZONE": "X", "SFHA_TF": "F"}]},
        )
        result = asyncio.run(
            _call(
                module, "get_fema_nfhl_flood_zones_in_roi", {"latitude": 29.95, "longitude": -90.07, "radius_miles": 25}
            )
        )
        text = _text(result)
        assert "FEMA Flood Zones Analysis" in text
        assert "AE: 1 zones" in text

    def test_empty_result_is_graceful(self):
        module = _load_server()
        _install_requests_mock(module, {FLOOD_ZONES_LAYER: []})
        result = asyncio.run(
            _call(module, "get_fema_nfhl_flood_zones_in_roi", {"latitude": 29.95, "longitude": -90.07})
        )
        assert "Total: 0" in _text(result)


class TestLeveesTool:
    def test_returns_levee_count(self):
        module = _load_server()
        _install_requests_mock(module, {LEVEES_LAYER: [{"OBJECTID": 1}, {"OBJECTID": 2}]})
        result = asyncio.run(_call(module, "get_fema_nfhl_levees_in_roi", {"latitude": 29.95, "longitude": -90.07}))
        text = _text(result)
        assert "FEMA Levees" in text
        assert "Total: 2" in text


class TestWaterAreasTool:
    def test_returns_water_area_count(self):
        module = _load_server()
        _install_requests_mock(module, {WATER_AREAS_LAYER: [{"OBJECTID": 7}]})
        result = asyncio.run(
            _call(module, "get_fema_nfhl_water_areas_in_roi", {"latitude": 29.95, "longitude": -90.07})
        )
        text = _text(result)
        assert "FEMA Water Areas" in text
        assert "Total: 1" in text


class TestFloodRiskScreeningTool:
    def test_combines_all_sections(self):
        module = _load_server()
        _install_requests_mock(
            module,
            {
                FLOOD_ZONES_LAYER: [{"FLD_ZONE": "AE", "SFHA_TF": "T"}],
                LEVEES_LAYER: [{"OBJECTID": 1}],
                WATER_AREAS_LAYER: [{"OBJECTID": 2}],
            },
        )
        result = asyncio.run(
            _call(module, "analyze_fema_nfhl_flood_hazard_screening", {"latitude": 29.95, "longitude": -90.07})
        )
        text = _text(result)
        assert "FEMA NFHL Flood-Hazard Screening" in text
        assert "Hazard Level:" in text
        assert "Levee Systems" in text
        assert "Water Areas" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_fema_nfhl_flood_zones_in_roi", {"latitude": 999, "longitude": -90.07}))

    def test_zero_radius_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    "get_fema_nfhl_flood_zones_in_roi",
                    {"latitude": 29.95, "longitude": -90.07, "radius_miles": 0},
                )
            )
