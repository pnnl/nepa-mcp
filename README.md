<div align="center" style="text-align: center;">

  <img src="https://raw.githubusercontent.com/pnnl/nepa-mcp/v0.1.4/docs/assets/permitai-nepa-mcp-toolkit-tm.svg" alt="PermitAI — NEPA MCP Toolkit™" width="740">
  <br>

  <p>
  <strong>Federal environmental data and regulatory research for AI-assisted NEPA workflows</strong>
  </p>

  <p>
  Works with<br>
  <a href="#configure-an-mcp-client"><img alt="Codex MCP client" src="https://raw.githubusercontent.com/pnnl/nepa-mcp/v0.1.4/docs/assets/badges/codex-client-config.svg" height="20"></a>
  <a href="#codex-plugin"><img alt="Codex plugin" src="https://raw.githubusercontent.com/pnnl/nepa-mcp/v0.1.4/docs/assets/badges/codex-plugin.svg" height="20"></a>
  <a href="#configure-an-mcp-client"><img alt="Claude Code client configuration" src="https://img.shields.io/badge/Claude_Code-MCP_Client-D97757?style=flat-square&amp;logo=anthropic&amp;logoColor=white" height="20"></a>
  <a href="#configure-an-mcp-client"><img alt="VS Code client configuration" src="https://raw.githubusercontent.com/pnnl/nepa-mcp/v0.1.4/docs/assets/badges/vscode-mcp-client.svg" height="20"></a>
  </p>

  <p>
  Built with<br>
  <a href="https://www.python.org/"><img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" height="20"></a>
  <a href="https://gofastmcp.com/"><img alt="FastMCP 3.4.4" src="https://img.shields.io/badge/FastMCP-3.4.4-009688?style=flat-square" height="20"></a>
  <a href="https://docs.pydantic.dev/"><img alt="Pydantic 2.12+" src="https://img.shields.io/badge/Pydantic-2.12%2B-E92063?style=flat-square&amp;logo=pydantic&amp;logoColor=white" height="20"></a>
  <a href="https://shapely.readthedocs.io/"><img alt="Shapely 2.0+" src="https://img.shields.io/badge/Shapely-2.0%2B-2F6F3E?style=flat-square" height="20"></a>
  <a href="https://github.com/pnnl/nepa-mcp/blob/main/LICENSE"><img alt="BSD 3-Clause License" src="https://img.shields.io/badge/License-BSD_3--Clause-F4B942?style=flat-square" height="20"></a>
  </p>

</div>

NEPA MCP is the Model Context Protocol (MCP) server layer of the PermitAI
toolkit. It gives AI agents structured access to federal environmental,
regulatory, biological, cultural, socioeconomic, and jurisdictional data used
in NEPA screening and permitting research.

The current inventory includes 22 MCP servers, 53 MCP tools, and 32 GIS
layers. Together, the tools and layers represent **85 environmental and
regulatory research capabilities**. These capabilities draw on public data
from 13 federal agencies, along with interagency and nonfederal sources.

The [MCP Tool Catalog](https://github.com/pnnl/nepa-mcp/blob/main/docs/mcp-tool-catalog.md) provides the complete server
and tool inventory. The [Map Composer MCP server](https://github.com/pnnl/nepa-mcp/blob/main/docs/map-composer.md) queries
public GIS services from eight federal data publishers at request time. It can
compose selected results into an interactive map or a provenance-rich GeoJSON
export.

> **Important**
>
> NEPA MCP is a screening and research aid. It does not make legal or agency
> determinations, replace consultation with agencies or Tribes, or guarantee
> that an upstream dataset is complete or current. Confirm material findings
> against authoritative records and current requirements.

## Quick Start

### Prerequisites

- Python 3.12 or newer
- [`pipx`](https://pipx.pypa.io/) for an isolated installation

Install the stable package from PyPI:
<a href="https://pypi.org/project/nepa-mcp/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/nepa-mcp?style=flat-square&amp;logo=pypi&amp;logoColor=white&amp;label=PyPI&amp;color=3775A9" height="20"></a>

```bash
pipx install nepa-mcp
pipx ensurepath
```

If `pipx ensurepath` reports a change, reopen the terminal before continuing.
If pipx selects a Python version older than 3.12, repeat the installation with
`pipx install --python 3.12 nepa-mcp`.

Verify the installation and list the available servers:

```bash
nepa-mcp doctor
nepa-mcp list-servers
```

Upgrade an existing PyPI installation:

```bash
pipx upgrade nepa-mcp
```

If `pipx upgrade` keeps an older version that was originally installed from a
local checkout or Git URL, replace that pipx environment with the current PyPI
release:

```bash
pipx install --force nepa-mcp
nepa-mcp doctor
```

This leaves the separate per-user NEPA MCP credential file unchanged.

## Configure an MCP Client

> **Before continuing:** For Claude Code or VS Code, confirm that the terminal
> is open in the project or workspace you intend to configure. The configuration
> file will be created or updated there.

| Client | Recommended setup |
|---|---|
| Claude Code | `nepa-mcp configure claude` |
| VS Code | `nepa-mcp configure vscode` |
| Codex CLI | `nepa-mcp configure codex` |
| Codex Desktop | [Install the Codex plugin](#codex-plugin) |

Restart or reload the selected client after configuring it; for Codex, start a
new task.

## Codex Plugin

The Codex plugin registers all 22 servers and includes the `nepa-screening`
skill. If you use the plugin, do not also run `nepa-mcp configure codex`.

Install and verify the Python runtime before adding the plugin:

```bash
pipx install nepa-mcp
nepa-mcp doctor
```

`doctor` should report `Installed servers: 22`. Then add the marketplace in
Codex Desktop:

1. Open **Plugins** and select **Add plugin marketplace**.
2. Enter `pnnl/nepa-mcp` for **Source** and `v0.1.4` for **Git ref**.
3. Leave **Sparse paths** blank, then select **Add marketplace**.
4. Install **NEPA-MCP** from the **NEPA-MCP Local** marketplace.

The equivalent Codex CLI commands are:

```bash
codex plugin marketplace add pnnl/nepa-mcp --ref v0.1.4
codex plugin add nepa-mcp@nepa-mcp-local
```

Start a new Codex task after installing the plugin so the new MCP tools and
skill are loaded.

## Map Composer

`map_composer` turns project-area data into an interactive HTML map or a
combined GeoJSON file for QGIS, ArcGIS, and other geospatial workflows. It
provides 32 selectable overlays assembled at request time from Census, USFWS,
USACE, USGS, BLM, USFS, NPS, and NIFC public GIS services.

The result is intentionally interactive rather than a fixed stack: start with
one of five profiles, then toggle returned layers to preserve visual clarity
for the question at hand. Every map reports requested, rendered, empty,
partial, and failed layer counts so source coverage remains visible.

<p align="center">
  <a href="https://github.com/pnnl/nepa-mcp/blob/main/docs/map-composer.md">
    <img src="https://raw.githubusercontent.com/pnnl/nepa-mcp/v0.1.4/docs/assets/map-composer-washington-dc-chesapeake.png" alt="Interactive Map Composer view of a 20-mile Chesapeake Bay watershed project area with 12 overlays visible" width="900">
  </a>
</p>

<p align="center">
  <em>Chesapeake Bay watershed, 20-mile project area: 12 overlays shown from 16 returned locally in a 32-layer request, with no failed sources. The generated map keeps every returned layer independently toggleable.</em>
</p>

See the [Map Composer guide](https://github.com/pnnl/nepa-mcp/blob/main/docs/map-composer.md) for profile membership, the
complete 32-layer catalog, output behavior, provenance, and artifact storage.

## Credentials

Credentials are not required to install NEPA MCP or use the other 20 servers.
The Census and EPA AQS servers require credentials before they can return data:

| Server | Environment variables |
|---|---|
| `census` | `CENSUS_API_KEY` |
| `epa_aqs` | `EPA_AQS_EMAIL`, `EPA_AQS_API_KEY` |

Set the variables in the shell or create a private per-user credential file:

```bash
nepa-mcp configure credentials
nepa-mcp doctor
```

`configure` creates a template only when one does not already exist and prints
its location. The default is the operating system's per-user configuration
directory under `nepa-mcp/credentials.env`; override it with
`NEPA_MCP_CONFIG_FILE`. Environment variables take precedence over the file.
Credentials are not copied into MCP client or plugin configuration, and
`doctor` reports only whether each value is present.

## Server Inventory

| Server | Source agency / publisher | Purpose |
|---|---|---|
| `blm` | [Bureau of Land Management](https://www.blm.gov/) / [Department of the Interior](https://www.doi.gov/) | Approved land-use plans, wilderness areas, national monuments, and National Conservation Areas |
| `blm_mlrs` | [Bureau of Land Management](https://www.blm.gov/) / [Mineral & Land Records System](https://mlrs.blm.gov/) | Land-use authorization cases, locatable-mineral operations, and geothermal and oil-and-gas leases |
| `census` | [U.S. Census Bureau](https://www.census.gov/) | ACS 5-Year socioeconomic indicators for intersecting TIGERweb counties |
| `cfr` | [Office of the Federal Register / National Archives](https://www.archives.gov/federal-register) and [U.S. Government Publishing Office](https://www.gpo.gov/) | eCFR and Federal Register records, including executive orders |
| `efh` | [NOAA Fisheries](https://www.fisheries.noaa.gov/) | EFH Mapper data for EFH, HAPC, salmon, HMS, coastal pelagic species, and groundfish screening |
| `epa_acres` | [U.S. Environmental Protection Agency](https://www.epa.gov/) | ACRES grant-reported Brownfields property records for redevelopment and site-screening context |
| `epa_aqs` | [U.S. Environmental Protection Agency](https://www.epa.gov/) | Air Quality System monitoring data and NAAQS screening comparisons |
| `esa_ranges` | [NOAA Fisheries, West Coast Region](https://www.fisheries.noaa.gov/about/west-coast-region) | ESA-listed salmon and steelhead ranges by HUC-12 watershed |
| `fema_nfhl` | [Federal Emergency Management Agency](https://www.fema.gov/) | National Flood Hazard Layer flood zones, levees, and water areas |
| `gbif` | [Global Biodiversity Information Facility](https://www.gbif.org/) and contributing dataset publishers; [U.S. Census Bureau](https://www.census.gov/) for county boundaries | Occurrence records by ROI or county; record-level publisher and license vary |
| `gis` | [Esri](https://www.esri.com/) | ArcGIS Geometry Service ROI buffers with locally derived GeoJSON and area estimates |
| `ipac` | [U.S. Fish and Wildlife Service](https://www.fws.gov/) / [Department of the Interior](https://www.doi.gov/) | IPaC species, critical habitat, migratory birds, wetlands, refuges, and related resources |
| `map_composer` | Census, USFWS, USACE, USGS, BLM, USFS, NPS, and NIFC public GIS services | Interactive project-area maps and provenance-rich GeoJSON exports across 32 selectable layers |
| `nepa_assist` | [U.S. Environmental Protection Agency](https://www.epa.gov/) | NEPAssist aggregated environmental-screening indicators |
| `noaa` | [NOAA Fisheries, West Coast Region](https://www.fisheries.noaa.gov/about/west-coast-region) | ESA critical-habitat designations |
| `nrcs_soils` | [USDA Natural Resources Conservation Service](https://www.nrcs.usda.gov/) | SSURGO soil map units, siting-related soil indicators, and farmland classifications |
| `nrhp` | [National Park Service](https://www.nps.gov/) / [Department of the Interior](https://www.doi.gov/) | National Register-listed property locations |
| `padus` | [U.S. Geological Survey](https://www.usgs.gov/) / [Department of the Interior](https://www.doi.gov/) | PAD-US 4.1 protected-area owner and manager attributes for screening |
| `pcsrf` | [NOAA Fisheries](https://www.fisheries.noaa.gov/) | PCSRF projects plus species ranges, a 2021 critical-habitat snapshot, and Atlantic salmon EFH/HAPC |
| `tigerweb_counties` | [U.S. Census Bureau](https://www.census.gov/) | TIGERweb county-boundary intersections |
| `tribal` | [U.S. Census Bureau](https://www.census.gov/) | TIGERweb AIANNHA geographic areas for tribal-consultation screening |
| `usace` | [U.S. Army Corps of Engineers](https://www.usace.army.mil/) | Regulatory boundaries and wetland delineation regions and subregions |

> Many geographic servers also use [Esri's ArcGIS Geometry Service](https://developers.arcgis.com/rest/services-reference/enterprise/geometry-service/)
> to construct ROI buffers. Esri is a supporting geometry-service provider,
> not the publisher of the agency datasets identified above.

See [Geographic Inputs and Data Behavior](https://github.com/pnnl/nepa-mcp/blob/main/docs/geographic-inputs-and-data-behavior.md)
for ROI constraints, area and clipping semantics, coverage warnings, and
partial-source behavior across geographic servers.

## Development

[`uv`](https://docs.astral.sh/uv/) is required only for source development and
testing. From the repository root:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q .
uv run pytest -q
```

Most tests do not require credentials. To exercise the optional Census or EPA
AQS integrations, use `uv run nepa-mcp configure` or export the variables
listed above. A repository `.env` file is not loaded automatically; opt into it
with `uv run --env-file .env <command>`.

Each domain follows the same basic layout:

```text
server_name/
├── requirements.txt
├── server.py
└── src/
    ├── apis/
    └── core/
```

Shared runtime, HTTP, validation, and ArcGIS utilities live in
`nepa_mcp_common/`. The root `pyproject.toml` builds the installable distribution;
individual `requirements.txt` files remain available for standalone deployment
packaging.

Inspect a server's MCP contract with FastMCP:

```bash
uv run fastmcp inspect cfr/server.py:mcp --skip-env
```

The test suite checks server startup and discovery, tool-schema readability,
offline invalid-argument handling, shared utilities, and distribution contents.

## Data Sources and Licensing

**Source agencies and publishers:** [Bureau of Land Management](https://www.blm.gov/)
· [Department of the Interior](https://www.doi.gov/)
· [U.S. Census Bureau](https://www.census.gov/)
· [U.S. Environmental Protection Agency](https://www.epa.gov/)
· [Esri](https://www.esri.com/)
· [Federal Emergency Management Agency](https://www.fema.gov/)
· [Office of the Federal Register](https://www.archives.gov/federal-register)
and [U.S. Government Publishing Office](https://www.gpo.gov/)
· [Global Biodiversity Information Facility](https://www.gbif.org/)
and contributing dataset publishers
· [National Park Service](https://www.nps.gov/)
· [National Interagency Fire Center](https://www.nifc.gov/)
· [NOAA Fisheries](https://www.fisheries.noaa.gov/)
· [U.S. Army Corps of Engineers](https://www.usace.army.mil/)
· [U.S. Fish and Wildlife Service](https://www.fws.gov/)
· [USDA Natural Resources Conservation Service](https://www.nrcs.usda.gov/)
· [USDA Forest Service](https://www.fs.usda.gov/)
· [U.S. Geological Survey](https://www.usgs.gov/)

> **Note**
>
> Agency and publisher names identify upstream data provenance only. NEPA MCP
> is an independent project and is not affiliated with, sponsored by, or
> endorsed by these organizations.

The [data-source inventory](https://github.com/pnnl/nepa-mcp/blob/main/docs/mcp-data-source-licenses.md) records
the source agencies, endpoints, authentication requirements, license signals,
and release notes for the current server inventory. Upstream data remains
subject to each source's terms and authoritative-use guidance.

## Contributing

Issues and pull requests are welcome. See [Contributing](https://github.com/pnnl/nepa-mcp/blob/main/CONTRIBUTING.md) for
development setup, required checks, pull-request expectations, and DCO
sign-off. Participation is governed by the [Code of Conduct](https://github.com/pnnl/nepa-mcp/blob/main/CODE_OF_CONDUCT.md).
Report suspected vulnerabilities through the private process in the
[Security Policy](https://github.com/pnnl/nepa-mcp/blob/main/SECURITY.md).
See [Support](https://github.com/pnnl/nepa-mcp/blob/main/SUPPORT.md) for the project's best-effort support boundary and
issue-reporting guidance. Current repository-governance roles are listed in
[Project Roles](https://github.com/pnnl/nepa-mcp/blob/main/MAINTAINERS.md).

## Acknowledgments

This work was supported by the U.S. Department of Energy’s Office of Policy and
Office of Critical Minerals and Energy Innovation and performed at Pacific
Northwest National Laboratory.

The authors acknowledge Tracy Fuentes for NEPA input during IPaC MCP evaluation;
Weili Xu for consultation on packaging MCP servers in Codex Marketplace
plugins; Scott Spare, Derek Lilienthal, and David Kocen for discussions on MCP
deployment in cloud environments; and Anastasia Bernat for GIS perspectives
shared during project discussions.

## License

The repository's source code is available under the
[BSD 3-Clause License](https://github.com/pnnl/nepa-mcp/blob/main/LICENSE). The accompanying [PNNL/DOE notice](https://github.com/pnnl/nepa-mcp/blob/main/NOTICE)
contains the sponsorship, warranty, endorsement, and views disclaimer.

## Citation

If you use NEPA MCP in research, environmental assessments, or other scientific
or technical publications, please use the metadata in [`CITATION.cff`](https://github.com/pnnl/nepa-mcp/blob/main/CITATION.cff)
or cite it as:

```bibtex
@software{nepa_mcp,
  author       = {Chaturvedi, Sarthak and Chintalapati, Renuka and Nally, Daniel and Parker, Mike and Munikoti, Sai and Horawalavithana, Sameera},
  title        = {PermitAI NEPA MCP Toolkit: Federal Environmental Data, Regulatory Research, and Geospatial Screening},
  year         = {2026},
  institution  = {Pacific Northwest National Laboratory},
  url          = {https://github.com/pnnl/nepa-mcp},
  version      = {0.1.4},
  license      = {BSD-3-Clause}
}
```
