"""
Security tests for the EPA ACRES server.

Cover input validation (coordinate/buffer bounds, NaN/inf), absence of
hardcoded secrets, and that upstream errors do not leak internal detail into
tool output. Validation is enforced by ``_validate_geo_inputs`` in
``epa_acres/server.py`` and the Pydantic ``Field`` bounds on the tool
signature.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_acres"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_acres_sec_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_epa_acres_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_acres_sec_server"] = module
    spec.loader.exec_module(module)
    return module


class TestInputValidation:
    """Module-level validation rejects unsafe inputs before upstream calls."""

    def test_latitude_above_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(999.0, -79.99, 25.0)

    def test_latitude_below_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(-91.0, -79.99, 25.0)

    def test_longitude_out_of_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(40.44, -999.0, 25.0)

    def test_zero_buffer_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(40.44, -79.99, 0.0)

    def test_negative_buffer_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(40.44, -79.99, -5.0)

    def test_buffer_above_max_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(40.44, -79.99, 250.0)

    def test_nan_coordinate_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(float("nan"), -79.99, 25.0)

    def test_inf_coordinate_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(float("inf"), -79.99, 25.0)

    def test_non_numeric_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs("abc", -79.99, 25.0)

    def test_valid_inputs_pass_through(self):
        module = _load_server()
        lat, lon, dist = module._validate_geo_inputs(40.44, -79.99, 25.0)
        assert (lat, lon, dist) == (40.44, -79.99, 25.0)

    def test_boundary_values_accepted(self):
        module = _load_server()
        assert module._validate_geo_inputs(90.0, 180.0, 0.1)[0] == 90.0
        assert module._validate_geo_inputs(-90.0, -180.0, 100.0)[0] == -90.0

    def test_result_window_bounds(self):
        module = _load_server()
        assert module._validate_result_window(1, 0) == (1, 0)
        assert module._validate_result_window(100, 9999) == (100, 9999)
        with pytest.raises(ValueError):
            module._validate_result_window(0, 0)
        with pytest.raises(ValueError):
            module._validate_result_window(101, 0)
        with pytest.raises(ValueError):
            module._validate_result_window(100, -1)
        with pytest.raises(ValueError):
            module._validate_result_window(100, 10000)


class TestNoHardcodedSecrets:
    def test_no_secret_patterns_in_source(self):
        for path in [SERVER_DIR / "server.py", SERVER_DIR / "src" / "apis" / "acres_api.py"]:
            content = path.read_text(encoding="utf-8")
            for pattern in ("API_KEY", "SECRET", "PASSWORD", "TOKEN", "api_key="):
                assert pattern not in content, f"{pattern} found in {path.name}"

    def test_service_urls_are_public_epa(self):
        content = (SERVER_DIR / "src" / "core" / "constants.py").read_text(encoding="utf-8")
        assert "geopub.epa.gov" in content
        assert "api_key" not in content.lower()


class TestErrorMessageSafety:
    def test_validation_message_has_no_internal_paths(self):
        module = _load_server()
        try:
            module._validate_geo_inputs(999.0, -79.99, 25.0)
        except ValueError as exc:
            msg = str(exc)
            assert "/Users/" not in msg
            assert "Traceback" not in msg
            # The value is echoed, which is acceptable and useful.
            assert "latitude" in msg.lower()
