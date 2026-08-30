# MCP Tool Catalog

NEPA MCP provides 22 independent servers with 53 tools. Use this catalog to choose the smallest set of servers needed for a workflow.

This file is generated from the server registry and each server's live MCP `tools/list` contract. Do not edit it manually. Regenerate it with `uv run python scripts/generate_tool_catalog.py`; add `--check` to verify it without writing.

| Server | Tool | Purpose |
|---|---|---|
| `blm` | `get_blm_land_use_plans_in_roi` | Identify BLM approved land use plans intersecting the ROI. |
| `blm` | `get_blm_national_monuments_in_roi` | Identify BLM National Monuments and NCAs intersecting the ROI. |
| `blm` | `get_blm_wilderness_areas_in_roi` | Identify BLM designated wilderness areas intersecting the ROI. |
| `blm_mlrs` | `get_blm_mlrs_energy_leases_in_roi` | Screen BLM MLRS geothermal and oil-and-gas lease case records. |
| `blm_mlrs` | `get_blm_mlrs_land_use_authorizations_in_roi` | Screen public BLM MLRS right-of-way, lease, permit, and easement case records. |
| `blm_mlrs` | `get_blm_mlrs_locatable_operations_in_roi` | Screen BLM MLRS locatable-mineral plans of operations and notices. |
| `census` | `get_acs_socioeconomic_indicators_in_roi` | Query ACS socioeconomic indicators for counties within a region of interest. |
| `cfr` | `cfr_browse_structure` | Browse the table of contents at any level of the CFR hierarchy. |
| `cfr` | `cfr_compare_versions` | Diff a single CFR section between two dates, paragraph by paragraph. |
| `cfr` | `cfr_history` | All amendment events for a citation in a date window. |
| `cfr` | `cfr_resolve_citation` | Resolve a CFR citation (any depth) to its current verbatim text. |
| `cfr` | `cfr_resolve_executive_order` | Resolve an Executive Order number to its Federal Register record. |
| `cfr` | `cfr_resolve_fr_citation` | Resolve a Federal Register citation to its source document and summary. |
| `cfr` | `cfr_rulemaking` | Federal Register documents that touched a CFR citation, plus optional correlation to specific eCFR amendment events. |
| `efh` | `get_efh_areas` | Query NOAA for Essential Fish Habitat (EFH) areas within the ROI. |
| `efh` | `get_efh_hapc` | Query NOAA for Habitat Areas of Particular Concern (HAPC) within the ROI. |
| `efh` | `get_efh_hms_cps_groundfish` | Query NOAA for HMS, Coastal Pelagic, and Groundfish EFH within the ROI. |
| `efh` | `get_efh_salmon` | Query NOAA for salmon Essential Fish Habitat by HUC-8 watershed within the ROI. |
| `epa_acres` | `get_epa_acres_properties_in_roi` | Query EPA ACRES Brownfields property records within a region of interest. |
| `epa_aqs` | `analyze_epa_aqs_air_quality_baseline` | Analyze EPA AQS air quality baseline data for NEPA screening. |
| `epa_aqs` | `get_epa_aqs_air_quality_monitors` | Identify EPA air quality monitoring stations within a region of interest. |
| `epa_aqs` | `get_epa_aqs_annual_air_quality` | Get annual air quality statistics for criteria pollutants in a region. |
| `esa_ranges` | `get_esa_species_ranges_in_roi` | Query NOAA for ESA-listed species ranges within the ROI. |
| `fema_nfhl` | `analyze_fema_nfhl_flood_hazard_screening` | Screen FEMA NFHL flood-hazard layers for a location. |
| `fema_nfhl` | `get_fema_nfhl_flood_zones_in_roi` | Query FEMA flood hazard zones within a radius of a location. |
| `fema_nfhl` | `get_fema_nfhl_levees_in_roi` | Query FEMA levee locations within a radius of a location. |
| `fema_nfhl` | `get_fema_nfhl_water_areas_in_roi` | Query FEMA water areas (rivers, lakes, etc.) within a radius. |
| `gbif` | `get_gbif_species_list_by_county` | Query GBIF for threatened & endangered species presence by county. |
| `gbif` | `get_gbif_species_occurrences_in_roi` | Query GBIF for georeferenced threatened & endangered species occurrences. |
| `gis` | `calculate_roi_area` | Compute ROI area in square miles and acres for a given buffer. |
| `gis` | `get_roi_geojson` | Return ROI GeoJSON for the requested buffer as formatted JSON. |
| `gis` | `summarize_roi_buffer` | Generate a human-readable ROI summary from lat/lon with a configurable buffer. |
| `ipac` | `get_ipac_resources_in_roi` | Query USFWS IPaC for ESA species, migratory birds, wetlands, critical habitat, and refuge data. |
| `map_composer` | `compose_environmental_map` | Create an interactive environmental screening map as a local HTML artifact. |
| `map_composer` | `export_all_layers_geojson` | Export selected environmental map layers as one provenance-rich GeoJSON artifact. |
| `map_composer` | `list_available_layers` | List Map Composer layer IDs, source publishers, review uses, and profiles. |
| `nepa_assist` | `analyze_nepa_assist_screening` | Analyze EPA NEPAssist environmental screening layers for a location. |
| `noaa` | `get_noaa_critical_habitat_in_roi` | Query NOAA for West Coast Region ESA critical habitat within the ROI. |
| `nrcs_soils` | `analyze_nrcs_ssurgo_soil_constraints` | Summarize NRCS SSURGO soil indicators relevant to early siting review. |
| `nrcs_soils` | `get_nrcs_ssurgo_farmland_classification_in_roi` | Get exact NRCS SSURGO farmland classifications within a project-area buffer. |
| `nrcs_soils` | `get_nrcs_ssurgo_mapunits_in_roi` | Get USDA-NRCS SSURGO soil map units intersecting a project-area buffer. |
| `nrhp` | `get_nrhp_properties_in_roi` | Query NRHP for historic properties within the ROI for Section 106 NHPA screening. |
| `padus` | `get_padus_protected_areas_in_roi` | Query PAD-US protected-area records within a region of interest. |
| `pcsrf` | `get_atlantic_salmon_efh_hapc_in_roi` | Query Atlantic salmon EFH/HAPC buffers within the ROI. |
| `pcsrf` | `get_noaa_all_species_ranges_in_roi` | Query NOAA All_Species_Ranges records within the ROI. |
| `pcsrf` | `get_noaa_critical_habitat_20210904_in_roi` | Query NOAA critical-habitat snapshot records within the ROI. |
| `pcsrf` | `get_pcsrf_projects_in_roi` | Query NOAA for PCSRF salmon recovery projects within the ROI. |
| `tigerweb_counties` | `get_tigerweb_counties_in_roi` | Identify all counties intersecting an ROI buffer using TIGERweb. |
| `tribal` | `get_tribal_lands_in_roi` | Identify tribal lands intersecting the ROI using TIGERweb AIANNHA datasets. |
| `usace` | `analyze_usace_jurisdiction` | Comprehensive USACE jurisdictional analysis for Section 404 compliance. |
| `usace` | `get_usace_regulatory_district` | Identify which USACE district has regulatory jurisdiction over the ROI. |
| `usace` | `get_usace_wetland_regions_in_roi` | Get wetland delineation regions within the ROI. |
| `usace` | `get_usace_wetland_subregions_in_roi` | Get wetland subregion classifications within the ROI. |
