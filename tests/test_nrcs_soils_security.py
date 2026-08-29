"""Input and query-construction security tests for the NRCS soils server."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "nrcs_soils"


def _load(module_file: Path, module_name: str):
    for name in list(sys.modules):
        if name == "src" or name.startswith("src.") or name.startswith("_nrcs_security_"):
            sys.modules.pop(name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location(module_name, module_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_geo_validation_rejects_nonfinite_and_oversized_inputs():
    server = _load(SERVER_DIR / "server.py", "_nrcs_security_server")

    for args in (
        (float("nan"), -121.6, 1.0),
        (37.7, float("inf"), 1.0),
        (37.7, -121.6, 0.0),
        (37.7, -121.6, 10.1),
    ):
        with pytest.raises(ValueError):
            server._validate_geo_inputs(*args)


def test_query_builders_reject_sql_metacharacters():
    api = _load(SERVER_DIR / "src" / "apis" / "nrcs_soils_api.py", "_nrcs_security_api")

    with pytest.raises(ValueError):
        api._mapunit_query("POLYGON((0 0,1 0,0 0)); DROP TABLE mapunit")
    with pytest.raises(ValueError):
        api._constraint_queries(["123", "456 OR 1=1"])
    with pytest.raises(ValueError):
        api._constraint_queries(["１２３"])


def test_queries_are_select_only_and_bounded():
    api = _load(SERVER_DIR / "src" / "apis" / "nrcs_soils_api.py", "_nrcs_security_api_select")

    query = api._mapunit_query("POLYGON((0 0,1 0,0 1,0 0))")
    detail_queries = api._constraint_queries(["123", "456"])
    combined = "\n".join((query, *detail_queries)).upper()

    assert "SELECT TOP" in combined
    assert "DROP " not in combined
    assert "DELETE " not in combined
    assert "UPDATE " not in combined
    assert "INSERT " not in combined


def test_source_contains_no_credentials_or_unsafe_execution():
    source = (SERVER_DIR / "src" / "apis" / "nrcs_soils_api.py").read_text(encoding="utf-8")
    constants = (SERVER_DIR / "src" / "core" / "constants.py").read_text(encoding="utf-8")

    for token in ("API_KEY", "PASSWORD", "SECRET", "TOKEN", "eval(", "exec("):
        assert token not in source
        assert token not in constants
    assert "https://sdmdataaccess.sc.egov.usda.gov/" in constants
