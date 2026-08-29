/**
 * NEPA MCP Toolkit - site data
 *
 * Generated from project metadata, the server registry, and each server's
 * live MCP tools/list contract. Do not edit manually. Regenerate with
 * `uv run python scripts/generate_site_data.py`; add `--check` to verify.
 */

/* eslint-disable */
var SITE_DATA = {
  "generatedFrom": "pyproject.toml, nepa_mcp.registry, and each server's live MCP tools/list contract",
  "release": {
    "version": "0.1.4",
    "license": "BSD-3-Clause",
    "licenseName": "BSD 3-Clause",
    "description": "MCP servers for federal environmental data, regulatory research, and geospatial screening",
    "repository": "https://github.com/pnnl/nepa-mcp"
  },
  "counts": {
    "servers": 21,
    "tools": 50,
    "layers": 32,
    "agencies": 13,
    "profiles": 5,
    "capabilities": 82,
    "credentialFreeServers": 19
  },
  "servers": [
    {
      "name": "blm",
      "description": "BLM land use plans, wilderness areas, and national monuments",
      "agency": "Bureau of Land Management",
      "accent": "amber",
      "credentials": [],
      "toolCount": 3
    },
    {
      "name": "census",
      "description": "Census ACS socioeconomic indicators",
      "agency": "U.S. Census Bureau",
      "accent": "indigo",
      "credentials": [
        "CENSUS_API_KEY"
      ],
      "toolCount": 1
    },
    {
      "name": "cfr",
      "description": "CFR, Federal Register, and executive-order lookup",
      "agency": "Federal Register / GPO",
      "accent": "slate",
      "credentials": [],
      "toolCount": 7
    },
    {
      "name": "efh",
      "description": "NOAA Essential Fish Habitat and HAPC screening",
      "agency": "NOAA Fisheries",
      "accent": "sky",
      "credentials": [],
      "toolCount": 4
    },
    {
      "name": "epa_acres",
      "description": "EPA ACRES Brownfields property records",
      "agency": "U.S. Environmental Protection Agency",
      "accent": "emerald",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "epa_aqs",
      "description": "EPA air-quality monitoring and NAAQS screening",
      "agency": "U.S. Environmental Protection Agency",
      "accent": "emerald",
      "credentials": [
        "EPA_AQS_EMAIL",
        "EPA_AQS_API_KEY"
      ],
      "toolCount": 3
    },
    {
      "name": "esa_ranges",
      "description": "NOAA ESA-listed species ranges",
      "agency": "NOAA Fisheries",
      "accent": "sky",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "fema_nfhl",
      "description": "FEMA flood zones, levees, and water areas",
      "agency": "Federal Emergency Management Agency",
      "accent": "rose",
      "credentials": [],
      "toolCount": 4
    },
    {
      "name": "gbif",
      "description": "GBIF species occurrences and biodiversity data",
      "agency": "Global Biodiversity Information Facility",
      "accent": "lime",
      "credentials": [],
      "toolCount": 2
    },
    {
      "name": "gis",
      "description": "Region-of-interest geometry and area utilities",
      "agency": "Esri geometry service",
      "accent": "violet",
      "credentials": [],
      "toolCount": 3
    },
    {
      "name": "ipac",
      "description": "USFWS IPaC species and habitat resources",
      "agency": "U.S. Fish and Wildlife Service",
      "accent": "amber",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "map_composer",
      "description": "Interactive environmental maps and GeoJSON exports",
      "agency": "Eight federal GIS publishers",
      "accent": "teal",
      "credentials": [],
      "toolCount": 3
    },
    {
      "name": "nepa_assist",
      "description": "EPA NEPAssist environmental screening",
      "agency": "U.S. Environmental Protection Agency",
      "accent": "emerald",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "noaa",
      "description": "NOAA West Coast critical habitat",
      "agency": "NOAA Fisheries",
      "accent": "sky",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "nrcs_soils",
      "description": "USDA-NRCS SSURGO soil and farmland screening",
      "agency": "USDA Natural Resources Conservation Service",
      "accent": "emerald",
      "credentials": [],
      "toolCount": 3
    },
    {
      "name": "nrhp",
      "description": "National Register of Historic Places properties",
      "agency": "National Park Service",
      "accent": "orange",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "padus",
      "description": "PAD-US protected areas and land management",
      "agency": "U.S. Geological Survey",
      "accent": "cyan",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "pcsrf",
      "description": "NOAA species, habitat, and recovery-program datasets",
      "agency": "NOAA Fisheries",
      "accent": "sky",
      "credentials": [],
      "toolCount": 4
    },
    {
      "name": "tigerweb_counties",
      "description": "Census TIGERweb county intersections",
      "agency": "U.S. Census Bureau",
      "accent": "indigo",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "tribal",
      "description": "Census AIANNHA tribal lands",
      "agency": "U.S. Census Bureau",
      "accent": "orange",
      "credentials": [],
      "toolCount": 1
    },
    {
      "name": "usace",
      "description": "USACE districts and wetland regions",
      "agency": "U.S. Army Corps of Engineers",
      "accent": "stone",
      "credentials": [],
      "toolCount": 4
    }
  ],
  "tools": [
    {
      "server": "blm",
      "name": "get_blm_land_use_plans_in_roi",
      "purpose": "Identify BLM approved land use plans intersecting the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "blm",
      "name": "get_blm_national_monuments_in_roi",
      "purpose": "Identify BLM National Monuments and NCAs intersecting the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "blm",
      "name": "get_blm_wilderness_areas_in_roi",
      "purpose": "Identify BLM designated wilderness areas intersecting the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "census",
      "name": "get_acs_socioeconomic_indicators_in_roi",
      "purpose": "Query ACS socioeconomic indicators for counties within a region of interest.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "include_industries",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Include top industries/occupations data (default: False)",
          "choices": []
        },
        {
          "name": "top_n",
          "type": "number",
          "required": false,
          "default": "2",
          "description": "Number of top industries or occupations per county, valid range 1 to 10.",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_browse_structure",
      "purpose": "Browse the table of contents at any level of the CFR hierarchy.",
      "parameters": [
        {
          "name": "title",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "CFR title number (1-50). None = list titles.",
          "choices": []
        },
        {
          "name": "part",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "Part number; restricts the returned subtree to that part.",
          "choices": []
        },
        {
          "name": "as_of",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "YYYY-MM-DD; None = current (eCFR ~1 day lag).",
          "choices": []
        },
        {
          "name": "max_depth",
          "type": "number",
          "required": false,
          "default": "3",
          "description": "1=parts, 2=subparts, 3=sections (default), 4=paragraphs. Children below this depth are elided with `children_truncated=true`.",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_compare_versions",
      "purpose": "Diff a single CFR section between two dates, paragraph by paragraph.",
      "parameters": [
        {
          "name": "citation",
          "type": "string",
          "required": true,
          "default": "",
          "description": "CFR citation. Must resolve to a section.",
          "choices": []
        },
        {
          "name": "date_a",
          "type": "string",
          "required": true,
          "default": "",
          "description": "Earlier date YYYY-MM-DD.",
          "choices": []
        },
        {
          "name": "date_b",
          "type": "string",
          "required": true,
          "default": "",
          "description": "Later date YYYY-MM-DD.",
          "choices": []
        },
        {
          "name": "paragraph_path",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "Restrict the diff to a subtree, e.g. [\"a\", \"4\", \"ii\"].",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_history",
      "purpose": "All amendment events for a citation in a date window.",
      "parameters": [
        {
          "name": "citation",
          "type": "string",
          "required": true,
          "default": "",
          "description": "CFR citation. See examples above.",
          "choices": []
        },
        {
          "name": "start_date",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "YYYY-MM-DD. Default: 5 years ago.",
          "choices": []
        },
        {
          "name": "end_date",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "YYYY-MM-DD. Default: today.",
          "choices": []
        },
        {
          "name": "substantive_only",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "If True, drop editorial-only events.",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_resolve_citation",
      "purpose": "Resolve a CFR citation (any depth) to its current verbatim text.",
      "parameters": [
        {
          "name": "citation",
          "type": "string",
          "required": true,
          "default": "",
          "description": "Citation string. Examples: \"43 CFR 46.215\", \"33 CFR 328.3(a)\", \"40 CFR 261.4(a)(20)(ii)(B)(1)\".",
          "choices": []
        },
        {
          "name": "as_of",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "YYYY-MM-DD; None = current (eCFR ~1 day lag).",
          "choices": []
        },
        {
          "name": "include_ancestry",
          "type": "boolean",
          "required": false,
          "default": "true",
          "description": "Include the title->section breadcrumb (default True).",
          "choices": []
        },
        {
          "name": "include_full_section",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Also return the entire section tree alongside the addressed node. Useful when you want sibling context or an explicit full-section payload.",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_resolve_executive_order",
      "purpose": "Resolve an Executive Order number to its Federal Register record.",
      "parameters": [
        {
          "name": "eo_number",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Normalized Executive Order number, e.g. 14008.",
          "choices": []
        },
        {
          "name": "year",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "Optional publication year hint.",
          "choices": []
        },
        {
          "name": "include_document",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Include the full raw Federal Register document JSON.",
          "choices": []
        },
        {
          "name": "include_body",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Include raw full-text body from the FR/GovInfo text URL. This also includes the full raw document so the body text is visible.",
          "choices": []
        },
        {
          "name": "max_body_chars",
          "type": "number",
          "required": false,
          "default": "50000",
          "description": "Truncate body text when include_body is true.",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_resolve_fr_citation",
      "purpose": "Resolve a Federal Register citation to its source document and summary.",
      "parameters": [
        {
          "name": "citation",
          "type": "string",
          "required": true,
          "default": "",
          "description": "Federal Register citation, e.g. \"90 FR 29498\" or \"90 Fed. Reg. 29498\".",
          "choices": []
        },
        {
          "name": "include_body",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Also inline the full document text from the GPO raw-text endpoint. Default False (returns compact metadata + abstract). Set True only when the full rule text is needed -- bodies can be large.",
          "choices": []
        },
        {
          "name": "max_body_chars",
          "type": "number",
          "required": false,
          "default": "50000",
          "description": "Truncate inlined body text to this many characters when include_body is True (default 50000).",
          "choices": []
        }
      ]
    },
    {
      "server": "cfr",
      "name": "cfr_rulemaking",
      "purpose": "Federal Register documents that touched a CFR citation, plus optional correlation to specific eCFR amendment events.",
      "parameters": [
        {
          "name": "cfr_title",
          "type": "number",
          "required": true,
          "default": "",
          "description": "CFR title number (e.g. 33, 40, 50).",
          "choices": []
        },
        {
          "name": "cfr_part",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "Optional part filter.",
          "choices": []
        },
        {
          "name": "document_types",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "List from {\"RULE\",\"PRORULE\",\"NOTICE\"}. Default: [\"RULE\",\"PRORULE\"] for document search, [\"RULE\"] when correlating to actual eCFR amendments unless explicitly provided.",
          "choices": []
        },
        {
          "name": "start_date",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "YYYY-MM-DD; default 365 days ago.",
          "choices": []
        },
        {
          "name": "end_date",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "YYYY-MM-DD; default today.",
          "choices": []
        },
        {
          "name": "correlate_with_amendments",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "If True, fetch eCFR amendment events in the same window and pair each with the strongest FR document(s).",
          "choices": []
        },
        {
          "name": "substantive_only",
          "type": "boolean",
          "required": false,
          "default": "true",
          "description": "When correlating, include only eCFR amendment events with `substantive=true` by default. Set False for editorial changes.",
          "choices": []
        },
        {
          "name": "correlation_tolerance_days",
          "type": "number",
          "required": false,
          "default": "7",
          "description": "Days tolerance for the date-matching window (default 7). Tighten to 1-3 for stricter joins.",
          "choices": []
        },
        {
          "name": "include_body_for",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "List of FR document numbers whose full body text should be inlined in the response (e.g. [\"2022-27225\"]).",
          "choices": []
        },
        {
          "name": "max_results",
          "type": "number",
          "required": false,
          "default": "50",
          "description": "Cap on FR documents returned (default 50; FR API max 1000).",
          "choices": []
        }
      ]
    },
    {
      "server": "efh",
      "name": "get_efh_areas",
      "purpose": "Query NOAA for Essential Fish Habitat (EFH) areas within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "efh",
      "name": "get_efh_hapc",
      "purpose": "Query NOAA for Habitat Areas of Particular Concern (HAPC) within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "efh",
      "name": "get_efh_hms_cps_groundfish",
      "purpose": "Query NOAA for HMS, Coastal Pelagic, and Groundfish EFH within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "efh",
      "name": "get_efh_salmon",
      "purpose": "Query NOAA for salmon Essential Fish Habitat by HUC-8 watershed within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "epa_acres",
      "name": "get_epa_acres_properties_in_roi",
      "purpose": "Query EPA ACRES Brownfields property records within a region of interest.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "max_results",
          "type": "number",
          "required": false,
          "default": "100",
          "description": "Maximum property records to return, valid range 1 to 100 (default: 100).",
          "choices": []
        },
        {
          "name": "result_offset",
          "type": "number",
          "required": false,
          "default": "0",
          "description": "Zero-based offset into the nearest-first property list, valid range 0 to 9999 (default: 0).",
          "choices": []
        }
      ]
    },
    {
      "server": "epa_aqs",
      "name": "analyze_epa_aqs_air_quality_baseline",
      "purpose": "Analyze EPA AQS air quality baseline data for NEPA screening.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "begin_year",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "First year for baseline period (default: last year)",
          "choices": []
        },
        {
          "name": "end_year",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "Last year for baseline period (default: last year)",
          "choices": []
        },
        {
          "name": "pollutants",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "List of pollutants to analyze. Default: all criteria pollutants",
          "choices": []
        }
      ]
    },
    {
      "server": "epa_aqs",
      "name": "get_epa_aqs_air_quality_monitors",
      "purpose": "Identify EPA air quality monitoring stations within a region of interest.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "year",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "Year to query for active monitors (default: current year)",
          "choices": []
        },
        {
          "name": "pollutants",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "List of pollutants to query (PM2.5, PM10, Ozone, NO2, SO2, CO). Default: all",
          "choices": []
        }
      ]
    },
    {
      "server": "epa_aqs",
      "name": "get_epa_aqs_annual_air_quality",
      "purpose": "Get annual air quality statistics for criteria pollutants in a region.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "begin_year",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "First year to query (default: last year)",
          "choices": []
        },
        {
          "name": "end_year",
          "type": "number",
          "required": false,
          "default": "null",
          "description": "Last year to query (default: last year)",
          "choices": []
        },
        {
          "name": "pollutants",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "List of pollutants to query. Default: all criteria pollutants",
          "choices": []
        }
      ]
    },
    {
      "server": "esa_ranges",
      "name": "get_esa_species_ranges_in_roi",
      "purpose": "Query NOAA for ESA-listed species ranges within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "fema_nfhl",
      "name": "analyze_fema_nfhl_flood_hazard_screening",
      "purpose": "Screen FEMA NFHL flood-hazard layers for a location.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "radius_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Search radius in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "fema_nfhl",
      "name": "get_fema_nfhl_flood_zones_in_roi",
      "purpose": "Query FEMA flood hazard zones within a radius of a location.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "radius_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Search radius in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "fema_nfhl",
      "name": "get_fema_nfhl_levees_in_roi",
      "purpose": "Query FEMA levee locations within a radius of a location.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "radius_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Search radius in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "fema_nfhl",
      "name": "get_fema_nfhl_water_areas_in_roi",
      "purpose": "Query FEMA water areas (rivers, lakes, etc.) within a radius.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "radius_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Search radius in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "gbif",
      "name": "get_gbif_species_list_by_county",
      "purpose": "Query GBIF for threatened & endangered species presence by county.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "threatened_only",
          "type": "boolean",
          "required": false,
          "default": "true",
          "description": "Only return threatened/endangered species (default: true)",
          "choices": []
        },
        {
          "name": "min_year",
          "type": "number",
          "required": false,
          "default": "2015",
          "description": "Minimum observation year (default: 2015)",
          "choices": []
        },
        {
          "name": "max_records_per_county",
          "type": "number",
          "required": false,
          "default": "1000",
          "description": "Maximum records per county, valid range 1 to 5000.",
          "choices": []
        }
      ]
    },
    {
      "server": "gbif",
      "name": "get_gbif_species_occurrences_in_roi",
      "purpose": "Query GBIF for georeferenced threatened & endangered species occurrences.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "threatened_only",
          "type": "boolean",
          "required": false,
          "default": "true",
          "description": "Only return threatened/endangered species (default: true)",
          "choices": []
        },
        {
          "name": "min_year",
          "type": "number",
          "required": false,
          "default": "2015",
          "description": "Minimum observation year (default: 2015)",
          "choices": []
        },
        {
          "name": "max_records",
          "type": "number",
          "required": false,
          "default": "1000",
          "description": "Maximum records to retrieve, valid range 1 to 5000.",
          "choices": []
        }
      ]
    },
    {
      "server": "gis",
      "name": "calculate_roi_area",
      "purpose": "Compute ROI area in square miles and acres for a given buffer.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "gis",
      "name": "get_roi_geojson",
      "purpose": "Return ROI GeoJSON for the requested buffer as formatted JSON.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "gis",
      "name": "summarize_roi_buffer",
      "purpose": "Generate a human-readable ROI summary from lat/lon with a configurable buffer.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "project_name",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "Optional project identifier",
          "choices": []
        }
      ]
    },
    {
      "server": "ipac",
      "name": "get_ipac_resources_in_roi",
      "purpose": "Query USFWS IPaC for ESA species, migratory birds, wetlands, critical habitat, and refuge data.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "map_composer",
      "name": "compose_environmental_map",
      "purpose": "Create an interactive environmental screening map as a local HTML artifact.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Circular point-buffer radius in miles, valid range 0.1 to 100.",
          "choices": []
        },
        {
          "name": "profile",
          "type": "string",
          "required": false,
          "default": "\"full\"",
          "description": "Named layer profile. The default full profile requests all 32 layers; explicit layers override the selected profile.",
          "choices": [
            "screening",
            "biological",
            "water",
            "lands",
            "full"
          ]
        },
        {
          "name": "layers",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "Optional explicit Map Composer layer IDs; overrides profile when provided.",
          "choices": []
        },
        {
          "name": "title",
          "type": "string",
          "required": false,
          "default": "null",
          "description": "Optional plain-text map title, maximum 200 characters.",
          "choices": []
        },
        {
          "name": "basemap",
          "type": "string",
          "required": false,
          "default": "\"CartoDB Positron\"",
          "description": "Interactive basemap style. Defaults to CartoDB Positron.",
          "choices": [
            "CartoDB Positron",
            "OpenStreetMap",
            "USGS",
            "Satellite"
          ]
        },
        {
          "name": "include_species_data",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Enrich county popups with recent GBIF species occurrence data.",
          "choices": []
        }
      ]
    },
    {
      "server": "map_composer",
      "name": "export_all_layers_geojson",
      "purpose": "Export selected environmental map layers as one provenance-rich GeoJSON artifact.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Circular point-buffer radius in miles, valid range 0.1 to 100.",
          "choices": []
        },
        {
          "name": "profile",
          "type": "string",
          "required": false,
          "default": "\"full\"",
          "description": "Named layer profile. The default full profile requests all 32 layers; explicit layers override the selected profile.",
          "choices": [
            "screening",
            "biological",
            "water",
            "lands",
            "full"
          ]
        },
        {
          "name": "layers",
          "type": "array",
          "required": false,
          "default": "null",
          "description": "Optional explicit Map Composer layer IDs; overrides profile when provided.",
          "choices": []
        },
        {
          "name": "include_species_data",
          "type": "boolean",
          "required": false,
          "default": "false",
          "description": "Enrich county properties with recent GBIF species occurrence data.",
          "choices": []
        }
      ]
    },
    {
      "server": "map_composer",
      "name": "list_available_layers",
      "purpose": "List Map Composer layer IDs, source publishers, review uses, and profiles.",
      "parameters": []
    },
    {
      "server": "nepa_assist",
      "name": "analyze_nepa_assist_screening",
      "purpose": "Analyze EPA NEPAssist environmental screening layers for a location.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        },
        {
          "name": "project_title",
          "type": "string",
          "required": false,
          "default": "\"\"",
          "description": "Optional project title/name for the screening",
          "choices": []
        }
      ]
    },
    {
      "server": "noaa",
      "name": "get_noaa_critical_habitat_in_roi",
      "purpose": "Query NOAA for West Coast Region ESA critical habitat within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "nrcs_soils",
      "name": "analyze_nrcs_ssurgo_soil_constraints",
      "purpose": "Summarize NRCS SSURGO soil indicators relevant to early siting review.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "1.0",
          "description": "Soil-screening buffer in miles, valid range 0.1 to 10.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "nrcs_soils",
      "name": "get_nrcs_ssurgo_farmland_classification_in_roi",
      "purpose": "Get exact NRCS SSURGO farmland classifications within a project-area buffer.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "1.0",
          "description": "Soil-screening buffer in miles, valid range 0.1 to 10.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "nrcs_soils",
      "name": "get_nrcs_ssurgo_mapunits_in_roi",
      "purpose": "Get USDA-NRCS SSURGO soil map units intersecting a project-area buffer.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "1.0",
          "description": "Soil-screening buffer in miles, valid range 0.1 to 10.0.",
          "choices": []
        },
        {
          "name": "max_results",
          "type": "number",
          "required": false,
          "default": "50",
          "description": "Maximum map-unit records to return, valid range 1 to 100 (default: 50).",
          "choices": []
        },
        {
          "name": "result_offset",
          "type": "number",
          "required": false,
          "default": "0",
          "description": "Zero-based offset into map units ordered by intersected ROI acreage, valid range 0 to 499.",
          "choices": []
        }
      ]
    },
    {
      "server": "nrhp",
      "name": "get_nrhp_properties_in_roi",
      "purpose": "Query NRHP for historic properties within the ROI for Section 106 NHPA screening.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "padus",
      "name": "get_padus_protected_areas_in_roi",
      "purpose": "Query PAD-US protected-area records within a region of interest.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "pcsrf",
      "name": "get_atlantic_salmon_efh_hapc_in_roi",
      "purpose": "Query Atlantic salmon EFH/HAPC buffers within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "pcsrf",
      "name": "get_noaa_all_species_ranges_in_roi",
      "purpose": "Query NOAA All_Species_Ranges records within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "pcsrf",
      "name": "get_noaa_critical_habitat_20210904_in_roi",
      "purpose": "Query NOAA critical-habitat snapshot records within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "pcsrf",
      "name": "get_pcsrf_projects_in_roi",
      "purpose": "Query NOAA for PCSRF salmon recovery projects within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "tigerweb_counties",
      "name": "get_tigerweb_counties_in_roi",
      "purpose": "Identify all counties intersecting an ROI buffer using TIGERweb.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "tribal",
      "name": "get_tribal_lands_in_roi",
      "purpose": "Identify tribal lands intersecting the ROI using TIGERweb AIANNHA datasets.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "usace",
      "name": "analyze_usace_jurisdiction",
      "purpose": "Comprehensive USACE jurisdictional analysis for Section 404 compliance.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "usace",
      "name": "get_usace_regulatory_district",
      "purpose": "Identify which USACE district has regulatory jurisdiction over the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "usace",
      "name": "get_usace_wetland_regions_in_roi",
      "purpose": "Get wetland delineation regions within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    },
    {
      "server": "usace",
      "name": "get_usace_wetland_subregions_in_roi",
      "purpose": "Get wetland subregion classifications within the ROI.",
      "parameters": [
        {
          "name": "latitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Latitude in decimal degrees (WGS84), valid range -90 to 90.",
          "choices": []
        },
        {
          "name": "longitude",
          "type": "number",
          "required": true,
          "default": "",
          "description": "Longitude in decimal degrees (WGS84), valid range -180 to 180.",
          "choices": []
        },
        {
          "name": "buffer_miles",
          "type": "number",
          "required": false,
          "default": "25.0",
          "description": "Buffer distance in miles, valid range 0.1 to 100.0.",
          "choices": []
        }
      ]
    }
  ],
  "mapComposer": {
    "layers": [
      {
        "id": "roi",
        "category": "Region of Interest",
        "title": "Project Location and Buffer",
        "source": "User-specified coordinates (calculated via ArcGIS geometry service)",
        "sourceUrl": "https://utility.arcgisonline.com/arcgis/rest/services/Geometry/GeometryServer",
        "sourceLinkLabel": "Geometry service",
        "geometry": "Point + Polygon",
        "reviewUse": "Defines the project area used for map-based screening",
        "profiles": [
          "biological",
          "full",
          "lands",
          "screening",
          "water"
        ]
      },
      {
        "id": "tribal_lands",
        "category": "Tribal",
        "title": "Tribal Lands",
        "source": "U.S. Census Bureau TIGERweb AIANNHA",
        "sourceUrl": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/AIANNHA/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides geographic context for early coordination and project-area review",
        "profiles": [
          "full",
          "screening"
        ]
      },
      {
        "id": "counties",
        "category": "Administrative",
        "title": "County Boundaries",
        "source": "U.S. Census Bureau TIGERweb",
        "sourceUrl": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides administrative context for scoping and related county-level data",
        "profiles": [
          "full",
          "screening"
        ]
      },
      {
        "id": "critical_habitat",
        "category": "Species and Habitat",
        "title": "Critical Habitat",
        "source": "U.S. Fish and Wildlife Service Critical Habitat FeatureServer",
        "sourceUrl": "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/USFWS_Critical_Habitat/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped habitat for closer biological-resource review",
        "profiles": [
          "biological",
          "full",
          "screening"
        ]
      },
      {
        "id": "wildlife_refuges",
        "category": "Species and Habitat",
        "title": "National Wildlife Refuges",
        "source": "U.S. Fish and Wildlife Service National Wildlife Refuge System",
        "sourceUrl": "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/National_Wildlife_Refuge_System_Boundaries/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies refuge boundaries for land and resource context",
        "profiles": [
          "biological",
          "full",
          "screening"
        ]
      },
      {
        "id": "usace_districts",
        "category": "Water Resources (USACE)",
        "title": "USACE Regulatory Districts",
        "source": "U.S. Army Corps of Engineers regulatory boundary service",
        "sourceUrl": "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/usace_cw_districts/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies the relevant USACE district for agency follow-up",
        "profiles": [
          "full",
          "screening",
          "water"
        ]
      },
      {
        "id": "wetland_regions",
        "category": "Water Resources (USACE)",
        "title": "Wetland Delineation Regions",
        "source": "USACE COE wetland regions service",
        "sourceUrl": "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_regions/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides regional wetland-delineation method context",
        "profiles": [
          "full",
          "screening",
          "water"
        ]
      },
      {
        "id": "wetland_subregions",
        "category": "Water Resources (USACE)",
        "title": "Wetland Delineation Subregions",
        "source": "USACE COE wetland subregions service",
        "sourceUrl": "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_subregions/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides subregional wetland-delineation context",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "nhd_lakes",
        "category": "Water Resources (USGS NHD)",
        "title": "Lakes and Ponds",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Maps lakes and ponds for water-resource screening",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "nhd_reservoirs",
        "category": "Water Resources (USGS NHD)",
        "title": "Reservoirs",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Maps reservoirs for water-resource and infrastructure context",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "nhd_estuaries",
        "category": "Water Resources (USGS NHD)",
        "title": "Estuaries",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Maps estuarine features for coastal and water-resource context",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "nhd_ice_masses",
        "category": "Water Resources (USGS NHD)",
        "title": "Glaciers and Ice Masses",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Maps glaciers and ice masses for baseline environmental context",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "nhd_perennial_streams",
        "category": "Water Resources (USGS NHD)",
        "title": "Perennial Stream Centerlines",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polyline",
        "reviewUse": "Maps perennial hydrography for water-resource screening",
        "profiles": [
          "full",
          "screening",
          "water"
        ]
      },
      {
        "id": "nhd_stream_areas",
        "category": "Water Resources (USGS NHD)",
        "title": "River and Stream Areas",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Maps river and stream areas for water-resource screening",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "nhd_infrastructure",
        "category": "Water Resources (USGS NHD)",
        "title": "Water Infrastructure (Dams, Springs, Gages, Wells, Intakes)",
        "source": "USGS National Hydrography Dataset",
        "sourceUrl": "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Point",
        "reviewUse": "Provides water-infrastructure and monitoring context",
        "profiles": [
          "full",
          "water"
        ]
      },
      {
        "id": "federal_lands",
        "category": "Federal Lands (non-BLM)",
        "title": "Federal Protected Lands",
        "source": "USGS Protected Areas Database (PAD-US 4.1), filtered to non-BLM federal managers",
        "sourceUrl": "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped federal land managers and protected areas",
        "profiles": [
          "full",
          "lands",
          "screening"
        ]
      },
      {
        "id": "usfs_forests",
        "category": "Federal Lands (non-BLM)",
        "title": "National Forest System Boundaries",
        "source": "USDA Forest Service Enterprise Data Warehouse",
        "sourceUrl": "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides National Forest System and land-management context",
        "profiles": [
          "full",
          "lands",
          "screening"
        ]
      },
      {
        "id": "usfs_roadless_areas",
        "category": "Federal Lands (non-BLM)",
        "title": "Inventoried Roadless Areas (2001 Rule)",
        "source": "USDA Forest Service Enterprise Data Warehouse",
        "sourceUrl": "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_InventoriedRoadlessAreas2001_01/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies inventoried roadless areas for land-use context",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "nps_boundaries",
        "category": "Federal Lands (non-BLM)",
        "title": "National Park Service Unit Boundaries",
        "source": "NPS Land Resources Division Boundary and Tract Data Service",
        "sourceUrl": "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services/NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies National Park Service units for land and resource context",
        "profiles": [
          "full",
          "lands",
          "screening"
        ]
      },
      {
        "id": "blm_managed_lands",
        "category": "Federal Lands (BLM)",
        "title": "BLM Surface Management",
        "source": "USGS Protected Areas Database (PAD-US 4.1), filtered to BLM",
        "sourceUrl": "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped BLM-managed lands",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "blm_land_use_plans",
        "category": "Federal Lands (BLM)",
        "title": "Approved Land Use Plans (RMPs)",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_Use_Plans_Approved_2022/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides approved BLM land-use-plan context",
        "profiles": [
          "full",
          "lands",
          "screening"
        ]
      },
      {
        "id": "blm_plans_in_progress",
        "category": "Federal Lands (BLM)",
        "title": "Land Use Plans Under Revision",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Revision_Development_Land_Use_Plans/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies BLM planning areas with revisions in progress",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "blm_wilderness_study_areas",
        "category": "Federal Lands (BLM)",
        "title": "Wilderness Study Areas",
        "source": "BLM National Conservation Lands System",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/NLCS_Wilderness_Study_Areas/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped wilderness study areas",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "blm_national_monuments",
        "category": "Federal Lands (BLM)",
        "title": "National Monuments and Conservation Areas",
        "source": "BLM National Conservation Lands System",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_National_Monuments_National_Conservation_Areas_Polygons/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped monuments and conservation areas",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "blm_rights_of_way",
        "category": "Federal Lands (BLM)",
        "title": "No Surface Occupancy Restrictions",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/Rights_of_Way/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides mapped right-of-way and surface-use context",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "grsg_habitat",
        "category": "Habitat Protection",
        "title": "Greater Sage-Grouse Habitat Management Areas",
        "source": "BLM National ArcGIS Portal (2026 ROD)",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_GRSG_ROD_HabitatMgmtAreas_Feb_2026/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides greater sage-grouse habitat-management context",
        "profiles": [
          "biological",
          "full"
        ]
      },
      {
        "id": "sagebrush_focal_areas",
        "category": "Habitat Protection",
        "title": "Sagebrush Focal Areas",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_GRSG_Sagebrush_Focal_Areas_v2/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped sagebrush focal areas",
        "profiles": [
          "biological",
          "full"
        ]
      },
      {
        "id": "wild_horse_hma",
        "category": "Habitat Protection",
        "title": "Wild Horse and Burro Herd Management Areas",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Wild_Horse_and_Burro_Heard_Mgmt_Area_Polygons/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies wild horse and burro management areas",
        "profiles": [
          "biological",
          "full"
        ]
      },
      {
        "id": "national_trails",
        "category": "Contextual",
        "title": "National Scenic and Historic Trails",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/National_Scenic_and_Historic_Trails_NSHT/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polyline",
        "reviewUse": "Provides national trail and corridor context",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "fire_perimeters",
        "category": "Contextual",
        "title": "Historical Fire Perimeters",
        "source": "National Interagency Fire Center authoritative fire history",
        "sourceUrl": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Provides historical disturbance context",
        "profiles": [
          "full"
        ]
      },
      {
        "id": "lwcf_lands",
        "category": "Contextual",
        "title": "Land and Water Conservation Fund Parcels",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_and_Water_Conservation_Fund_LWCF_Polygons/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies mapped Land and Water Conservation Fund parcels",
        "profiles": [
          "full",
          "lands"
        ]
      },
      {
        "id": "eis_boundaries",
        "category": "Contextual",
        "title": "Western US EIS Planning Boundaries",
        "source": "BLM National ArcGIS Portal",
        "sourceUrl": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_EIS_Boundaries/FeatureServer",
        "sourceLinkLabel": "Source service",
        "geometry": "Polygon",
        "reviewUse": "Identifies prior EIS planning boundaries for contextual review",
        "profiles": [
          "full",
          "lands"
        ]
      }
    ],
    "categories": [
      "Region of Interest",
      "Tribal",
      "Administrative",
      "Species and Habitat",
      "Water Resources (USACE)",
      "Water Resources (USGS NHD)",
      "Federal Lands (non-BLM)",
      "Federal Lands (BLM)",
      "Habitat Protection",
      "Contextual"
    ],
    "profiles": [
      {
        "id": "screening",
        "count": 12
      },
      {
        "id": "biological",
        "count": 6
      },
      {
        "id": "water",
        "count": 11
      },
      {
        "id": "lands",
        "count": 14
      },
      {
        "id": "full",
        "count": 32
      }
    ]
  }
};
