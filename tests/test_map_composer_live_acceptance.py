"""Opt-in checks for the live BLM source used by Map Composer.

Run explicitly with:

    RUN_MAP_COMPOSER_LIVE=1 uv run pytest -q \
        tests/test_map_composer_live_acceptance.py -s

The ordinary test suite remains hermetic because this module is skipped unless
the environment variable is set.
"""

from __future__ import annotations

import os

import pytest
import requests


RUN_LIVE = os.getenv("RUN_MAP_COMPOSER_LIVE") == "1"
pytestmark = pytest.mark.skipif(not RUN_LIVE, reason="set RUN_MAP_COMPOSER_LIVE=1 to run live Map Composer acceptance")

WSA_SERVICE_URL = (
    "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/"
    "BLM_Natl_NLCS_Wilderness_Study_Areas_Polygons/FeatureServer"
)
WSA_LAYER_ID = 3
EXPECTED_FIELDS = {"NLCS_NAME", "NLCS_ID", "CASEFILE_NO", "WSA_RCMND", "ADMIN_ST"}


def _get_json(url: str, params: dict[str, str]) -> dict:
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    assert isinstance(payload, dict)
    assert "error" not in payload, payload.get("error")
    return payload


def test_national_wsa_layer_contract_and_nevada_coverage() -> None:
    service = _get_json(WSA_SERVICE_URL, {"f": "json"})
    assert any(
        layer.get("id") == WSA_LAYER_ID
        and layer.get("geometryType") == "esriGeometryPolygon"
        and "Natl" in layer.get("name", "")
        for layer in service.get("layers", [])
    )

    layer_url = f"{WSA_SERVICE_URL}/{WSA_LAYER_ID}"
    layer = _get_json(layer_url, {"f": "json"})
    assert EXPECTED_FIELDS <= {field.get("name") for field in layer.get("fields", [])}

    nevada = _get_json(
        f"{layer_url}/query",
        {
            "where": "ADMIN_ST = 'NV'",
            "returnCountOnly": "true",
            "f": "json",
        },
    )
    assert nevada.get("count", 0) > 0
