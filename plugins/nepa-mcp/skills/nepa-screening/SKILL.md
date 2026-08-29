---
name: nepa-screening
description: Use NEPA-MCP for project-area environmental screening, biological and cultural resources, jurisdiction, soils, protected lands, flood risk, air quality, and regulatory research.
---

# NEPA Screening

Use this skill for NEPA or ESA screening, environmental review scoping, project-area baseline research, jurisdictional context, or environmental regulatory lookup.

## Establish the project area

Before location-scoped calls, confirm or derive latitude, longitude, and buffer distance in miles. Use `gis` tools to summarize the ROI, return GeoJSON, or calculate area. Use `tigerweb_counties` for intersecting counties and `tribal` for AIANNHA tribal lands.

## Select authoritative datasets

- Use `census` for ACS socioeconomic indicators.
- Use `ipac` for USFWS species, critical habitat, migratory birds, wetlands, refuges, hatcheries, and related resources.
- Use `esa_ranges` for NOAA ESA-listed species ranges.
- Use `noaa` for NOAA West Coast critical habitat.
- Use `efh` for Essential Fish Habitat and Habitat Areas of Particular Concern.
- Use `pcsrf` for NOAA species ranges, critical habitat, salmon EFH/HAPC, and recovery projects.
- Use `gbif` for biodiversity occurrences and county species lists.
- Use `fema_nfhl` for flood zones, levees, water areas, and flood-risk summaries.
- Use `epa_aqs` for air monitors, annual air-quality data, and NAAQS screening context.
- Use `nepa_assist` for EPA NEPAssist screening categories.
- Use `nrcs_soils` for SSURGO soil map units, drainage and hydrologic-group
  indicators, restrictive layers, erosion factors, and farmland classifications.
  Treat results as soil-survey screening, not geotechnical advice, wetland
  delineation, infiltration testing, or an agency farmland determination.
- Use `epa_acres` for identifiable EPA ACRES Brownfields property records; treat
  results as grant-reported screening data, not a complete contaminated-site
  inventory. Dense results are nearest-first and paginated; follow the returned
  `result_offset` instruction when the complete property list is needed.
- Use `padus` for protected areas, ownership, management, and conservation status.
- Use `blm` for BLM land use plans, wilderness areas, and national monuments.
- Use `usace` for Corps districts and wetland delineation regions.
- Use `nrhp` for National Register of Historic Places properties.
- Use `cfr` for current eCFR text, regulatory history, Federal Register citations, and executive orders.

## Create map artifacts

Use `map_composer` after establishing the project area when an interactive
visual or GIS-ready export will help communicate the screening context.

- Use the default `full` profile for general-purpose maps, comprehensive
  screening, demonstrations, and publication-oriented visuals.
- Use `screening` when the user prefers a faster balanced overview, and use
  `biological`, `water`, or `lands` for explicitly focused maps.
- Use explicit layer IDs when only selected findings need to be visualized.
- Treat failed or partial map layers as unavailable data, not as no-hit findings.
- Report the map's requested, rendered, empty, partial, and failed layer counts;
  do not describe catalog size as though every layer intersected the ROI.
- Generated HTML contains the selected vector features but needs network access
  for basemap tiles and standard web-map assets.

## Credentials

Most tools use public APIs. Census requires `CENSUS_API_KEY`; EPA AQS requires `EPA_AQS_EMAIL` and `EPA_AQS_API_KEY`. Never request that credentials be pasted into chat and never print credential values. If a credential is missing, identify only its variable name and continue with independent datasets.

## Reporting

Keep retrieved facts tied to their source systems and observation dates. Distinguish screening indicators from legal conclusions, formal agency determinations, consultation requirements, and professional judgments. Explain geographic coverage limitations when a no-hit result may mean the queried service does not cover the project location.
