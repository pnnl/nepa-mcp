"""Verified public Socrata source and exact source field names."""

DATASET_ID = "mcm3-xbid"
API_URL = f"https://data.permits.performance.gov/resource/{DATASET_ID}.json"
METADATA_URL = f"https://data.permits.performance.gov/api/views/{DATASET_ID}.json"
DATASET_URL = f"https://data.permits.performance.gov/d/{DATASET_ID}"
QUERY_TIMEOUT_SECONDS = 15
TOOL_TIMEOUT_SECONDS = 75.0
MAX_RESULTS = 100
MAX_TIMETABLE_ROWS = 1000
MAX_OFFSET = 100_000
PROJECT_STATUSES = ("In Progress", "Planned", "Paused", "Complete", "Cancelled", "Class of Action Changed")
MODES = ("upcoming", "recently_completed", "past_target")
STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
    "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI".split()
)
EFFECTIVE_TARGET = "coalesce(milestone_alternative_completion_date,action_milestone_completion_target)"
COVERAGE_NOTE = (
    "Agency-reported reviews for projects listed on the federal Permitting Dashboard; "
    "not an inventory of every project or required permit. Complete refers to the reported review, not construction."
)

PROJECT_FIELDS = (
    "project_id",
    "project_title",
    "project_field_project_lead_agency",
    "project_field_project_lead_agency_bureau",
    "project_category",
    "project_field_project_status",
    "project_sector",
    "project_sector_type",
    "project_field_project_sponsor_agency",
    "project_field_location_state",
    "project_field_location_county",
    "project_field_location_city",
    "project_field_location_other",
    "project_lat",
    "project_lon",
    "project_latlong",
    "project_url",
    "project_pause_start",
    "project_pause_end",
    "total_estimated_project_cost",
)
ACTION_FIELDS = (
    "action_id",
    "action_type",
    "action_status",
    "action_agency",
    "action_description",
    "action_agency_status",
    "action_agency_declined",
    "action_outcome",
    "action_identifier",
    "action_pause_start",
    "action_pause_end",
    "action_justification_paused_title",
    "action_justification_paused_url",
    "action_reference_id",
)
MILESTONE_FIELDS = (
    "milestone_id",
    "unique_id",
    "milestone_type",
    "action_milestone_name",
    "action_milestone_details",
    "action_milestone_group",
    "action_milestone_na",
    "action_milestone_complete",
    "action_milestone_completion_target",
    "action_milestone_completion_actual",
    "action_milestone_baseline_target",
    "milestone_alternative_completion_date",
    "milestone_conditional_target_date",
    "milestone_reason_for_date_change",
    "dependency_action",
    "dependency_action_id",
    "dependency_milestone",
    "dependency_milestone_id",
    "action_milestone_dependencies",
    "action_optional_milestone",
    "action_milestone_classification",
    "action_milestone_final_milestone",
    "action_triggering_milestone",
    "non_conformance_milestone",
)
