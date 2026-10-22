# MCP Data Source Licenses

This reference consolidates data-source license notes for the current flat
24-server repository. It is a public-release aid, not legal advice. Verify final
license determinations before publishing or redistributing derived datasets.

| Server | Agency / Publisher | Dataset / Service | Primary endpoint | Auth required | License / terms signal | Risk flag | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `blm` | BLM / DOI | Land Use Plans, Wilderness Areas, National Monuments and NCAs | `services1.arcgis.com/KbxwQRRfWyEYLgp4/.../FeatureServer` | No | Public domain signal from DOI / BLM public-content policies | Low | Federal agency geospatial services hosted on ArcGIS Online. |
| `blm_mlrs` | BLM / DOI | MLRS authorization, locatable-operation, and energy-lease services | `gis.blm.gov/nlsdb/rest/services/HUB/.../FeatureServer` | No | BLM permits public use of the map/feature services and requires BLM attribution; item metadata disclaims legal-document and land-survey status | Medium | Dynamic legal-description-derived geometries may be generalized or absent. Preserve source status, geometry quality, endpoint, and retrieval time; confirm official records with BLM. |
| `census` | U.S. Census Bureau | ACS 5-Year profile API and TIGERweb county boundaries | `api.census.gov/data/.../acs/acs5/profile`; `tigerweb.geo.census.gov/.../tigerWMS_Current/MapServer` | Yes for ACS API key | ACS API metadata declares CC0; TIGERweb follows Census API terms with attribution requirements | Medium | Census API terms require attribution and prohibit misuse such as re-identification. |
| `cfr` | OFR / NARA / GPO; Federal Register | eCFR, Federal Register documents, Executive Orders | `ecfr.gov/api`; `federalregister.gov/api/v1` | No | Unrestricted reproduction / republication for Federal Register materials under 1 CFR 2.6 | Low | API responses are official federal regulatory publication data; verify citation currency. |
| `efh` | NOAA Fisheries | EFH Mapper, HAPC, Pacific salmon EFH, HMS/CPS/groundfish EFH | `services2.arcgis.com/C8EMgrsFcRFL6LrL/.../FeatureServer` | No | Federal agency data; NOAA Fisheries service terms should be verified | Medium | Current tool docs disclose the applicable NOAA Fisheries scope. No-hit outside a dataset's geography is not a national absence finding. |
| `epa_acres` | EPA | ACRES Brownfields property points (Envirofacts facility points) | `geopub.epa.gov/ArcGIS/rest/services/EMEF/efpoints/MapServer/5` | No | Federal agency data; no layer-specific license identified in the ArcGIS metadata | Medium | ACRES records are grantee-reported and cover only EPA Brownfields grant-program properties, not all brownfields or contaminated sites. Verify EPA reuse terms and preserve per-record facility URLs. |
| `epa_aqs` | EPA | Air Quality System API | `aqs.epa.gov/data/api` | Yes | EPA web policies permit non-commercial, scientific, and educational use; API has rate-limit and account terms | High | Requires EPA AQS email and API key. Avoid presenting screening comparisons as formal NAAQS compliance determinations. |
| `epa_superfund` | EPA; Office of the Federal Register | NPL status points; total-site, operable-unit, and institutional-control boundaries; FRS SEMS points; Superfund Sites in Reuse points; Envirofacts SEMS site and contaminant tables; Federal Register documents | `services.arcgis.com/cJ9YHowT8TU7DUyn/.../FeatureServer/0`; `data.epa.gov/efservice/sems.*`; `federalregister.gov/api/v1` | No | EPA data are public domain under the EPA data license; the boundary layers carry an EPA disclaimer. Federal Register material is unrestricted (1 CFR 2.6) | Medium | EPA's site-profile host (`cumulis.epa.gov`) and its notice and news-release search pages are robots-disallowed and never fetched; tools link to them for people to open. Program records are not clean-land or suitability determinations. |
| `esa_ranges` | NOAA Fisheries | West Coast Region ESA-listed salmon and steelhead ranges by HUC-12 | `maps.fisheries.noaa.gov/.../Ranges_dice/FeatureServer` | No | Federal agency data; NOAA Fisheries service terms should be verified | Medium | Current tool docs disclose West Coast Region scope and salmon/steelhead coverage. |
| `fema_nfhl` | FEMA | National Flood Hazard Layer | `hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer` | No | No explicit NFHL service license found in the reviewed source materials | Medium | Treat results as screening data, not a site-specific engineering flood determination. |
| `gbif` | GBIF and contributing dataset publishers; U.S. Census Bureau for county boundaries | Species occurrence search and TIGERweb county boundaries | `api.gbif.org/v1/occurrence/search`; `tigerweb.geo.census.gov/.../tigerWMS_Current/MapServer` | No | GBIF occurrence responses include dataset-level licenses, commonly CC-BY 4.0 / CC0 / CC-BY-NC; Census API terms require attribution | Medium | Preserve record-level publisher and license metadata. County-based screening also depends on Census TIGERweb. |
| `gis` | Esri | ArcGIS Geometry Service | `utility.arcgisonline.com/.../GeometryServer` | No for current usage | Esri service terms / Master License Agreement | Medium | Used to construct ROI buffers; GeoJSON and area estimates are derived locally. Esri is a supporting geometry-service provider, not the publisher of agency datasets screened by other servers. |
| `ipac` | USFWS / DOI | IPaC resources API | `ipac.ecosphere.fws.gov/location/api/resources` | No | Generally public domain signal from DOI / USFWS federal data policies | Medium | IPaC endpoint is not a formal public API contract and may change. |
| `map_composer` | USFWS / DOI | Critical Habitat and National Wildlife Refuge System boundary services | `services.arcgis.com/QVENGdaPbd4LUkLV/.../FeatureServer` | No | Federal agency public-data signal; item-level terms should be verified | Medium | Spatial screening layers are dataset representations, not agency determinations. |
| `map_composer` | USGS / DOI | National Hydrography Dataset | `hydro.nationalmap.gov/.../nhd/MapServer` | No | USGS-authored data generally carries a public-domain signal | Low | Preserve dataset name, retrieval time, and service URL in exported metadata. |
| `map_composer` | USDA Forest Service | National Forest System and Inventoried Roadless Area boundaries | `apps.fs.usda.gov/arcx/rest/services/EDW/.../MapServer` | No | Federal agency public-data signal; service terms should be verified | Medium | Boundary layers provide project-area context and may not reflect every local update. |
| `map_composer` | NPS / DOI | Land Resources Division unit boundaries | `services1.arcgis.com/fBc8EJBxQRMcHlei/.../FeatureServer` | No | Federal agency public-data signal; item-level terms should be verified | Medium | Preserve source attribution in maps and exports. |
| `map_composer` | BLM / DOI | Planning, habitat-management, trail, LWCF, and contextual boundary layers | `services1.arcgis.com/KbxwQRRfWyEYLgp4/.../FeatureServer` | No | Public-domain signal from DOI / BLM public-content policies | Low | Individual layers have different update dates and geographic coverage. |
| `map_composer` | National Interagency Fire Center | Interagency fire-perimeter history | `services3.arcgis.com/T4QMspbfLg3qTGWY/.../FeatureServer` | No | Federal public-data signal; item-level terms should be verified | Medium | Historical perimeter records vary by contributing agency and year. |
| `map_composer` | Carto, USGS, Esri | Interactive basemap tiles and web-map assets | Runtime tile and CDN endpoints embedded by Folium | No | Provider-specific service and attribution terms apply | Medium | HTML maps require network access for basemap tiles and standard web-map assets; vector overlays are embedded locally. |
| `nepa_assist` | EPA | NEPAssist environmental screening | `nepassisttool.epa.gov/nepassist/analysis.aspx` | No | EPA geospatial data generally public domain under 17 U.S.C. 105 unless otherwise specified | High | Access method is fragile because it relies on NEPAssist web endpoint behavior. |
| `noaa` | NOAA Fisheries | West Coast Region ESA critical habitat | `maps.fisheries.noaa.gov/.../WCR_ch_dice/FeatureServer` | No | Federal agency data; NOAA Fisheries service terms should be verified | Medium | Current tool docs disclose West Coast Region scope. |
| `nrcs_soils` | USDA-NRCS | Soil Survey Geographic Database (SSURGO) through Soil Data Access | `sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest` | No | Federal soil-survey data; USDA-NRCS service and reuse terms should be verified | Medium | Map-unit and component data are generalized soil-survey screening information, not site-specific geotechnical, wetland, infiltration, or FPPA determinations. |
| `nrhp` | National Park Service | National Register of Historic Places listed properties | `mapservices.nps.gov/.../cultural_resources/nrhp_locations/MapServer` | No | Federal agency public data signal; NPS service terms should be verified | Medium | Current service covers listed NRHP records, not all eligible cultural resources. |
| `padus` | USGS / DOI | PAD-US 4.1 Combined protected-area records | `edits.nationalmap.gov/.../PAD-US/PAD_US_gaz_combined/MapServer` | No | Public domain signal from DOI / USGS public data policies | Low | PAD-US is protected-area screening data, not comprehensive cadastral parcel ownership; Combined-layer records may overlap. |
| `pcsrf` | NOAA Fisheries | PCSRF project locations and funding | `services2.arcgis.com/C8EMgrsFcRFL6LrL/.../PCSRF_Projects_Display/FeatureServer` | No | Federal agency data; NOAA Fisheries service terms should be verified | Medium | Only `get_pcsrf_projects_in_roi` is PCSRF project data. |
| `pcsrf` | NOAA Fisheries | NOAA all-species ranges, 2021-09-04 critical habitat snapshot, Atlantic salmon EFH/HAPC | `services2.arcgis.com/C8EMgrsFcRFL6LrL/.../FeatureServer` | No | Federal agency data; NOAA Fisheries service terms should be verified | Medium | These are NOAA datasets exposed by the PCSRF server for now; tool names disclose actual provenance. |
| `permitting_dashboard` | FPISC / Federal Permitting Data Portal | Permitting Dashboard Full Dataset (mcm3-xbid) | `data.permits.performance.gov/resource/mcm3-xbid.json` | No | Official dataset metadata identifies public access and federal-agency reporting; preserve attribution and verify reuse terms | Medium | Dashboard-listed projects only; reported schedules and outcomes are not comprehensive permits or construction approval. Preserve source dates, alternative dates, and freshness. |
| `tigerweb_counties` | U.S. Census Bureau | TIGERweb county boundaries | `tigerweb.geo.census.gov/.../tigerWMS_Current/MapServer/82/query` | No | Census API terms with attribution requirements | Medium | Attribution language from Census API terms should be preserved in downstream products. |
| `tribal` | U.S. Census Bureau | AIANNHA tribal geography layers | `tigerweb.geo.census.gov/.../AIANNHA/MapServer` | No | Census API terms with attribution requirements | Medium | These are Census geography records for screening and do not replace consultation obligations. |
| `usace` | USACE | Regulatory boundaries, wetland regions, wetland subregions | `services7.arcgis.com/n1YM8pTrFmm7L4hs/.../FeatureServer` | No | USACE public-information disclaimer permits distribution/copying | Low | Contact the relevant district for permit decisions; tools are screening aids. |

## EPA Superfund Access And Reuse

Reviewed October 21, 2026. Access controls and reuse rights are separate: a
public-domain record is not permission to automate every page that hosts it.
These notes describe the reviewed sources and this server's conservative access
policy, not a legal certification or a blanket authorization for EPA hosts.

| Source | Published guidance | Server behavior |
| --- | --- | --- |
| Envirofacts SEMS | EPA documents a [REST data service](https://www.epa.gov/enviro/envirofacts-data-service-api), bounded row ranges, and site/contaminant joins. | Query selected fields with bounded results; preserve typed identifiers and source retrieval states. |
| EPA ArcGIS layers | Check the specific layer metadata, attribution, and intended-use limitations. EPA's [data license](https://edg.epa.gov/EPA_Data_License.html) says EPA-produced data are public domain unless otherwise specified, without warranty. | Query the six configured layers only; preserve source links, raw meanings, and boundary limitations. A mapped area is not a contamination, ownership, or suitability finding. |
| `cumulis.epa.gov` profiles | The host's [robots.txt](https://cumulis.epa.gov/robots.txt) disallows `/` for automated clients. | Never fetch profiles, schedules, document collections, or participation pages. Return manual links and explicit unsupported coverage instead. |
| EPA notice/news search | [EPA robots.txt](https://www.epa.gov/robots.txt) disallows `/publicnotices/notices-search/` and `/newsreleases/search/`. | Never fetch these searches or bypass bot challenges. Federal Register results do not replace local or web-only notices. |
| Federal Register | Use the published [documents API](https://www.federalregister.gov/developers/documentation/api/v1); verify the official document and its dates. | Name-search results remain candidates unless linked to the site by stronger evidence. Matching publication dates alone do not establish identity. |
| Esri geometry service | The shared buffer service is a separate provider, governed by the terms noted in the `gis` row above. | Use it only for the requested ROI buffer, not as an EPA data source. |

All Superfund requests identify the project with a User-Agent, have bounded
timeouts and tool budgets, and reject redirects without visiting their targets.
SEMS and Federal Register reads are cached for ten minutes with the original
retrieval timestamp retained. These are repository safeguards, not a claim that
EPA published these exact limits. No SEMS-specific numeric requests-per-second
quota was established from the reviewed REST documentation.

Preserve attribution, retrieval times, source warnings, and applicable item-level
restrictions in exports. Check individual documents before redistributing them:
EPA hosting does not establish authorship or remove third-party copyright. EPA's
[disclaimer guidance](https://www.epa.gov/web-policies-and-procedures/epa-disclaimers)
also distinguishes intended use, accuracy, and endorsement; do not imply agency
approval of this tool. Recheck access guidance before adding endpoints or
publishing a new integration. Detailed schedules, complete profile OU inventories,
document bodies, and web-only notices remain deferred until a sanctioned source
or permission is available.

### Profile Evidence Source Check

Checked October 21, 2026; research only, no new automated adapter added:

- EPA's [published Envirofacts OpenAPI schema](https://data.epa.gov/api-cache/metadata/openapi_swagger.json)
  exposes `sems.envirofacts_site` and `sems.envirofacts_contaminants`. No national
  cleanup-schedule or full OU-inventory endpoint was verified in that schema.
- EPA's [Superfund Data and Reports](https://www.epa.gov/superfund/superfund-data-and-reports)
  lists completed ROD/amendment/ESD reports (FOIA 2), active/archived inventories,
  and decision-related data. These are promising published products, but not a
  verified current full schedule or a documented API contract. The archived
  CERCLIS activity downloads reflect the end of FY 2013, not current schedules.
- Some regional `www.epa.gov` pages publish SEMS-derived schedules directly,
  such as [Butte's schedule by OU](https://www.epa.gov/butte/cleanup-schedule-operable-unit).
  This is a useful official manual source outside the prohibited cumulis host,
  not proof of nationwide coverage or approval for an automated integration.
  Preserve estimated windows, suppressed dates, footnotes, and intended-use limits.
- EPA's [document discovery page](https://www.epa.gov/superfund/search-superfund-documents)
  provides another official research lead. A published web interface alone does
  not establish a stable machine API, permitted bulk indexing, or document rights.

Before implementing another adapter, verify the specific endpoint's access
guidance, publication/update contract, EPA-ID/OU joins, and coverage; seek EPA
confirmation if these cannot be established. Do not guess private endpoints,
re-enable cumulis/search crawling, or silently substitute historical downloads.

## Follow-Up Checks

- Confirm whether NOAA Fisheries ArcGIS service pages expose explicit item-level terms beyond general federal data status.
- Confirm current FEMA NFHL terms for the ArcGIS MapServer specifically, separate from OpenFEMA API terms.
- Preserve source URLs, retrieval dates, and any upstream warnings when generating public-facing reports from tool outputs.
