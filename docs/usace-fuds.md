# USACE FUDS research

Five read-only tools cover property discovery/lookup, independently paged restoration projects, mapped munitions response areas, and FUDS program district lookup. All use the primary [USACE FUDS MapServer](https://geospatial.sec.usace.army.mil/server/rest/services/Military/FUDS_Data/MapServer); no mirror or alternative inventory is substituted.

| Layer | Role | Coverage |
| --- | --- | --- |
| 1 | Public property reference points | Not property footprints |
| 4 | Mapped property polygons | Sparse subset; polygon-only records retained |
| 2 | Restoration project relationships | Public property and foreign keys; projects paged independently |
| 3 | Mapped munitions response areas | Not individual hazard locations |
| 9 | FUDS program offices | Recorded assignments remain distinct from geographic intersections |

Metadata and representative public queries were checked October 23, 2026. Property/project group: **FUDS FY24**. Preserve per-record FISCALYEAR separately; project records lack a per-record fiscal year field. Project cost units and estimate-specific vintage are not published in the checked layer metadata. Dates are source epoch milliseconds rendered in UTC without inventing planned/actual meanings. Fixture samples omit owner fields and unrestricted narratives.

Arguments are checked before requests. Buffers follow the repository's 0.1–100 mile convention. Page sizes are 1–100, offsets 0–100,000. Select source IDs, retrieve at most 2,500 features per layer in batches of 250, then recheck IDs. Combined property identities are sorted before public pagination; projects use property/site/project and source object identifiers. IDs are checked twice but the service does not guarantee an atomic snapshot. Compare result fingerprints and restart on changes. Request budget: 24 query operations / 50 seconds; individual requests use bounded connect/read timeouts. Every source reports unavailable, partial, or complete retrieval separately; counts after incomplete retrieval are lower bounds. Output geometry is represented by official layer/object references, avoiding large polygon tool responses. Spatial selection uses the full ROI, without simplification.

`get_usace_fuds_program_district` accepts exactly a property number or a full coordinate pair. No owner names or free-form historical descriptions are requested. Unknown/missing/unrecognized codes stay distinct, with raw values preserved. Conflicting source records remain visible. Published program records and eligibility labels do not establish contamination, safety, ownership, availability, development suitability, or NEPA determinations.

Run default offline tests with `uv run pytest tests/test_usace_fuds.py`. Set `NEPA_FUDS_LIVE=1` to explicitly run the live smoke test. A failed service request is an unavailable source, never an empty inventory finding.
