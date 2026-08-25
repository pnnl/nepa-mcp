"""Stable inventory and installed-path resolution for NEPA MCP servers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerSpec:
    name: str
    description: str
    credentials: tuple[str, ...] = ()


SERVER_SPECS = (
    ServerSpec("blm", "BLM land use plans, wilderness areas, and national monuments"),
    ServerSpec("census", "Census ACS socioeconomic indicators", ("CENSUS_API_KEY",)),
    ServerSpec("cfr", "CFR, Federal Register, and executive-order lookup"),
    ServerSpec("efh", "NOAA Essential Fish Habitat and HAPC screening"),
    ServerSpec("epa_acres", "EPA ACRES Brownfields property records"),
    ServerSpec(
        "epa_aqs",
        "EPA air-quality monitoring and NAAQS screening",
        ("EPA_AQS_EMAIL", "EPA_AQS_API_KEY"),
    ),
    ServerSpec("esa_ranges", "NOAA ESA-listed species ranges"),
    ServerSpec("fema_nfhl", "FEMA flood zones, levees, and water areas"),
    ServerSpec("gbif", "GBIF species occurrences and biodiversity data"),
    ServerSpec("gis", "Region-of-interest geometry and area utilities"),
    ServerSpec("ipac", "USFWS IPaC species and habitat resources"),
    ServerSpec("map_composer", "Interactive environmental maps and GeoJSON exports"),
    ServerSpec("nepa_assist", "EPA NEPAssist environmental screening"),
    ServerSpec("noaa", "NOAA West Coast critical habitat"),
    ServerSpec("nrhp", "National Register of Historic Places properties"),
    ServerSpec("padus", "PAD-US protected areas and land management"),
    ServerSpec("pcsrf", "NOAA species, habitat, and recovery-program datasets"),
    ServerSpec("tigerweb_counties", "Census TIGERweb county intersections"),
    ServerSpec("tribal", "Census AIANNHA tribal lands"),
    ServerSpec("usace", "USACE districts and wetland regions"),
)

SERVERS = {spec.name: spec for spec in SERVER_SPECS}
CREDENTIAL_VARIABLES = tuple(variable for spec in SERVER_SPECS for variable in spec.credentials)


def server_names() -> tuple[str, ...]:
    return tuple(SERVERS)


def get_server(name: str) -> ServerSpec:
    try:
        return SERVERS[name]
    except KeyError:
        known = ", ".join(server_names())
        raise KeyError(f"unknown server {name!r}; expected one of: {known}") from None


def server_directory(name: str) -> Path:
    """Resolve a server directory in a wheel or in this source checkout."""
    get_server(name)
    package_root = Path(__file__).resolve().parent
    candidates = (
        package_root / "_servers" / name,
        package_root.parent / name,
    )
    for candidate in candidates:
        if (candidate / "server.py").is_file():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"server {name!r} is not installed; searched: {searched}")


def server_entrypoint(name: str) -> Path:
    return server_directory(name) / "server.py"
