# Geographic Inputs and Data Behavior

This reference documents shared geographic-input constraints and the
server-specific area, clipping, coverage, and failure semantics used by NEPA
MCP.

## Geographic inputs

- Geographic screening tools currently accept a WGS84 latitude, longitude,
  and point-buffer distance. Project-polygon input is not yet supported.
- Tool schemas constrain point buffers to 0.1–100 miles. The default is 25
  miles unless a tool documents another value.
- `nrcs_soils` uses a 1-mile default and a 10-mile maximum because SSURGO
  map-unit and component detail is intended for site-scale screening.

## Map Composer layer status

Map Composer reports each requested layer as `ok`, `empty`, `partial`, or
`failed`. Failed and partial layers remain visible as warnings in the tool
response and GeoJSON metadata. An empty layer means the upstream source
returned no local features for the requested ROI; it does not mean the
capability is unavailable.

See the [Map Composer guide](map-composer.md) for profiles, the complete
32-layer catalog, output behavior, and provenance.

## Server-specific geometry behavior

- `esa_ranges` combines both complementary NOAA `Ranges_dice` layers. Layer 1
  covers Washington, Idaho, Oregon, and transboundary fish ranges; Layer 2
  covers California and southern Oregon. Diced watershed geometries are unioned
  by range record and clipped to the requested point-buffer ROI; source
  watershed area is retained separately.
- `efh` uses the public services behind NOAA's EFH Mapper for HAPC, general EFH,
  Pacific salmon watersheds, and species or management-unit screening. Species
  or management-unit polygon acreage is clipped to the point-buffer ROI while
  HAPC and salmon-watershed presence semantics remain unchanged.
- `noaa` consolidates diced critical-habitat fragments by listed entity while
  preserving distinct named habitat units. Polygon area is unioned across
  fragments and clipped to the ROI; upstream whole-feature area is retained as
  provenance rather than presented as affected area.
- `pcsrf` applies the same provenance contract to its generalized critical-
  habitat polygons and Atlantic salmon EFH/HAPC polygons. Critical-habitat line
  length retains its legacy source-coordinate estimate and is explicitly marked
  as not ROI-clipped; recovery projects and species-range tools retain their
  existing behavior.
- `nrcs_soils` intersects SSURGO map-unit polygons with the point-buffer ROI
  inside USDA Soil Data Access and reports clipped acreage. Component-weighted
  estimates multiply that acreage by NRCS component percentages; components
  are not spatially located within map units, so those estimates are not mapped
  subareas or parcel-specific measurements.
- `blm_mlrs` intersects the ROI with BLM case geometries derived from legal
  land descriptions and PLSS data. A case can be generalized to an aliquot,
  section, or county, and some cases cannot be geocoded. Results therefore
  identify research leads rather than surveyed footprints, title opinions,
  permit determinations, or proof that an operation is active.
- `epa_superfund` intersects the ROI with NPL status points (a Web Mercator
  service) and total-site polygons (WGS84), and, in `sems_candidates` scope,
  FRS SEMS points (NAD83); every layer is requested with an explicit WGS84
  output reference. Features are grouped by EPA ID before paging, so several
  polygons count as one site, and each site reports a point, polygon, or
  combined match basis. Polygon distances are approximate (zero inside the
  polygon, otherwise the nearest generalized boundary vertex). Source-reported
  `GIS_AREA` is shown as published; site or ROI acreage is not calculated, and
  overlap with a polygon is not contaminated acreage.

## Coverage and upstream failures

Superfund list tools select matching ArcGIS object IDs first, fetch at most
500 selected IDs per batch, restore ID order, and recheck matching IDs after
retrieval. Missing, duplicate, unexpected, or changed records and interrupted
retrievals are reported as partial or truncated, not complete empty results.
The existing per-layer safety caps and tool budgets still apply.

All eight Superfund list tools return a `result_fingerprint`. Pass it with the
same filters and the next `result_offset` to check continuation pages. Changes
to retrieved evidence, selected ArcGIS IDs, or source coverage reject the
continuation and require restarting at offset zero without the old fingerprint.
The token excludes retrieval timestamps and cache bookkeeping. It is a change
guard, not a persisted or transactional upstream snapshot: SEMS and Federal
Register evidence can remain cached for ten minutes. Calls without a token are
independent live reads and do not guarantee continuity.

- Empty NOAA West Coast and PCSRF-project results outside their expected
  service geography include a coverage warning.
- Upstream request failures and partial-layer failures are returned as
  warnings; they are not presented as evidence that a resource is absent.
