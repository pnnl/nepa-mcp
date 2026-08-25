"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# EPA ACRES BROWNFIELDS — ENVIROFACTS FACILITY POINTS
# =============================================================================

# EPA Envirofacts facility-points MapServer (EMEF efpoints)
ACRES_SERVICE_URL = "https://geopub.epa.gov/ArcGIS/rest/services/EMEF/efpoints/MapServer"
ACRES_BROWNFIELDS_LAYER_ID = 5  # "Brownfields": grantee-reported ACRES property points
