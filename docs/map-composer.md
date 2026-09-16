# Map Composer

Map Composer is the geospatial synthesis server in NEPA MCP. In one request it
can query public GIS services from multiple federal data publishers, organize
the returned features around a project-area buffer, and produce either an
interactive HTML map or a combined GeoJSON artifact.

The server has 32 selectable overlays and three MCP tools:

- `compose_environmental_map` creates an interactive HTML map with independent
  layer controls and per-layer source attribution. CartoDB Positron is the
  default basemap; OpenStreetMap, USGS, and Satellite remain opt-in choices.
- `export_all_layers_geojson` creates one provenance-rich GeoJSON artifact for
  QGIS, ArcGIS, and other geospatial workflows.
- `list_available_layers` returns the current layer IDs, source publishers,
  geometry types, review uses, and profile memberships at runtime.

## Why the map is interactive

Layer breadth and visual clarity serve different purposes. A broad request is
useful for discovering what intersects a project area; a curated view is more
useful for communicating the result. Map Composer keeps those decisions
separate:

1. A profile or explicit layer list determines which upstream services are
   queried.
2. Every requested layer is reported as `ok`, `empty`, `partial`, or `failed`.
3. Layers that return features can be toggled independently in the HTML map.
4. The same collected features can be exported together as GeoJSON.

An empty layer means the source returned no local features for that project
area. It does not mean the capability is missing. Partial and failed layers are
reported as warnings rather than being presented as evidence of absence.

## Layer profiles

| Profile | Layers requested | Intended starting point |
|---|---:|---|
| `screening` | 12 | Balanced project-area context across jurisdiction, habitat, water, and managed lands |
| `biological` | 6 | Habitat, refuges, sage-grouse context, and herd-management areas |
| `water` | 11 | USACE context and USGS National Hydrography Dataset features |
| `lands` | 14 | Federal land managers, planning areas, roadless areas, trails, and related land context |
| `geothermal` | 21 | Practitioner document's selection: land managers, plans in progress, WSAs, bundled monuments/NCAs, habitat and water context |
| `full` | 32 | Complete catalog; this is the default profile |

Explicit layer IDs override the selected profile. For the authoritative runtime
inventory, call `list_available_layers`.

## Complete layer catalog

| Category | Layer ID | Overlay | Source publisher | Geometry |
|---|---|---|---|---|
| Region of Interest | `roi` | Project Location and Buffer | User coordinates and ArcGIS geometry service | Point + polygon |
| Tribal | `tribal_lands` | Tribal Lands | U.S. Census Bureau TIGERweb AIANNHA | Polygon |
| Administrative | `counties` | County Boundaries | U.S. Census Bureau TIGERweb | Polygon |
| Species and Habitat | `critical_habitat` | Critical Habitat | U.S. Fish and Wildlife Service | Polygon |
| Species and Habitat | `wildlife_refuges` | National Wildlife Refuges | U.S. Fish and Wildlife Service | Polygon |
| Water Resources | `usace_districts` | USACE Regulatory Districts | U.S. Army Corps of Engineers | Polygon |
| Water Resources | `wetland_regions` | Wetland Delineation Regions | U.S. Army Corps of Engineers | Polygon |
| Water Resources | `wetland_subregions` | Wetland Delineation Subregions | U.S. Army Corps of Engineers | Polygon |
| Water Resources | `nhd_lakes` | Lakes and Ponds | USGS National Hydrography Dataset | Polygon |
| Water Resources | `nhd_reservoirs` | Reservoirs | USGS National Hydrography Dataset | Polygon |
| Water Resources | `nhd_estuaries` | Estuaries | USGS National Hydrography Dataset | Polygon |
| Water Resources | `nhd_ice_masses` | Glaciers and Ice Masses | USGS National Hydrography Dataset | Polygon |
| Water Resources | `nhd_perennial_streams` | Perennial Stream Centerlines | USGS National Hydrography Dataset | Polyline |
| Water Resources | `nhd_stream_areas` | River and Stream Areas | USGS National Hydrography Dataset | Polygon |
| Water Resources | `nhd_infrastructure` | Water Infrastructure | USGS National Hydrography Dataset | Point |
| Federal Lands | `federal_lands` | Federal Protected Lands | USGS PAD-US 4.1, non-BLM federal managers | Polygon |
| Federal Lands | `usfs_forests` | National Forest System Boundaries | USDA Forest Service | Polygon |
| Federal Lands | `usfs_roadless_areas` | Inventoried Roadless Areas | USDA Forest Service | Polygon |
| Federal Lands | `nps_boundaries` | National Park Service Unit Boundaries | National Park Service | Polygon |
| Federal Lands | `blm_managed_lands` | BLM-Managed Protected Lands | USGS PAD-US 4.1 Fee, filtered to BLM | Polygon |
| Federal Lands | `blm_land_use_plans` | Approved Land Use Plans | Bureau of Land Management | Polygon |
| Federal Lands | `blm_plans_in_progress` | Land Use Plans Under Revision | Bureau of Land Management | Polygon |
| Federal Lands | `blm_wilderness_study_areas` | Wilderness Study Areas | Bureau of Land Management | Polygon |
| Federal Lands | `blm_national_monuments` | National Monuments and Conservation Areas | Bureau of Land Management | Polygon |
| Federal Lands | `blm_rights_of_way` | No Surface Occupancy Restrictions | Bureau of Land Management | Polygon |
| Habitat | `grsg_habitat` | Greater Sage-Grouse Habitat Management Areas | Bureau of Land Management | Polygon |
| Habitat | `sagebrush_focal_areas` | Sagebrush Focal Areas | Bureau of Land Management | Polygon |
| Habitat | `wild_horse_hma` | Wild Horse and Burro Herd Management Areas | Bureau of Land Management | Polygon |
| Context | `national_trails` | National Scenic and Historic Trails | Bureau of Land Management | Polyline |
| Context | `fire_perimeters` | Historical Fire Perimeters | National Interagency Fire Center | Polygon |
| Context | `lwcf_lands` | Land and Water Conservation Fund Parcels | Bureau of Land Management | Polygon |
| Context | `eis_boundaries` | Western U.S. EIS Planning Boundaries | Bureau of Land Management | Polygon |

## Geothermal screening

Use `profile="geothermal"` with either map tool. The profile selects exactly the
21 layers in the practitioner document's proposed profile, reusing the existing
32-layer catalog. No additional overlays are introduced by this profile.

Use an explicit `layers` list to request optional layers; it replaces rather
than extends the profile, so include the desired base layers as well. The `full`
profile still selects all 32 layers. Existing NPS boundaries, USFS roadless
areas, and national trails remain in the catalog, outside the geothermal default.

Dedicated map overlays for designated BLM Wilderness, separate NCAs, PAD-US
designations, and geothermal lease records are not included. Use the standalone
BLM, PAD-US, and MLRS tools for those queries. In particular, the WSA layer is
not a substitute for designated Wilderness screening. Standalone MLRS tools
retain disposition filtering, case-oriented pagination, and explicit missing
case-name and expiration-date reporting. Source dispositions are not
determinations of valid existing rights; closed records or no Authorized
matches do not establish land availability.

`project_geometry` accepts a WGS84 GeoJSON Polygon or MultiPolygon geometry
(longitude/latitude, closed valid rings, at most 10,000 vertices). The footprint
must lie inside the point-buffer search ROI; otherwise enlarge `buffer_miles`.
WSA and bundled monuments/NCA properties distinguish `contained`, `overlap`,
`boundary_touch`, and `outside` relative to that footprint. If no footprint is provided, the
relationship refers only to the project point. Incomplete source retrieval or
invalid geometry produces an unknown relationship. If any source polygon ring
is unusable, the entire feature is excluded with a dropped-feature warning;
other usable features survive, but the layer is partial and cannot establish
containment. Ring and assembled-polygon validity are both checked, without
silently repairing the boundary. Multiple retrieved parts of a designation are
evaluated together, preserving holes. Display and query simplification are
disabled for these land-boundary layers. HTML rendering also preserves the
exact supplied project footprint, including collinear vertices, holes, and
multipart geometry. These are GIS screening relationships, not surveyed
boundaries or legal determinations.

GeoJSON collection metadata retains the validated input as `project_geometry`
even when an explicit layer selection omits `roi`. Its `relation_target` is
`project_footprint`, or `project_point` when `project_geometry` is null. Retaining
the footprint in metadata does not add an unrequested ROI feature or layer.

No protective buffer is inferred from the search ROI. For Numunaa Nobe NCA,
[16 USC 460hhhh(6) and (9)](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title16-section460hhhh)
provide the geothermal withdrawal (subject to valid existing rights) and
no-buffer rule. Its verified BLM `NLCS_ID=NLCS000607` supplies a cited type
classification when `sma_code` is null. Other unclassified records remain in
the bundled monuments response. There is no separate NCA map overlay.
The standalone BLM tool `get_blm_national_monuments_in_roi` accepts
`designation_type="national_conservation_area"` or `"national_monument"`;
the default `"all"` retains other and unclassified designations.

Fee ownership/management remains separate from designation screening:
`blm_managed_lands` and `federal_lands` retain the PAD-US Fee layer, while
the standalone PAD-US tool queries Combined records. PAD-US is not a
complete cadastral or mineral-ownership dataset. For BLM designations, prefer
BLM agency data and controlling legal records. In the standalone PAD-US tool,
the three verified former WSA records (Clan Alpine Mountains, Stillwater Range,
Job Peak) retain their
published attributes and carry a **conflicting or potentially outdated** flag
and a citation to Pub. L. 117-263 sections 2905(b) and 2906. This is a limited,
maintained set of known conflicts, not an automated nationwide reconciliation
or a historical dataset.
Unrecognized records and missing GIS matches are not findings of clearance.

WSA map records include the new-leasing rule in 43 CFR 3201.11(h).
Other designation restrictions default to **not evaluated**. This release does
not supply a comprehensive withdrawal inventory or determine mineral ownership,
valid existing rights, RMP allocations, or the Numu Newe SMA boundary. Numu Newe
SMA is distinct from Numunaa Nobe NCA. Federal geothermal leasing applies to
the federal resource interest; surface ownership alone does not resolve it.
NHD springs/wells and soil ratings are screening indicators, not Section 404
jurisdictional determinations.

## Output and provenance

For the BLM Wilderness Study Areas layer, `ROD_DATE` is returned only when the
source provides a usable date. The source default of `9999-09-09` is reported as
unavailable rather than as a decision date. `CASEFILE_NO` values are preserved
exactly as published; their formatting is not normalized, and they should be
verified against the appropriate BLM case record before being used for a join
or legal-status conclusion.

Generated artifacts are written with private permissions to the operating
system's per-user data directory under `nepa-mcp/artifacts/map_composer`.
Operators can override that location with `NEPA_MCP_OUTPUT_DIR`; MCP callers
cannot choose arbitrary output directories.

HTML maps embed the selected vector features and include a source-and-
limitations panel. Network access is still required for basemap tiles and
standard web-map assets. GeoJSON exports include collection metadata,
per-layer status, source publisher, source URL, retrieval time, project-area
parameters, and warnings.

The [data-source inventory](mcp-data-source-licenses.md) records the upstream
services, authentication requirements, license signals, and release notes.
