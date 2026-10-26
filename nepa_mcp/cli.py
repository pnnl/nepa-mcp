"""Command-line interface for the installable NEPA MCP runtime."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from nepa_mcp import __version__
from nepa_mcp.aggregate import run_aggregate_server
from nepa_mcp.clients import configure_client
from nepa_mcp.config import (
    create_credential_template,
    credential_config_path,
    credential_file_is_private,
    load_credentials,
)
from nepa_mcp.loader import run_server
from nepa_mcp.registry import SERVER_SPECS, server_entrypoint, server_names


def list_servers() -> int:
    print("SERVER              CREDENTIALS                         DESCRIPTION")
    for spec in SERVER_SPECS:
        credentials = ",".join(spec.credentials) if spec.credentials else "none"
        print(f"{spec.name:<19} {credentials:<35} {spec.description}")
    return 0


def doctor() -> int:
    sources = load_credentials()
    config_path = credential_config_path()
    privacy = credential_file_is_private(config_path)

    print(f"nepa-mcp version: {__version__}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Credential file: {config_path} ({'found' if config_path.is_file() else 'not found'})")
    if privacy is False:
        print("Credential file permissions: WARNING - readable by other users")
    elif privacy is True:
        print("Credential file permissions: private")

    missing_server_files = [spec.name for spec in SERVER_SPECS if not server_entrypoint(spec.name).is_file()]
    if missing_server_files:
        print("Missing installed servers: " + ", ".join(missing_server_files))
        return 1
    print(f"Installed servers: {len(SERVER_SPECS)}")

    for spec in SERVER_SPECS:
        if not spec.credentials:
            continue
        missing = [variable for variable in spec.credentials if variable not in sources]
        if missing:
            requirement = "required for official_api; optional to toolkit" if spec.name == "nrc_adams" else "optional"
            print(f"{spec.name} credentials: {requirement}, missing {', '.join(missing)}")
        else:
            source_names = sorted({sources[variable] for variable in spec.credentials})
            print(f"{spec.name} credentials: configured via {', '.join(source_names)}")
    return 0


def configure_credentials() -> int:
    path, created = create_credential_template()
    if created:
        print(f"Created private credential template: {path}")
        print("Add only the Census, EPA AQS, or NRC ADAMS values needed for your selected servers.")
    else:
        print(f"Credential file already exists; left unchanged: {path}")
    return 0


def configure_mcp_client(
    client: str,
    *,
    path: str | None,
    dry_run: bool,
) -> int:
    target = Path(path).expanduser() if path else None
    resolved, rendered = configure_client(client, path=target, dry_run=dry_run)
    if dry_run:
        print(f"# {resolved}\n{rendered}", end="")
    else:
        print(f"Configured {client}: {resolved}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NEPA MCP local runtime")
    parser.add_argument("--version", action="version", version=f"nepa-mcp {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    server_parser = subparsers.add_parser("server", help="Start an MCP server over stdio")
    server_parser.add_argument("name", choices=("all", *server_names()))

    subparsers.add_parser("list-servers", help="List servers and optional credentials")
    subparsers.add_parser("doctor", help="Check the installation without printing secrets")

    configure_parser = subparsers.add_parser("configure", help="Create credentials or client config")
    configure_parser.add_argument(
        "target",
        nargs="?",
        default="credentials",
        choices=("credentials", "claude", "vscode", "codex"),
    )
    configure_parser.add_argument("--path", help="Override the target configuration path")
    configure_parser.add_argument("--dry-run", action="store_true", help="Print client config without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "server":
        if args.name == "all":
            run_aggregate_server()
        else:
            run_server(args.name)
        return 0
    if args.command == "list-servers":
        return list_servers()
    if args.command == "doctor":
        return doctor()
    if args.target == "credentials":
        if args.path:
            os.environ["NEPA_MCP_CONFIG_FILE"] = args.path
        if args.dry_run:
            build_parser().error("--dry-run applies only to client configuration")
        return configure_credentials()
    return configure_mcp_client(args.target, path=args.path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
