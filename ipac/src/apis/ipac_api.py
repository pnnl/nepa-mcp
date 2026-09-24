"""
USFWS IPaC (Information for Planning and Consultation) API Integration.

This module provides access to the USFWS IPaC API for threatened/endangered species
and other Fish & Wildlife Service resources within a Region of Interest.

API Documentation: https://ipac.ecosphere.fws.gov/
"""

from __future__ import annotations

import json
import requests
from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService


_CATEGORIES = (
    ("populationsBySid", "species", "species_count", "Threatened/Endangered Species"),
    ("migbirds", "migratory_birds", "migbirds_count", "Migratory Birds"),
    ("wetlands", "wetlands", "wetlands_count", "Wetland Types"),
    ("crithabs", "critical_habitat", "critical_habitat_count", "Critical Habitat Units"),
    ("refuges", "refuges", "refuges_count", "Refuges"),
    ("fieldOffices", "field_offices", "field_offices_count", "Field Offices"),
    ("marineMammals", "marine_mammals", "marine_mammals_count", "Marine Mammals"),
    (
        "allReferencedPopulationsBySid",
        "referenced_populations",
        "referenced_populations_count",
        "Referenced Populations",
    ),
    ("fishHatcheries", "fish_hatcheries", "fish_hatcheries_count", "Fish Hatcheries"),
    ("coastalBarriers", "coastal_barriers", "coastal_barriers_count", "Coastal Barriers"),
)


def _dict_or_empty(value: object, field: str, unavailable: set[str]) -> dict:
    if isinstance(value, dict):
        return value
    unavailable.add(field)
    return {}


def _records_or_empty(value: object, field: str, unavailable: set[str]) -> list[dict]:
    if not isinstance(value, list):
        unavailable.add(field)
        return []
    records = [record for record in value if isinstance(record, dict)]
    if len(records) != len(value):
        unavailable.add(field)
    return records


def _population_map(value: object, field: str, unavailable: set[str]) -> dict:
    records = _dict_or_empty(value, field, unavailable)
    valid = {key: record for key, record in records.items() if isinstance(record, dict)}
    if len(valid) != len(records):
        unavailable.add(field)
    return valid


def _resource_items(resources: dict, field: str, unavailable: set[str]) -> list[dict]:
    container = _dict_or_empty(resources.get(field, {}), field, unavailable)
    if container.get("truncated") is True:
        unavailable.add(field)
    return _records_or_empty(container.get("items", []), field + ".items", unavailable)


def _sid_value(value: object, default: str, field: str, unavailable: set[str]) -> str:
    sid = _dict_or_empty(value, field, unavailable)
    result = sid.get("val", default)
    if not isinstance(result, str):
        unavailable.add(field)
        return default
    return result


def _is_unavailable(field: str, unavailable: set[str]) -> bool:
    return any(item == field or item.startswith(field + ".") for item in unavailable)


def get_ipac_resources_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query the IPaC API for threatened/endangered species and other FWS resources.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Parsed resource lists, availability and counts, and unchanged raw_response.
        Unavailable category counts are None; returned_counts records how many
        usable records were retained without implying a complete category total.
    """
    return _query_ipac_api(lat, lon, buffer_miles)


def _query_ipac_api(lat: float, lon: float, buffer_miles: float) -> Dict:
    """
    Query USFWS IPaC (Information for Planning and Consultation) API
    for threatened/endangered species and other FWS resources in ROI.

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        buffer_miles: Buffer distance in miles

    Returns:
        Dictionary containing resource lists and explicit `*_count` fields
        (None when the category is unavailable or incomplete):
        - species / species_count
        - migratory_birds / migbirds_count
        - wetlands / wetlands_count
        - refuges / refuges_count
        - field_offices
        - critical_habitat / critical_habitat_count
        Also includes partial, unavailable_resource_fields, returned_counts,
        and the untouched raw_response for audit.
    """
    try:
        # Step 1: Get ROI polygon geometry
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

        # Simplify polygon to reduce payload size
        simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geom)

        # Extract just the polygon coordinates (IPaC wants pure GeoJSON geometry)
        polygon_geometry = {"type": "Polygon", "coordinates": simplified_geom["rings"]}

        # Step 2: Build IPaC request
        ipac_request = {
            "location.footprint": json.dumps(polygon_geometry),
            "timeout": 45,
            "apiVersion": "1.0.0",
            "locationFormat": "GeoJSON",
            "includeOtherFwsResources": True,
            "includeCrithabGeometry": False,  # Don't include geometry (too large)
            "saveLocationForProjectCreation": False,
        }

        # Step 3: POST to IPaC API
        ipac_url = "https://ipac.ecosphere.fws.gov/location/api/resources"
        response = requests.post(
            ipac_url,
            json=ipac_request,
            headers={"Content-Type": "application/json"},
            timeout=55,
        )

        response.raise_for_status()
        data = response.json()

        resources = data.get("resources") if isinstance(data, dict) else None
        if not isinstance(resources, dict):
            raise ValueError("IPaC response did not include a resources object")

        # Step 4: Parse and structure the response
        unavailable: set[str] = set()
        species_list = []
        populations = _population_map(resources.get("populationsBySid", {}), "populationsBySid", unavailable)

        for pop_id, pop_data in populations.items():
            pop = _dict_or_empty(pop_data.get("population", {}), "populationsBySid", unavailable)
            species_list.append(
                {
                    "id": _sid_value(pop.get("sid", {}), pop_id, "populationsBySid", unavailable),
                    "common_name": pop.get("optionalCommonName", ""),
                    "scientific_name": pop.get("optionalScientificName", ""),
                    "short_name": pop.get("shortName", ""),
                    "listing_status": pop.get("listingStatusName", ""),
                    "listing_code": pop.get("listingStatusCode", ""),
                    "critical_habitat": pop.get("criticalHabitat", "None"),
                }
            )

        # Sort by common name
        species_list.sort(key=lambda x: str(x["common_name"] or ""))

        # Migratory birds - parse phenology data
        migbirds_list = []
        for bird in _records_or_empty(resources.get("migbirds", []), "migbirds", unavailable):
            phenology = _dict_or_empty(bird.get("phenologySpecies", {}), "migbirds", unavailable)
            level = _dict_or_empty(bird.get("level", {}), "migbirds", unavailable)
            migbirds_list.append(
                {
                    "common_name": phenology.get("commonName", ""),
                    "scientific_name": phenology.get("scientificName", ""),
                    "code": phenology.get("code", ""),
                    "conservation_level": level.get("name", ""),
                    "bcc": bird.get("bcc", False),
                    "breeds_from": bird.get("optionalBreedsFrom", ""),
                    "breeds_to": bird.get("optionalBreedsTo", ""),
                }
            )

        # Sort by common name
        migbirds_list.sort(key=lambda x: str(x["common_name"] or ""))

        # Wetlands - extract items from dict
        wetlands_list = []
        for wetland in _resource_items(resources, "wetlands", unavailable):
            attrs = _dict_or_empty(wetland.get("attributes", {}), "wetlands.items", unavailable)
            wetlands_list.append(
                {
                    "code": wetland.get("wetlandCode", ""),
                    "system": attrs.get("SYSTEM_NAME", ""),
                    "class": attrs.get("CLASS_NAME", ""),
                    "water_regime": attrs.get("WATER_REGIME_SUBGROUP", ""),
                    "shape": attrs.get("Shape", ""),
                }
            )

        # Refuges - extract items from dict
        refuges_list = []
        for refuge in _resource_items(resources, "refuges", unavailable):
            refuges_list.append(
                {
                    "name": refuge.get("name", ""),
                    "type": refuge.get("rslType", ""),
                    "acres": refuge.get("acres", 0),
                    "org_code": refuge.get("orgCode", ""),
                }
            )

        # Field offices
        field_offices = []
        for office in _records_or_empty(resources.get("fieldOffices", []), "fieldOffices", unavailable):
            field_offices.append({"name": office.get("officeName", ""), "code": office.get("officeCode", "")})

        # Critical Habitat - parse and cross-reference with species data
        critical_habitat_list = []
        crithabs = _records_or_empty(resources.get("crithabs", []), "crithabs", unavailable)

        for crithab in crithabs:
            pop_id = _sid_value(crithab.get("populationSid", {}), "", "crithabs", unavailable)

            # Find matching species for detailed info
            species_name = "Unknown"
            scientific_name = ""
            listing_status = ""
            fr_date = ""
            fr_type = ""
            fr_url = ""

            if pop_id in populations:
                pop_data = populations[pop_id]
                pop = _dict_or_empty(pop_data.get("population", {}), "populationsBySid", unavailable)
                species_name = pop.get("optionalCommonName", "Unknown")
                scientific_name = pop.get("optionalScientificName", "")
                listing_status = pop.get("listingStatusName", "")

                # Get Federal Register critical habitat designation info
                fr_info = pop_data.get("optionalFederalRegisterCrithabStatus")
                if fr_info is not None:
                    fr_info = _dict_or_empty(fr_info, "populationsBySid", unavailable)
                if fr_info:
                    fr_date = fr_info.get("date", "")
                    fr_type = fr_info.get("displayType", "")
                    fr_url = fr_info.get("url", "")

            critical_habitat_list.append(
                {
                    "species_id": pop_id,
                    "common_name": species_name,
                    "scientific_name": scientific_name,
                    "listing_status": listing_status,
                    "critical_habitat_type": crithab.get("type", ""),
                    "species_in_footprint": crithab.get("speciesInFootprint", False),
                    "has_geometry": crithab.get("hasGeometry", False),
                    "federal_register_date": fr_date,
                    "federal_register_type": fr_type,
                    "federal_register_url": fr_url,
                }
            )

        # Marine Mammals - cross-reference with population data
        marine_mammals_list = []
        marine_mammals = _records_or_empty(resources.get("marineMammals", []), "marineMammals", unavailable)
        all_populations = _population_map(
            resources.get("allReferencedPopulationsBySid", {}), "allReferencedPopulationsBySid", unavailable
        )

        for mm in marine_mammals:
            pop_id = _sid_value(mm.get("populationSid", {}), "", "marineMammals", unavailable)

            # Try main populations first, then all referenced populations
            pop_data = populations.get(pop_id) or all_populations.get(pop_id)

            if not pop_data:
                # The resource exists even when its population lookup is absent.
                # Keep the identifier; do not turn an unresolved record into zero.
                unavailable.add("marineMammals")
                pop_data = {}
            # Handle both formats (with or without 'population' wrapper).
            pop = _dict_or_empty(pop_data.get("population", pop_data), "marineMammals", unavailable)
            marine_mammals_list.append(
                {
                    "species_id": pop_id,
                    "common_name": pop.get("optionalCommonName", "Unknown"),
                    "scientific_name": pop.get("optionalScientificName", ""),
                    "listing_status": pop.get("listingStatusName", ""),
                    "listing_code": pop.get("listingStatusCode", ""),
                    "group": pop.get("groupName", "Mammals"),
                }
            )

        # Fish Hatcheries - extract from facilities
        fish_hatcheries_list = []
        for hatchery in _resource_items(resources, "fishHatcheries", unavailable):
            fish_hatcheries_list.append(
                {
                    "name": hatchery.get("name", ""),
                    "type": hatchery.get("rslType", ""),
                    "acres": hatchery.get("acres", 0),
                    "org_code": hatchery.get("orgCode", ""),
                    "url": hatchery.get("url", ""),
                }
            )

        # The live API uses an items wrapper; retain support for legacy lists.
        coastal_data = resources.get("coastalBarriers", [])
        coastal_barriers = (
            _resource_items(resources, "coastalBarriers", unavailable)
            if isinstance(coastal_data, dict)
            else _records_or_empty(coastal_data, "coastalBarriers", unavailable)
        )
        result = {
            "center": {"latitude": lat, "longitude": lon},
            "buffer_miles": buffer_miles,
            "species": species_list,
            "migratory_birds": migbirds_list,
            "wetlands": wetlands_list,
            "refuges": refuges_list,
            "field_offices": field_offices,
            "critical_habitat": critical_habitat_list,
            "marine_mammals": marine_mammals_list,
            "fish_hatcheries": fish_hatcheries_list,
            "coastal_barriers": coastal_barriers,
            "partial": bool(unavailable),
            "unavailable_resource_fields": sorted(unavailable),
            "returned_counts": {},
            "raw_response": data,  # Include full response for advanced users
        }
        for field, collection, count_key, _label in _CATEGORIES:
            count = len(all_populations) if field == "allReferencedPopulationsBySid" else len(result[collection])
            result["returned_counts"][count_key] = count
            result[count_key] = None if _is_unavailable(field, unavailable) else count
        return result

    except requests.exceptions.RequestException as e:
        raise Exception(f"IPaC API request failed: {str(e)}")
    except (KeyError, ValueError) as e:
        raise Exception(f"Error parsing IPaC response: {str(e)}")


def format_ipac_summary(ipac_data: Dict) -> str:
    """
    Format IPaC data as a markdown summary.

    Args:
        ipac_data: Data from get_ipac_resources_in_roi()

    Returns:
        Formatted markdown string
    """
    center = ipac_data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = ipac_data.get("buffer_miles", 0)
    unavailable = set(ipac_data.get("unavailable_resource_fields") or [])

    lines = [
        "USFWS IPaC Resources within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        "",
    ]
    if ipac_data.get("partial") or unavailable:
        affected = [
            label.lower() for field, _collection, _count, label in _CATEGORIES if _is_unavailable(field, unavailable)
        ]
        lines.extend(
            [
                "PARTIAL IPAC RESPONSE",
                "IPaC did not return usable data for all records in: " + ", ".join(affected) + ".",
                "Unavailable categories are not confirmed no-hit findings and require reviewer follow-up.",
                "Usable records are retained below; affected category totals are unknown.",
                "",
            ]
        )
    for field, collection, count_key, label in _CATEGORIES:
        count = ipac_data.get(count_key, len(ipac_data.get(collection) or []))
        if _is_unavailable(field, unavailable) or count is None:
            count_text = "Unavailable in this response"
            retained = ipac_data.get("returned_counts", {}).get(count_key, 0)
            if retained:
                count_text += f" ({retained} records retained; not a complete count)"
        else:
            count_text = str(count)
        lines.append(f"{label}: {count_text}")
    lines.append("")

    critical = ipac_data.get("critical_habitat", [])
    if critical:
        lines.append("Critical Habitat Designations:")
        for habitat in critical:
            lines.append(
                f"- {habitat['common_name']} ({habitat['listing_status']}) – {habitat.get('critical_habitat_type', 'Unknown')} "
                f"(FR: {habitat.get('federal_register_date', 'N/A')})"
            )
        lines.append("")

    species = ipac_data.get("species", [])
    if species:
        lines.append("Threatened & Endangered Species:")
        for sp in species:
            lines.append(f"- {sp['common_name']} ({sp['scientific_name']}) – {sp['listing_status']}")
        lines.append("")

    birds = ipac_data.get("migratory_birds", [])
    if birds:
        lines.append("Representative Migratory Birds:")
        for bird in birds[:10]:
            lines.append(f"- {bird['common_name']} ({bird['conservation_level']})")
        if len(birds) > 10:
            lines.append(f"... and {len(birds) - 10} additional species")
        lines.append("")

    lines.append(
        "Coordinate with the responsible USFWS field office for ESA Section 7 consultation and MBTA compliance."
    )
    lines.append(
        "Screening information only; not an official species list, consultation determination, or evidence of absence."
    )

    return "\n".join(lines)
