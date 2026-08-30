"""Security and input-boundary tests for the BLM MLRS MCP server."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "blm_mlrs"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_blm_mlrs_sec"):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_blm_mlrs_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "values",
    [
        (91, -117, 25),
        (-91, -117, 25),
        (38, 181, 25),
        (38, -181, 25),
        (38, -117, 0),
        (38, -117, 101),
        (float("nan"), -117, 25),
        (38, float("inf"), 25),
    ],
)
def test_invalid_geographic_inputs_are_rejected(values):
    module = _load_server()
    with pytest.raises(ValueError):
        module._validate_geo_inputs(*values)


def test_pagination_bounds_are_enforced():
    module = _load_server()
    assert module._validate_pagination(1, 0) == (1, 0)
    assert module._validate_pagination(100, 9999) == (100, 9999)
    for values in ((0, 0), (101, 0), (25, -1), (25, 10000)):
        with pytest.raises(ValueError):
            module._validate_pagination(*values)


def test_only_fixed_public_blm_endpoints_are_present():
    constants = (SERVER_DIR / "src" / "core" / "constants.py").read_text(encoding="utf-8")
    assert "https://gis.blm.gov/nlsdb/rest/services" in constants
    assert "http://" not in constants
    for forbidden in ("API_KEY", "PASSWORD", "SECRET", "TOKEN"):
        assert forbidden not in constants
    for restricted_field in ("CUST_NM_SEC", "SF_ID", "CSE_META", "CSE_NAME"):
        assert restricted_field not in constants


def test_free_text_filters_reject_sql_metacharacters_before_network_access():
    module = _load_server()
    with pytest.raises(ValueError, match="commodity_filter"):
        module.get_locatable_operations_in_roi(
            38.0,
            -117.0,
            commodity_filter="GOLD%' OR 1=1 --",
        )


def test_empty_and_unknown_disposition_filters_are_rejected_before_network_access():
    module = _load_server()
    with pytest.raises(ValueError, match="at least one"):
        module.get_energy_leases_in_roi(38.0, -117.0, source_dispositions=[])
    with pytest.raises(ValueError, match="unsupported"):
        module.get_energy_leases_in_roi(38.0, -117.0, source_dispositions=["Active"])


def test_server_has_no_listener_or_write_tools():
    source = (SERVER_DIR / "server.py").read_text(encoding="utf-8")
    assert 'mcp.run(transport="stdio", show_banner=False)' in source
    assert "streamable-http" not in source
    assert "0.0.0.0" not in source
    assert "@mcp.resource" not in source
    assert source.count("timeout=TOOL_TIMEOUT_SECONDS") == 3


def test_upstream_retry_and_tool_timeout_are_bounded():
    constants = (SERVER_DIR / "src" / "core" / "constants.py").read_text(encoding="utf-8")
    assert "QUERY_TIMEOUT_SECONDS = 12" in constants
    assert "QUERY_MAX_ATTEMPTS = 2" in constants
    assert "TOOL_TIMEOUT_SECONDS = 150.0" in constants
