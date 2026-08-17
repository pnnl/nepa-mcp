from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

from fastmcp import Client

from nepa_mcp import cli
from nepa_mcp.aggregate import build_aggregate_server, child_server_config
from nepa_mcp.clients import render_client_config
from nepa_mcp.config import create_credential_template, load_credentials
from nepa_mcp.registry import CREDENTIAL_VARIABLES, SERVER_SPECS, server_entrypoint


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SERVERS = {
    "blm",
    "census",
    "cfr",
    "efh",
    "epa_aqs",
    "esa_ranges",
    "fema_nfhl",
    "gbif",
    "gis",
    "ipac",
    "map_composer",
    "nepa_assist",
    "noaa",
    "nrhp",
    "padus",
    "pcsrf",
    "tigerweb_counties",
    "tribal",
    "usace",
}
EXPECTED_AUTHORS = [
    "Sarthak Chaturvedi",
    "Renuka Chintalapati",
    "Daniel Nally",
    "Mike Parker",
    "Sai Munikoti",
    "Sameera Horawalavithana",
]
CANONICAL_REPOSITORY = "https://github.com/pnnl/nepa-mcp"


def test_public_package_metadata_matches_the_approved_release_identity() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice_text = (ROOT / "NOTICE").read_text(encoding="utf-8")

    assert project["version"] == "0.1.0rc1"
    assert project["description"] == (
        "MCP servers for federal environmental data, regulatory research, and geospatial screening"
    )
    assert [author["name"] for author in project["authors"]] == EXPECTED_AUTHORS
    assert project["urls"]["Homepage"] == CANONICAL_REPOSITORY
    assert project["urls"]["Repository"] == CANONICAL_REPOSITORY
    assert project["urls"]["Issues"] == f"{CANONICAL_REPOSITORY}/issues"
    assert project["license"] == "BSD-3-Clause"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    sdist_include = configuration["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/SECURITY.md" in sdist_include
    assert f'repository-code: "{CANONICAL_REPOSITORY}"' in citation
    assert "license: BSD-3-Clause" in citation
    assert "BSD-2-Clause" not in citation
    assert "under Contract DE-AC05-76RL01830" not in license_text
    assert "under Contract DE-AC05-76RL01830" in notice_text
    assert "Copyright Battelle Memorial Institute 2026" in license_text
    assert "Neither the name of the copyright holder nor the names of its contributors" in license_text


def test_registry_matches_the_public_server_inventory() -> None:
    assert {spec.name for spec in SERVER_SPECS} == EXPECTED_SERVERS
    assert all(server_entrypoint(spec.name).is_file() for spec in SERVER_SPECS)
    assert CREDENTIAL_VARIABLES == (
        "CENSUS_API_KEY",
        "EPA_AQS_EMAIL",
        "EPA_AQS_API_KEY",
    )


def test_child_servers_use_the_current_interpreter_and_stdio_cli() -> None:
    config = child_server_config("gis")["mcpServers"]["gis"]
    assert config["command"] == os.sys.executable
    assert config["args"] == ["-m", "nepa_mcp", "server", "gis"]
    assert config["env"] == {"PYTHONUNBUFFERED": "1"}


def test_direct_server_entrypoints_use_stdio_without_network_listeners() -> None:
    for spec in SERVER_SPECS:
        source = server_entrypoint(spec.name).read_text(encoding="utf-8")
        assert 'mcp.run(transport="stdio", show_banner=False)' in source
        assert "streamable-http" not in source
        assert "0.0.0.0" not in source


def test_credential_template_is_private_and_environment_wins(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config" / "credentials.env"
    monkeypatch.setenv("NEPA_MCP_CONFIG_FILE", str(config_path))
    for variable in CREDENTIAL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    path, created = create_credential_template()
    assert created is True
    assert path == config_path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    path.write_text(
        "CENSUS_API_KEY=file-census\nEPA_AQS_EMAIL=file@example.test\nEPA_AQS_API_KEY=file-aqs\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.setenv("CENSUS_API_KEY", "environment-census")
    sources = load_credentials()

    assert os.environ["CENSUS_API_KEY"] == "environment-census"
    assert sources["CENSUS_API_KEY"] == "environment"
    assert sources["EPA_AQS_EMAIL"] == "user config"
    assert sources["EPA_AQS_API_KEY"] == "user config"

    _, created_again = create_credential_template()
    assert created_again is False
    assert "file-census" in path.read_text(encoding="utf-8")


def test_doctor_never_prints_credential_values(tmp_path, monkeypatch, capsys) -> None:
    secret = "do-not-print-this-value"
    monkeypatch.setenv("NEPA_MCP_CONFIG_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("CENSUS_API_KEY", secret)
    monkeypatch.setenv("EPA_AQS_EMAIL", "person@example.test")
    monkeypatch.setenv("EPA_AQS_API_KEY", secret)

    assert cli.doctor() == 0
    output = capsys.readouterr().out
    assert secret not in output
    assert "person@example.test" not in output
    assert "configured via environment" in output


def test_client_config_generation_preserves_unrelated_entries() -> None:
    claude = render_client_config(
        "claude",
        json.dumps({"mcpServers": {"other": {"command": "node", "args": ["server.js"]}}}),
    )
    claude_data = json.loads(claude)
    assert "other" in claude_data["mcpServers"]
    assert "nepa" not in claude_data["mcpServers"]
    assert EXPECTED_SERVERS <= set(claude_data["mcpServers"])
    for server_name in EXPECTED_SERVERS:
        assert claude_data["mcpServers"][server_name]["args"] == ["server", server_name]

    codex = render_client_config(
        "codex",
        'model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "node"\n',
    )
    assert 'model = "gpt-5"' in codex
    assert "[mcp_servers.other]" in codex
    assert "[mcp_servers.nepa]" not in codex
    for server_name in EXPECTED_SERVERS:
        assert f"[mcp_servers.{server_name}]" in codex
        assert f'args = ["server", "{server_name}"]' in codex


def test_plugin_and_marketplace_register_independent_servers() -> None:
    plugin_root = ROOT / "plugins" / "nepa-mcp"
    manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp_config = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
    marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "nepa-mcp"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["skills"] == "./skills/"
    assert set(mcp_config["mcpServers"]) == EXPECTED_SERVERS
    for server_name, server_config in mcp_config["mcpServers"].items():
        assert server_config == {
            "command": "nepa-mcp",
            "args": ["server", server_name],
            "env": {"PYTHONUNBUFFERED": "1"},
        }
    assert marketplace["plugins"][0]["source"] == {
        "source": "local",
        "path": "./plugins/nepa-mcp",
    }

    plugin_text = "\n".join(path.read_text(encoding="utf-8") for path in plugin_root.rglob("*") if path.is_file())
    assert "/Users/" not in plugin_text
    assert "AWS" not in plugin_text


def test_repository_client_examples_register_the_same_independent_servers() -> None:
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    vscode = json.loads((ROOT / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    codex = (ROOT / "config.template.toml").read_text(encoding="utf-8")

    assert set(claude["mcpServers"]) == EXPECTED_SERVERS
    assert set(vscode["servers"]) == EXPECTED_SERVERS
    for server_name in EXPECTED_SERVERS:
        assert claude["mcpServers"][server_name]["args"] == ["server", server_name]
        assert vscode["servers"][server_name]["args"] == ["server", server_name]
        assert f"[mcp_servers.{server_name}]" in codex
        assert f'args = ["server", "{server_name}"]' in codex


def test_open_source_runtime_has_no_aws_secret_manager_dependency() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    credential_servers = (ROOT / "census" / "server.py").read_text(encoding="utf-8") + (
        ROOT / "epa_aqs" / "server.py"
    ).read_text(encoding="utf-8")
    credential_requirements = (ROOT / "census" / "requirements.txt").read_text(encoding="utf-8") + (
        ROOT / "epa_aqs" / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "boto3" not in project
    assert "boto3" not in credential_requirements
    assert "secretsmanager" not in credential_servers.lower()
    assert "get_secret_value" not in credential_servers


def test_non_spatial_common_import_does_not_require_pyproj() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "pyproj" or name.startswith("pyproj."):
        raise ImportError("pyproj intentionally unavailable")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import nepa_mcp_common.arcgis
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_area_enabled_standalone_servers_declare_pyproj() -> None:
    for server_name in ("efh", "esa_ranges", "noaa", "pcsrf"):
        requirements = (ROOT / server_name / "requirements.txt").read_text(encoding="utf-8")
        assert "pyproj>=3.7.0" in requirements


async def _aggregate_tool_names() -> set[str]:
    async with Client(build_aggregate_server()) as client:
        return {tool.name for tool in await client.list_tools()}


def test_aggregate_server_discovers_all_tools() -> None:
    tool_names = asyncio.run(_aggregate_tool_names())
    assert len(tool_names) == 46
    assert {
        "summarize_roi_buffer",
        "get_ipac_resources_in_roi",
        "cfr_resolve_citation",
        "get_nrhp_properties_in_roi",
        "compose_environmental_map",
        "export_all_layers_geojson",
    } <= tool_names

    layer_inventory = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from nepa_mcp.loader import load_server_module; "
                'print(len(load_server_module("map_composer").LAYER_METADATA))'
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert layer_inventory.returncode == 0, layer_inventory.stderr
    layer_count = int(layer_inventory.stdout.strip())
    capability_count = len(tool_names) + layer_count
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    inventory = (
        f"The current inventory includes {len(SERVER_SPECS)} MCP servers, "
        f"{len(tool_names)} MCP tools, and {layer_count} GIS layers."
    )
    total = (
        f"Together, the tools and layers represent **{capability_count} environmental "
        "and regulatory research capabilities**."
    )
    assert inventory in readme
    assert total in readme
