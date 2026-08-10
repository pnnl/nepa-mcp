"""
Integration tests for the EPA AQS MCP server.

These load ``epa_aqs/server.py`` through a real ``fastmcp.Client`` and exercise
the full async tool -> api -> formatter -> Markdown path, with the ArcGIS buffer
service and the EPA AQS HTTP layer (``_query_aqs_api_sync``) mocked. Mirrors the
loading approach in ``test_mcp_contracts.py`` and ``test_usace_integration.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_aqs"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "get_epa_aqs_air_quality_monitors",
    "get_epa_aqs_annual_air_quality",
    "analyze_epa_aqs_air_quality_baseline",
}


def _set_test_credentials() -> None:
    os.environ.setdefault("EPA_AQS_EMAIL", "test@example.com")
    os.environ.setdefault("EPA_AQS_API_KEY", "test-aqs-key")


def _load_server():
    _set_test_credentials()
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_aqs_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_epa_aqs_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_aqs_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mocks(module, monitors=None, annual=None):
    """Patch the ArcGIS buffer and the EPA AQS HTTP layer on the loaded api module."""
    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)

    api = sys.modules.get("src.apis.aqs_api")
    assert api is not None, "aqs_api module should be imported by the server"
    api.RATE_LIMIT_SECONDS = 0.0

    monitors = monitors if monitors is not None else []
    annual = annual if annual is not None else []

    def fake_sync(endpoint, _params, max_retries=3):
        if "monitors" in endpoint:
            return {"Data": [dict(m) for m in monitors]}
        return {"Data": [dict(r) for r in annual]}

    api._query_aqs_api_sync = fake_sync


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        return await client.call_tool(tool_name, args)


def _text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class TestToolRegistration:
    def test_all_three_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestMonitorsTool:
    def test_returns_markdown_with_monitor(self):
        module = _load_server()
        _install_mocks(
            module,
            monitors=[
                {
                    "parameter": "PM2.5",
                    "local_site_name": "Downtown",
                    "state_code": "35",
                    "county_code": "001",
                    "site_number": "0001",
                    "first_year_of_data": "2010",
                    "last_year_of_data": "2024",
                }
            ],
        )
        result = asyncio.run(
            _call(
                module,
                "get_epa_aqs_air_quality_monitors",
                {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25, "year": 2024, "pollutants": ["PM2.5"]},
            )
        )
        text = _text(result)
        assert "EPA Air Quality Monitors" in text
        assert "Downtown" in text

    def test_empty_result_is_graceful(self):
        module = _load_server()
        _install_mocks(module, monitors=[])
        result = asyncio.run(
            _call(
                module,
                "get_epa_aqs_air_quality_monitors",
                {"latitude": 34.5, "longitude": -106.5, "pollutants": ["PM2.5"]},
            )
        )
        assert "No monitors found in the specified area." in _text(result)


class TestAnnualTool:
    def test_returns_naaqs_screening(self):
        module = _load_server()
        _install_mocks(
            module,
            annual=[
                {
                    "parameter_code": "88101",
                    "arithmetic_mean": "10.5",
                    "first_max_value": "24.0",
                    "primary_exceedance_count": "0",
                    "site_number": "001",
                }
            ],
        )
        result = asyncio.run(
            _call(
                module,
                "get_epa_aqs_annual_air_quality",
                {"latitude": 34.5, "longitude": -106.5, "begin_year": 2024, "end_year": 2024, "pollutants": ["PM2.5"]},
            )
        )
        text = _text(result)
        assert "Air Quality Baseline Assessment" in text
        assert "PM2.5" in text


class TestBaselineTool:
    def test_combines_monitors_and_annual(self):
        module = _load_server()
        _install_mocks(
            module,
            monitors=[
                {
                    "parameter": "PM2.5",
                    "local_site_name": "Downtown",
                    "state_code": "35",
                    "county_code": "001",
                    "site_number": "0001",
                }
            ],
            annual=[
                {
                    "parameter_code": "88101",
                    "arithmetic_mean": "10.5",
                    "site_number": "001",
                }
            ],
        )
        result = asyncio.run(
            _call(
                module,
                "analyze_epa_aqs_air_quality_baseline",
                {"latitude": 34.5, "longitude": -106.5, "pollutants": ["PM2.5"]},
            )
        )
        text = _text(result)
        assert "Comprehensive Air Quality Baseline Analysis" in text
        assert "EPA Air Quality Monitors" in text
        assert "Air Quality Baseline Assessment" in text


class TestInvalidPollutant:
    def test_unknown_pollutant_returns_error(self):
        module = _load_server()
        _install_mocks(module)
        result = asyncio.run(
            _call(
                module,
                "get_epa_aqs_air_quality_monitors",
                {"latitude": 34.5, "longitude": -106.5, "pollutants": ["Unobtainium"]},
            )
        )
        assert "No valid pollutants specified" in _text(result)


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        _install_mocks(module)
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_epa_aqs_air_quality_monitors", {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        _install_mocks(module)
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    "get_epa_aqs_air_quality_monitors",
                    {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0},
                )
            )
