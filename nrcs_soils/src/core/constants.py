"""Constants for USDA-NRCS Soil Data Access."""

SDA_POST_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SDA_HELP_URL = "https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx"
WEB_SOIL_SURVEY_URL = "https://websoilsurvey.sc.egov.usda.gov/App/WebSoilSurvey.aspx"

SDA_TIMEOUT_SECONDS = 30
MAX_MAPUNITS = 500
MAX_COMPONENT_ROWS = 5_000
MAX_DETAIL_MAPUNITS = 25
MAX_MAPUNIT_PAGE_SIZE = 100
MAX_MAPUNIT_OFFSET = MAX_MAPUNITS - 1
