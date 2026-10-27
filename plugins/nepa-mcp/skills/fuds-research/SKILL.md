---
name: fuds-research
description: Research Formerly Used Defense Sites properties, restoration records, munitions response areas, and responsible USACE FUDS offices.
---

# FUDS research

Start from a public FUDS property number or a project coordinate and a 0.1–100 mile buffer. Use `usace_fuds`, not regulatory/Civil Works district inventories, to establish FUDS program responsibility.

1. Discover properties with `get_usace_fuds_properties_in_roi`, then resolve each identity with `get_usace_fuds_property`. Retain ambiguous or conflicting records. A point is a reference location; sparse property polygons are mapped evidence, not complete coverage.
2. Retrieve `get_usace_fuds_projects` independently of property pagination. Use only published relationship keys. Preserve raw dates, cost units and estimate vintage; a future/past date does not establish planned/achieved status. Zero cost differs from missing cost and does not establish a funding commitment.
3. Use `get_usace_fuds_munitions_response_sites_in_roi` for mapped response areas. Keep property/site/project identity and raw priority schemes. These are not precise locations of individual hazards or redevelopment risk scores.
4. Resolve `get_usace_fuds_program_district` by property number for recorded assignments or by coordinates for geographic candidates. Report the basis, multiple offices, and any unresolved disagreement; never replace a recorded assignment with another district inventory.
5. Assemble a cited dossier: identity, source-specific restoration records, mapped evidence, offices, official links, fiscal years, retrieval times, source status, incomplete pages, conflicting evidence, and unresolved questions. Stop within an explicit research budget, and report unvisited pages. Result fingerprints can expose changes; the source does not supply an atomic cross-request snapshot.

Explain complete empty results separately from unavailable or partial sources. A current retrieval timestamp is not the data vintage. Published FY2024 data may contain older entries. Do not infer safety, ownership, land availability, development suitability, completed cleanup, contamination absence, or NEPA compliance from program status. FUDS “Categorical Exclusion” is an eligibility label, not a NEPA categorical-exclusion determination.

Example dossier outline: property number → point/polygon evidence and coverage → independently paged projects → mapped response areas → recorded/geographic office basis → citations and unresolved evidence gaps. If two layers disagree on an office or name, show both source records and ask the responsible program office to resolve the discrepancy.
