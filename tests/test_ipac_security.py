"""
Security tests for the IPaC server.

Cover input validation (coordinate/buffer bounds, NaN/inf), absence of
hardcoded secrets, and that upstream errors do not leak internal detail into
tool output. Validation is enforced by ``_validate_geo_inputs`` in
``ipac/server.py`` and the Pydantic ``Field`` bounds on the tool signature.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "ipac"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_ipac_sec_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_ipac_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ipac_sec_server"] = module
    spec.loader.exec_module(module)
    return module


class TestInputValidation:
    """The module-level _validate_geo_inputs is the single validation choke point."""

    def test_latitude_above_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(999.0, -106.5, 25.0)

    def test_latitude_below_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(-91.0, -106.5, 25.0)

    def test_longitude_out_of_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -999.0, 25.0)

    def test_zero_buffer_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -106.5, 0.0)

    def test_negative_buffer_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -106.5, -5.0)

    def test_buffer_above_max_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -106.5, 250.0)

    def test_nan_coordinate_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(float("nan"), -106.5, 25.0)

    def test_inf_coordinate_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(float("inf"), -106.5, 25.0)

    def test_non_numeric_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs("abc", -106.5, 25.0)

    def test_valid_inputs_pass_through(self):
        module = _load_server()
        lat, lon, dist = module._validate_geo_inputs(34.5, -106.5, 25.0)
        assert (lat, lon, dist) == (34.5, -106.5, 25.0)

    def test_boundary_values_accepted(self):
        module = _load_server()
        assert module._validate_geo_inputs(90.0, 180.0, 0.1)[0] == 90.0
        assert module._validate_geo_inputs(-90.0, -180.0, 100.0)[0] == -90.0


class TestNoHardcodedSecrets:
    def test_no_secret_patterns_in_source(self):
        for path in [SERVER_DIR / "server.py", SERVER_DIR / "src" / "apis" / "ipac_api.py"]:
            content = path.read_text(encoding="utf-8")
            for pattern in ("API_KEY", "SECRET", "PASSWORD", "TOKEN", "api_key="):
                assert pattern not in content, f"{pattern} found in {path.name}"

    def test_service_url_is_public_ipac(self):
        content = (SERVER_DIR / "src" / "apis" / "ipac_api.py").read_text(encoding="utf-8")
        assert "ipac.ecosphere.fws.gov" in content
        assert "api_key" not in content.lower()


class TestErrorMessageSafety:
    def test_validation_message_has_no_internal_paths(self):
        module = _load_server()
        try:
            module._validate_geo_inputs(999.0, -106.5, 25.0)
        except ValueError as exc:
            msg = str(exc)
            assert "/Users/" not in msg
            assert "Traceback" not in msg
            assert "latitude" in msg.lower()

    def test_buffer_message_has_no_internal_paths(self):
        module = _load_server()
        try:
            module._validate_geo_inputs(34.5, -106.5, 999.0)
        except ValueError as exc:
            msg = str(exc)
            assert "/Users/" not in msg
            assert "Traceback" not in msg
            assert "buffer" in msg.lower()
