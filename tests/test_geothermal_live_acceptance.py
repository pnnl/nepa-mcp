"""Opt-in public service contracts; no credentials, writes, or fixed national counts.

RUN_GEOTHERMAL_LIVE=1 python -m pytest tests/test_geothermal_live_acceptance.py
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
import requests

from nepa_mcp.loader import load_server_module
from nepa_mcp_common.land_status import (
    GEOTHERMAL_LAYER,
    NCA_LAYER,
    PADUS_DESIGNATIONS_LAYER,
    WILDERNESS_LAYER,
    WSA_LAYER,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_GEOTHERMAL_LIVE") != "1", reason="opt-in public source requests")


@pytest.mark.parametrize(
    "url,fields",
    [
        (WSA_LAYER, {"NLCS_NAME", "NLCS_ID", "CASEFILE_NO", "WSA_RCMND", "ADMIN_ST", "ROD_DATE"}),
        (WILDERNESS_LAYER, {"NLCS_NAME", "NLCS_ID", "CASEFILE_NO", "ADMIN_ST", "DESIG_DATE"}),
        (NCA_LAYER, {"NCA_NAME", "NLCS_ID", "sma_code"}),
        (PADUS_DESIGNATIONS_LAYER, {"Category", "Unit_Nm", "Des_Tp", "Mang_Name", "Date_Est", "State_Nm"}),
        (
            GEOTHERMAL_LAYER,
            {"OBJECTID", "CSE_NR", "LEG_CSE_NR", "CSE_NAME", "CSE_DISP", "EXP_DT", "EFF_DT", "SRC", "QLTY"},
        ),
    ],
)
def test_published_layer_schemas(url, fields):
    response = requests.get(url, params={"f": "json"}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    assert "error" not in payload, payload
    assert fields <= {field["name"] for field in payload["fields"]}


def test_live_numunaa_nobe_geometry_classification_and_collector():
    original_path = list(sys.path)
    try:
        directory = str(Path(__file__).resolve().parents[1] / "map_composer")
        sys.path[:] = [entry for entry in sys.path if entry != directory]
        load_server_module("map_composer")
        collector = importlib.import_module("src.core.geometry_collector")
        response = requests.get(
            NCA_LAYER + "/query",
            params={
                "f": "json",
                "where": "NLCS_ID = 'NLCS000607'",
                "outFields": "NCA_NAME,NLCS_ID,sma_code",
                "returnGeometry": "true",
                "outSR": 4326,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        assert "error" not in payload and payload["features"]
        geometry = payload["features"][0]["geometry"]
        result = collector.get_blm_national_monuments_geojson(geometry)
        assert result["status"] in ("ok", "partial"), result
        matching = [f for f in result["features"] if f["properties"]["nlcs_id"] == "NLCS000607"]
        assert matching and matching[0]["properties"]["designation_type"] == "national_conservation_area"
    finally:
        sys.path[:] = original_path
        for name in tuple(sys.modules):
            if name == "src" or name.startswith("src."):
                sys.modules.pop(name, None)


def test_sda_hydric_component_fields():
    response = requests.post(
        "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
        json={
            "query": "SELECT TOP 3 mukey,cokey,compname,comppct_r,hydricrating FROM component WHERE hydricrating = 'Yes'",
            "format": "JSON+COLUMNNAME",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    assert "error" not in payload, payload
    table = payload["Table"]
    assert {"mukey", "cokey", "compname", "comppct_r", "hydricrating"} <= set(table[0])
    assert len(table) > 1
