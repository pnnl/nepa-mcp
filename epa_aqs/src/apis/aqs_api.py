"""
EPA Air Quality System (AQS) API Wrapper

This module provides functions to query the EPA AQS API for air quality monitoring
data within a specified region of interest. Used for NEPA/EIS baseline air quality
assessments.

API Documentation: https://aqs.epa.gov/aqsweb/documents/data_api.html

"""

import os
import time
import requests
import asyncio
import logging
from typing import Dict, List, Tuple

from src.apis.aqs_constants import (
    AQS_ENDPOINTS,
    NAAQS_STANDARDS,
    MAX_CONCURRENT_REQUESTS,
    RATE_LIMIT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    get_pollutant_name,
)
from nepa_mcp_common.arcgis import ArcGISService

logger = logging.getLogger(__name__)


class AQSAPIError(Exception):
    """Custom exception for EPA AQS API errors"""

    pass


def get_aqs_credentials() -> Tuple[str, str]:
    """
    Get EPA AQS API credentials from environment variables.

    Returns:
        Tuple of (email, api_key)

    Raises:
        ValueError: If credentials are not set
    """
    email = os.getenv("EPA_AQS_EMAIL")
    api_key = os.getenv("EPA_AQS_API_KEY")

    if not email or not api_key:
        raise ValueError(
            "EPA AQS API credentials not found. Please set EPA_AQS_EMAIL and "
            "EPA_AQS_API_KEY environment variables. Sign up at: "
            "https://aqs.epa.gov/data/api/signup"
        )

    return email, api_key


def calculate_bounding_box(lat: float, lon: float, buffer_miles: float) -> Dict[str, float]:
    """
    Calculate bounding box from center point and buffer distance.

    Uses ArcGIS buffer geometry to create accurate geodesic buffer,
    then extracts min/max lat/lon for API queries.

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        buffer_miles: Buffer distance in miles

    Returns:
        Dictionary with minlat, maxlat, minlon, maxlon
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

    # Extract extent from buffer geometry
    extent = ArcGISService.get_extent_from_geometry(buffer_geom)

    return {"minlat": extent["ymin"], "maxlat": extent["ymax"], "minlon": extent["xmin"], "maxlon": extent["xmax"]}


def split_date_ranges(begin_year: int, end_year: int) -> List[Tuple[str, str]]:
    """
    Split multi-year query into single-year date ranges.

    EPA AQS API requires begin and end dates to be in the same year.

    Args:
        begin_year: First year to query
        end_year: Last year to query

    Returns:
        List of (begin_date, end_date) tuples in YYYYMMDD format
    """
    date_ranges = []
    for year in range(begin_year, end_year + 1):
        begin_date = f"{year}0101"
        end_date = f"{year}1231"
        date_ranges.append((begin_date, end_date))

    return date_ranges


def _query_aqs_api_sync(endpoint: str, params: Dict, max_retries: int = 3) -> Dict:
    """
    Synchronous query to EPA AQS API with error handling and retries.

    Args:
        endpoint: API endpoint URL
        params: Query parameters
        max_retries: Maximum number of retry attempts

    Returns:
        API response data

    Raises:
        AQSAPIError: If API request fails
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(endpoint, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()

            data = response.json()

            # Check for API-specific errors in Header
            if "Header" in data and len(data["Header"]) > 0:
                header = data["Header"][0]
                status = header.get("status", "")

                # "No data matched your selection" is a valid response, not an error
                if status not in ("Success", "No data matched your selection"):
                    error_msg = header.get("error", status or "Unknown error")
                    raise AQSAPIError(f"AQS API error: {error_msg}")

            return data

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = 2**attempt
                logger.warning(f"Request timeout, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise AQSAPIError("Request timed out after multiple retries")

        except requests.exceptions.HTTPError as e:
            raise AQSAPIError(f"HTTP error: {e}")

        except Exception as e:
            raise AQSAPIError(f"Unexpected error: {e}")


async def _query_monitors_for_param(
    semaphore: asyncio.Semaphore, endpoint: str, params: Dict, param_code: str
) -> List[Dict]:
    """
    Query monitors for a single parameter with semaphore rate limiting.

    Args:
        semaphore: Asyncio semaphore for rate limiting
        endpoint: API endpoint URL
        params: Query parameters
        param_code: Parameter code being queried (for logging)

    Returns:
        List of monitor records
    """
    async with semaphore:
        pollutant = get_pollutant_name(param_code)
        start_time = time.time()
        logger.debug(f"  [START] Querying monitors for {pollutant}...")

        # Run sync query in thread pool to avoid blocking event loop
        data = await asyncio.to_thread(_query_aqs_api_sync, endpoint, params)

        elapsed = time.time() - start_time
        monitors = data.get("Data", [])
        logger.debug(f"    [DONE] {pollutant}: {len(monitors)} monitors in {elapsed:.2f}s")

        # Rate limiting delay
        await asyncio.sleep(RATE_LIMIT_SECONDS)

        return monitors


async def get_monitors_by_box(
    bbox: Dict[str, float], begin_date: str, end_date: str, param_codes: List[str]
) -> List[Dict]:
    """
    Get air quality monitoring stations within a bounding box.

    Uses parallel queries with semaphore rate limiting for faster performance.

    Args:
        bbox: Bounding box with minlat, maxlat, minlon, maxlon
        begin_date: Begin date in YYYYMMDD format
        end_date: End date in YYYYMMDD format
        param_codes: List of parameter codes to query

    Returns:
        List of monitor records (deduplicated by the AQS monitor identity:
        state, county, site, parameter, and parameter occurrence code)
    """
    email, api_key = get_aqs_credentials()
    overall_start = time.time()

    logger.info(
        f"[MONITORS] Starting parallel queries for {len(param_codes)} pollutants (max {MAX_CONCURRENT_REQUESTS} concurrent)"
    )

    # Build tasks for parallel execution
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    tasks = []

    for param_code in param_codes:
        params = {
            "email": email,
            "key": api_key,
            "param": param_code,
            "bdate": begin_date,
            "edate": end_date,
            "minlat": bbox["minlat"],
            "maxlat": bbox["maxlat"],
            "minlon": bbox["minlon"],
            "maxlon": bbox["maxlon"],
        }

        tasks.append(
            _query_monitors_for_param(
                semaphore=semaphore, endpoint=AQS_ENDPOINTS["monitors_by_box"], params=params, param_code=param_code
            )
        )

    # Execute all queries in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and deduplicate
    all_monitors = []
    monitor_ids = set()

    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Monitor query failed: {result}")
            continue

        for monitor in result:
            monitor_id = (
                monitor.get("state_code"),
                monitor.get("county_code"),
                monitor.get("site_number"),
                monitor.get("parameter_code"),
                monitor.get("poc"),
            )

            if monitor_id not in monitor_ids:
                monitor_ids.add(monitor_id)
                all_monitors.append(monitor)

    overall_elapsed = time.time() - overall_start
    logger.info(f"[MONITORS] Completed in {overall_elapsed:.2f}s - found {len(all_monitors)} unique monitors")

    return all_monitors


async def _query_annual_data_for_param_year(
    semaphore: asyncio.Semaphore,
    endpoint: str,
    params: Dict,
    param_code: str,
    year: str,
    query_num: int,
    total_queries: int,
) -> List[Dict]:
    """
    Query annual data for a single parameter/year with semaphore rate limiting.

    Args:
        semaphore: Asyncio semaphore for rate limiting
        endpoint: API endpoint URL
        params: Query parameters
        param_code: Parameter code being queried
        year: Year being queried (for logging)
        query_num: Current query number (for logging)
        total_queries: Total number of queries (for logging)

    Returns:
        List of annual data records
    """
    async with semaphore:
        pollutant = get_pollutant_name(param_code)
        start_time = time.time()
        logger.debug(f"  [START] {pollutant} ({year}) - {query_num}/{total_queries}")

        # Run sync query in thread pool to avoid blocking event loop
        data = await asyncio.to_thread(_query_aqs_api_sync, endpoint, params)

        elapsed = time.time() - start_time
        records = data.get("Data", [])
        logger.debug(f"    [DONE] {pollutant} ({year}): {len(records)} records in {elapsed:.2f}s")

        # Rate limiting delay
        await asyncio.sleep(RATE_LIMIT_SECONDS)

        return records


async def get_annual_data_by_box(
    bbox: Dict[str, float], begin_year: int, end_year: int, param_codes: List[str]
) -> List[Dict]:
    """
    Get annual air quality summary data within a bounding box.

    Uses parallel queries with semaphore rate limiting for faster performance.

    Args:
        bbox: Bounding box with minlat, maxlat, minlon, maxlon
        begin_year: First year to query
        end_year: Last year to query
        param_codes: List of parameter codes to query

    Returns:
        List of annual data records
    """
    email, api_key = get_aqs_credentials()
    overall_start = time.time()

    date_ranges = split_date_ranges(begin_year, end_year)
    total_queries = len(date_ranges) * len(param_codes)

    logger.info(
        f"[ANNUAL] Starting parallel queries: {len(param_codes)} pollutants x {len(date_ranges)} years = {total_queries} queries"
    )

    # Build tasks for parallel execution
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    tasks = []
    query_num = 0

    for begin_date, end_date in date_ranges:
        for param_code in param_codes:
            query_num += 1
            params = {
                "email": email,
                "key": api_key,
                "param": param_code,
                "bdate": begin_date,
                "edate": end_date,
                "minlat": bbox["minlat"],
                "maxlat": bbox["maxlat"],
                "minlon": bbox["minlon"],
                "maxlon": bbox["maxlon"],
            }

            year = begin_date[:4]
            tasks.append(
                _query_annual_data_for_param_year(
                    semaphore=semaphore,
                    endpoint=AQS_ENDPOINTS["annual_data_by_box"],
                    params=params,
                    param_code=param_code,
                    year=year,
                    query_num=query_num,
                    total_queries=total_queries,
                )
            )

    # Execute all queries in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect all data
    all_data = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Annual data query failed: {result}")
            continue
        all_data.extend(result)

    overall_elapsed = time.time() - overall_start
    logger.info(f"[ANNUAL] Completed in {overall_elapsed:.2f}s - found {len(all_data)} records")

    return all_data


def assess_naaqs_compliance(annual_data: List[Dict]) -> Dict[str, Dict]:
    """
    Screen annual air quality data against selected NAAQS values.

    Args:
        annual_data: List of annual air quality records

    Returns:
        Dictionary with screening comparison for each pollutant
    """
    compliance = {}

    # Group data by pollutant
    by_pollutant = {}
    for record in annual_data:
        pollutant = get_pollutant_name(record.get("parameter_code", ""))

        if pollutant not in by_pollutant:
            by_pollutant[pollutant] = []

        by_pollutant[pollutant].append(record)

    # Compare each pollutant to the configured screening value.
    for pollutant, records in by_pollutant.items():
        if pollutant not in NAAQS_STANDARDS:
            continue

        standards = NAAQS_STANDARDS[pollutant]
        has_annual_standard = "annual" in standards
        if has_annual_standard:
            standard_info = standards["annual"]
        else:
            # Short-duration standards cannot be classified from annual means.
            standard_info = next(iter(standards.values()))

        if not standard_info:
            continue

        # Calculate statistics
        means = []
        max_values = []
        exceedances = []

        for record in records:
            mean = record.get("arithmetic_mean")
            max_val = record.get("first_max_value")
            exceedance_count = record.get("primary_exceedance_count", 0)

            if mean is not None:
                try:
                    means.append(float(mean))
                except (ValueError, TypeError):
                    pass

            if max_val is not None:
                try:
                    max_values.append(float(max_val))
                except (ValueError, TypeError):
                    pass

            if exceedance_count is not None:
                try:
                    exceedances.append(int(exceedance_count))
                except (ValueError, TypeError):
                    pass

        if not means:
            continue

        avg_mean = sum(means) / len(means)
        max_of_max = max(max_values) if max_values else None
        total_exceedances = sum(exceedances) if exceedances else 0

        standard_value = standard_info["value"]
        if has_annual_standard:
            exceeds = avg_mean > standard_value
            comparison_status = "above" if exceeds else "at_or_below"
            exceedance_percent = round((avg_mean - standard_value) / standard_value * 100, 1) if exceeds else 0
            comparison_note = "Annual mean screening comparison; this is not a regulatory design-value determination."
        else:
            exceeds = None
            comparison_status = "not_evaluated"
            exceedance_percent = None
            comparison_note = (
                "Selected NAAQS value uses a short-duration form; annual AQS means are shown for context only."
            )

        compliance[pollutant] = {
            "avg_annual_mean": round(avg_mean, 3),
            "max_value": round(max_of_max, 3) if max_of_max else None,
            "naaqs_standard": standard_value,
            "naaqs_units": standard_info["units"],
            "naaqs_averaging_time": standard_info["averaging_time"],
            "naaqs_form": standard_info.get("form", ""),
            "exceeds_standard": exceeds,
            "comparison_status": comparison_status,
            "comparison_note": comparison_note,
            "exceedance_percent": exceedance_percent,
            "total_exceedance_days": total_exceedances,
            "num_records": len(records),
            "num_monitors": len(set(r.get("site_number") for r in records)),
        }

    return compliance


def _monitor_pollutant_name(monitor: Dict) -> str:
    """Return a display name from an AQS monitor record."""
    name = monitor.get("parameter_name") or monitor.get("parameter")
    if name:
        return str(name)

    parameter_code = str(monitor.get("parameter_code") or "")
    return get_pollutant_name(parameter_code) if parameter_code else "Unknown"


def _monitor_active_range(monitor: Dict) -> str:
    """Format the operating period exposed by the AQS monitors endpoint."""
    opened = monitor.get("open_date") or monitor.get("first_year_of_data")
    closed = monitor.get("close_date") or monitor.get("last_year_of_data")

    if opened and closed:
        return f"{opened} - {closed}"
    if opened:
        return f"{opened} - Present"
    if closed:
        return f"Unknown - {closed}"
    return "Unknown"


def format_monitors_summary(monitors: List[Dict], lat: float, lon: float, buffer_miles: float) -> str:
    """
    Format monitor data as markdown summary.

    Args:
        monitors: List of monitor records
        lat: Center latitude
        lon: Center longitude
        buffer_miles: Buffer distance

    Returns:
        Markdown formatted summary
    """
    summary = f"""# EPA Air Quality Monitors

**Location**: ({lat}, {lon})
**Search Radius**: {buffer_miles} miles
**Total Monitors**: {len(monitors)}

"""

    if not monitors:
        summary += "No monitors found in the specified area.\n"
        return summary

    # Group by parameter
    by_param = {}
    for monitor in monitors:
        param = _monitor_pollutant_name(monitor)
        if param not in by_param:
            by_param[param] = []
        by_param[param].append(monitor)

    summary += "## Monitors by Pollutant\n\n"
    for param, mons in sorted(by_param.items()):
        summary += f"### {param}\n"
        summary += f"**Count**: {len(mons)} monitors\n\n"

        for mon in mons[:5]:  # Show first 5
            site_name = mon.get("local_site_name") or "Unknown"
            site_id = f"{mon.get('state_code', '')}-{mon.get('county_code', '')}-{mon.get('site_number', '')}"
            poc = mon.get("poc")
            poc_display = f", POC: {poc}" if poc is not None else ""
            active_range = _monitor_active_range(mon)
            summary += f"- **{site_name}** (ID: {site_id}{poc_display}, Active: {active_range})\n"

        if len(mons) > 5:
            summary += f"- ... and {len(mons) - 5} more\n"

        summary += "\n"

    return summary


def format_air_quality_summary(
    annual_data: List[Dict],
    compliance: Dict[str, Dict],
    lat: float,
    lon: float,
    buffer_miles: float,
    begin_year: int,
    end_year: int,
) -> str:
    """
    Format air quality data and NAAQS screening comparisons as markdown summary.

    Args:
        annual_data: List of annual data records
        compliance: Screening comparison
        lat: Center latitude
        lon: Center longitude
        buffer_miles: Buffer distance
        begin_year: First year
        end_year: Last year

    Returns:
        Markdown formatted summary
    """
    year_range = f"{begin_year}-{end_year}" if begin_year != end_year else str(begin_year)

    summary = f"""# Air Quality Baseline Assessment

**Location**: ({lat}, {lon})
**Search Radius**: {buffer_miles} miles
**Time Period**: {year_range}
**Total Data Records**: {len(annual_data)}

"""

    if not compliance:
        summary += "No air quality data available for NAAQS screening comparison.\n"
        return summary

    summary += "## NAAQS Annual-Metric Screening\n\n"
    summary += (
        "Note: This is a screening summary from annual AQS statistics, not a regulatory NAAQS "
        "design-value or attainment determination. Short-duration NAAQS values are shown for context only.\n\n"
    )

    # Count screening classifications.
    exceeds = sum(1 for c in compliance.values() if c.get("comparison_status") == "above")
    at_or_below = sum(1 for c in compliance.values() if c.get("comparison_status") == "at_or_below")
    context_only = sum(1 for c in compliance.values() if c.get("comparison_status") == "not_evaluated")

    summary += f"**Pollutants at or below selected annual NAAQS value**: {at_or_below}\n"
    summary += f"**Pollutants above selected annual NAAQS value**: {exceeds}\n"
    summary += f"**Pollutants with short-duration NAAQS shown for context only**: {context_only}\n\n"

    # Detail each pollutant
    for pollutant in sorted(compliance.keys()):
        data = compliance[pollutant]
        summary += f"### {pollutant}\n\n"
        summary += f"- **Average Annual Mean**: {data['avg_annual_mean']} {data['naaqs_units']}\n"
        summary += (
            f"- **Selected NAAQS Context Value**: {data['naaqs_standard']} {data['naaqs_units']} "
            f"({data['naaqs_averaging_time']})\n"
        )

        if data.get("comparison_status") == "above":
            summary += f"- **Status**: Above selected standard value by {data['exceedance_percent']}%\n"
        elif data.get("comparison_status") == "at_or_below":
            summary += "- **Status**: At or below selected standard value\n"
        else:
            summary += "- **Status**: Context only; no annual-mean NAAQS status assigned\n"

        summary += f"- **Screening Note**: {data['comparison_note']}\n"

        if data.get("max_value"):
            summary += f"- **Maximum Value**: {data['max_value']} {data['naaqs_units']}\n"

        if data.get("total_exceedance_days", 0) > 0:
            summary += f"- **Exceedance Days**: {data['total_exceedance_days']}\n"

        summary += f"- **Data from**: {data['num_monitors']} monitors, {data['num_records']} records\n\n"

    return summary
