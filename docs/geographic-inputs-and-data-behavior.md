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

## Coverage and upstream failures

- Empty NOAA West Coast and PCSRF-project results outside their expected
  service geography include a coverage warning.
- Upstream request failures and partial-layer failures are returned as
  warnings; they are not presented as evidence that a resource is absent.
