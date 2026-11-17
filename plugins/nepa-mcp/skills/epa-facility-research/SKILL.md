---
name: epa-facility-research
description: Trace EPA Brownfields accomplishments and grants, regulated facility reports, discharge monitoring records, and civil enforcement cases.
---

# EPA facility research

For a brownfield, start with an ACRES property ID or find one with
`get_epa_acres_properties_in_roi`. Use `get_epa_acres_property` for dated
activities and `get_epa_acres_property_grants` for the organizations and awards
linked to that property. Preserve deleted or uncounted activity flags; do not
describe those rows as completed work. A grant can support several properties.

For compliance research, use `search_epa_echo_facilities` with a name and state
or project coordinates and a radius. Identify candidates by FRS ID. If several
facilities match, show their names and locations before attributing a record.
Use an FRS ID published by EPA to follow a property into ECHO; a similar name
or adjacent point does not establish that two records describe the same site.

Use `get_epa_echo_facility_report` with the FRS ID. Select the permits,
quarters, inspections, or cases section for a focused question. Use a published
NPDES permit ID with `get_epa_echo_discharge_reports` and an explicit date
range; keep the outfall, units, qualifier, limit, measurement, and no-discharge
code together. A facility coordinate does not locate its outfalls. Use an ICIS
case number from the cases section with `get_epa_echo_civil_case`; distinguish
reported penalties from amounts collected.

Keep the same filters and page size when following the returned page or offset.
EPA data can change between requests. Cite the returned sources and reporting
periods, label missing IDs and unavailable sections, and say when more records
remain. A retrieval date is not an inspection date. An empty history cannot
establish compliance, and an ACRES milestone does not establish unrestricted use.
