import pytest

from epa_acres.src.apis import property_api as api
from nepa_mcp_common.http import UpstreamServiceError


def test_property_activity_and_paging(monkeypatch):
    def fetch(url, **kwargs):
        if "acres.grant_property/" in url:
            return [{"property_id": 12, "property_name": "Former mill", "current_owner": "private"}]
        if "acres.grant_property_accomplishment/" in url:
            assert "/sort/acres.grant_property_accomplishment.gpa_id:asc/2:3/" in url
            return [{"property_id": 12, "gpa_id": k, "gpa_type_id": 8, "gpa_completion_date": None} for k in (2, 3)]
        return [{"gpa_type_id": 8, "label_gpa_type": "Assessment"}]

    monkeypatch.setattr(api, "get_json_rows", fetch)
    r = api.property_records("12", 1, 1)
    assert r["records"] == [{"gpa_id": 2, "gpa_type_id": 8, "gpa_completion_date": None, "activity": "Assessment"}]
    assert r["next_offset"] == 2 and "current_owner" not in r["property"]


def test_grant_associations_and_unresolved_ids(monkeypatch):
    def fetch(url, **kwargs):
        if "acres.grant_property/" in url:
            return [{"property_id": 12}]
        if "grant_property_assoc" in url:
            return [{"property_id": 12, "grant_id": i} for i in [1, 2, None]]
        if "acres.grants" in url:
            assert "/grant_id/in/1,2/" in url
            return [
                {"grant_id": 1, "grant_type_id": 7, "recipient_name": "City", "award_amount_cumulative": 0},
                {"grant_id": 2, "grant_type_id": 7, "recipient_name": "County"},
            ]
        return [{"grant_type_id": 7, "label_grant_type": "Cleanup"}]

    monkeypatch.setattr(api, "get_json_rows", fetch)
    r = api.property_records("12", grants=True)
    assert r["status"] == "partial" and len(r["records"]) == 3
    assert r["records"][0]["award_amount_cumulative"] == 0 and r["records"][1]["grant_type"] == "Cleanup"


def test_empty_failed_or_partial(monkeypatch):
    monkeypatch.setattr(api, "get_json_rows", lambda *a, **k: [])
    assert api.property_records("12")["status"] == "empty"

    def fail(url, **k):
        raise UpstreamServiceError("service offline")

    monkeypatch.setattr(api, "get_json_rows", fail)
    result = api.property_records("12")
    assert result["status"] == "unavailable"
    assert "service offline" not in str(result["warnings"])
    with pytest.raises(ValueError):
        api.property_records("../12")
    monkeypatch.setattr(
        api, "get_json_rows", lambda url, **kw: [{"property_id": 12}] if "acres.grant_property/" in url else fail(url)
    )
    r = api.property_records("12")
    assert r["property"]["property_id"] == 12 and r["status"] == "partial"


def test_bad_property_link_does_not_swallow_page_boundary(monkeypatch):
    def fetch(url, **kwargs):
        if "acres.grant_property/" in url:
            return [{"property_id": 12}]
        return [{"property_id": 999, "grant_id": 1}, {"property_id": 12, "grant_id": 2}]

    monkeypatch.setattr(api, "get_json_rows", fetch)
    r = api.property_records("12", 1, grants=True)
    assert r["records"] == [] and r["next_offset"] == 1 and r["status"] == "partial"


def test_property_without_activity_still_has_profile(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_json_rows",
        lambda url, **kw: [{"property_id": 12, "property_name": "Mill"}] if "acres.grant_property/" in url else [],
    )
    r = api.property_records("00012")
    assert r["status"] == "complete" and r["records"] == [] and r["property"]["property_name"] == "Mill"
