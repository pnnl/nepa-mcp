"""User-owned credential configuration for the open-source runtime."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from dotenv import dotenv_values
from platformdirs import user_config_path

from nepa_mcp.registry import CREDENTIAL_VARIABLES

CONFIG_TEMPLATE = """# Optional credentials for NEPA MCP.
# Keep this file private. Existing shell environment variables take precedence.

# Census API key: https://api.census.gov/data/key_signup.html
CENSUS_API_KEY=

# EPA AQS credentials: https://aqs.epa.gov/data/api/signup
EPA_AQS_EMAIL=
EPA_AQS_API_KEY=

# Required for NRC ADAMS API calls: https://adams-api-developer.nrc.gov/
NRC_ADAMS_API_KEY=
"""


def credential_config_path() -> Path:
    configured = os.environ.get("NEPA_MCP_CONFIG_FILE")
    if configured:
        return Path(configured).expanduser()
    return user_config_path("nepa-mcp", "NEPA-MCP") / "credentials.env"


def load_credentials() -> dict[str, str]:
    """Load optional credentials without replacing process environment values.

    Returns a variable-to-source mapping and never returns credential values.
    """
    sources = {variable: "environment" for variable in CREDENTIAL_VARIABLES if os.environ.get(variable)}
    path = credential_config_path()
    if not path.is_file():
        return sources

    values = dotenv_values(path)
    for variable in CREDENTIAL_VARIABLES:
        value = values.get(variable)
        if variable not in sources and value:
            os.environ[variable] = value
            sources[variable] = "user config"
    return sources


def create_credential_template() -> tuple[Path, bool]:
    """Create an owner-only credential template, without overwriting secrets."""
    path = credential_config_path()
    if path.exists():
        return path, False

    parent_missing = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent_missing:
        path.parent.chmod(0o700)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(CONFIG_TEMPLATE)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    path.chmod(0o600)
    return path, True


def credential_file_is_private(path: Path | None = None) -> bool | None:
    target = path or credential_config_path()
    if not target.exists():
        return None
    return stat.S_IMODE(target.stat().st_mode) & 0o077 == 0
