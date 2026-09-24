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

## Coverage and upstream failures

- Empty NOAA West Coast and PCSRF-project results outside their expected
  service geography include a coverage warning.
- Upstream request failures and partial-layer failures are returned as
  warnings; they are not presented as evidence that a resource is absent.

### IPaC partial responses

The IPaC tool accepts a 0.1–100-mile radius (25 miles by default). A large
buffer is not itself an explanation for an upstream null value, and reducing
the buffer does not repair an incomplete response.

When IPaC returns a null or malformed resource collection, including nested
`items` collections, the adapter preserves usable categories and marks the
response as partial. Malformed individual entries are skipped with their
category flagged; usable entries in that category are retained. The summary
names affected categories and says **Unavailable in this response**, not zero
or no-hit. Reviewer follow-up is required. Unresolved marine-mammal population
references retain the resource identifier rather than silently dropping it.

Coastal barriers accept both the live API's `items` wrapper and legacy lists;
the adapter normalizes the parsed `coastal_barriers` field to a list. Explicit
wrapper truncation also marks that category incomplete rather than presenting
a retained-record count as a complete total.

For callers of the Python adapter, `partial` and `unavailable_resource_fields`
describe availability. Affected `*_count` values are `None`; `returned_counts`
reports retained record counts, not complete category totals. Existing parsed
lists remain available, and `raw_response` preserves the unmodified upstream
JSON for audit. The MCP tool continues returning a human-readable summary;
these Python audit fields are not a new MCP output schema or persisted artifact.

Missing collection keys and valid empty collections retain the established
empty-collection behavior. An absent or non-object overall `resources` member,
malformed JSON, and HTTP failures still fail the call. All results remain
screening information, not an official species list, consultation determination,
or evidence of absence.
