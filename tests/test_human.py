import json

import pytest

from voygr.human import format_human

# The live /v1/pricing card, as captured on 21 Oct 2026.
PRICING_CARD = {
    "unit": "credits",
    "rates": [
        {"key": "call", "label": "Phone call that reaches a person", "credits": 10, "per": "answered call",
         "hold": 30, "operator_owned": False, "note": "No answer, voicemail and hang-ups are free."},
        {"key": "place_suggest", "label": "Place research", "credits": 5, "per": "request",
         "hold": 15, "operator_owned": True, "note": None},
        {"key": "validation", "label": "Single-record validation and enrichment", "credits": 1,
         "credits_range": None, "per": "request", "hold": None, "operator_owned": False,
         "routes": ["POST /v1/validate"], "note": "Batch, list, deep-research and discovery work is priced per row."},
        {"key": "enrich_standard", "label": "Standard attributes", "credits": 1, "per": "place",
         "hold": None, "operator_owned": False, "routes": ["POST /v1/enrich"],
         "fields": ["email", "existence", "facebook", "instagram", "open_closed", "opening_hours", "phone",
                    "tiktok", "website", "x"],
         "note": "One credit per place however many standard attributes you request."},
        {"key": "enrich_research", "label": "Research fields", "credits": 1, "per": "place per field",
         "hold": None, "operator_owned": False, "routes": ["POST /v1/enrich"],
         "note": "Any attribute outside the standard set."},
    ],
    "packs_url": "/checkout/packs",
    "docs_url": "/docs",
    "per_key_rates_url": "/v1/usage",
}

FREE_USAGE = {
    "tier": "free", "quota_limit": 2500, "current_usage": 0, "remaining": 2500, "available": 2500,
    "percentage_used": 0.0, "reset_date": "2099-12-31", "period": "lifetime", "status": "active",
}


def validate_result(status, **operational):
    return {
        "success": True,
        "existence_confidence": 0.94,
        "operational_status": {"status": status, **operational},
        "request_id": "req_abc",
    }


def human(cmd, data, color=False):
    return format_human(cmd, data, color=color)


# validate

def test_validate_open():
    out = human("validate", validate_result("open"))
    assert "0.94" in out
    assert "open" in out


def test_validate_closed_shows_reason():
    out = human("validate", validate_result("closed", closure_reason="permanent", closure_confidence=0.8))
    assert "closed (permanent)" in out


def test_validate_closed_without_reason():
    out = human("validate", validate_result("closed", closure_reason=None))
    assert "closed" in out
    assert "()" not in out
    assert "None" not in out


def test_validate_not_exists():
    data = validate_result("not_exists", closure_reason=None, closure_confidence=None)
    data["existence_confidence"] = 0.03
    out = human("validate", data)
    assert "not_exists" in out
    assert "0.03" in out
    assert "None" not in out


def test_validate_shows_request_id():
    assert "req_abc" in human("validate", validate_result("open"))


def test_validate_missing_fields_do_not_crash():
    out = human("validate", {"success": True})
    assert "unknown" in out
    assert "None" not in out


# enrich

def test_enrich_attributes():
    data = {"success": True, "attributes": {"phone": {"value": "+14155551234", "confidence": "high"}}}
    assert human("enrich", data) == "phone: +14155551234 (high)"


def test_enrich_one_line_per_attribute():
    data = {"success": True, "attributes": {
        "phone": {"value": "+14155551234", "confidence": "high"},
        "website": {"value": "https://example.com", "confidence": "medium"},
    }}
    assert human("enrich", data).splitlines() == [
        "phone: +14155551234 (high)", "website: https://example.com (medium)",
    ]


def test_enrich_cell_and_object_values():
    hours = {"monday": [{"open": "09:00", "close": "17:00"}]}
    data = {"success": True, "attributes": {
        "opening_hours": {"value": hours, "confidence": "medium"},
        "owner": {"value": None, "confidence": None, "abstain_reason": "not_found"},
        "outdoor_seating": {"value": True, "confidence": "low"},
        "price_band": {"value": None, "confidence": None},
    }}
    lines = human("enrich", data).splitlines()
    assert lines[0] == 'opening_hours: {"monday":[{"open":"09:00","close":"17:00"}]} (medium)'
    assert lines[1] == "owner: not found"
    assert lines[2] == "outdoor_seating: true (low)"
    assert lines[3] == "price_band: unavailable"


def test_enrich_keeps_unicode():
    data = {"success": True, "attributes": {"owner": {"value": {"name": "Zoë Müller"}, "confidence": "high"}}}
    assert "Zoë Müller" in human("enrich", data)


def test_enrich_estimate():
    data = {"success": True, "attributes": {}, "meta": {"stopped_reason": "estimate_only", "estimated_credits": 2}}
    assert human("enrich", data) == "Estimated cost: 2 credits. Nothing was charged."


def test_enrich_estimate_one_credit_is_singular():
    data = {"success": True, "attributes": {}, "meta": {"stopped_reason": "estimate_only", "estimated_credits": 1}}
    assert human("enrich", data) == "Estimated cost: 1 credit. Nothing was charged."


PHONE = {"phone": {"value": "+14155551234", "confidence": "high"}}


def test_enrich_shows_existence_and_status_before_the_attributes():
    data = {"success": True, "status": {"existence_confidence": 0.94},
            "operational_status": {"status": "closed", "closure_reason": "permanent"}, "attributes": PHONE}
    assert human("enrich", data).splitlines() == [
        "Existence: 0.94 confidence", "Status:    closed (permanent)", "phone: +14155551234 (high)",
    ]


def test_enrich_open_place_has_no_reason():
    data = {"success": True, "status": {"existence_confidence": 0.94},
            "operational_status": {"status": "open", "closure_reason": None}, "attributes": PHONE}
    assert human("enrich", data).splitlines()[:2] == ["Existence: 0.94 confidence", "Status:    open"]


def test_enrich_with_only_one_part_marks_the_other_unknown_like_validate_does():
    only_status = {"success": True, "status": {"existence_confidence": 0.5}, "attributes": PHONE}
    assert human("enrich", only_status).splitlines() == [
        "Existence: 0.50 confidence", "Status:    unknown", "phone: +14155551234 (high)",
    ]
    only_operational = {"success": True, "operational_status": {"status": "open"}, "attributes": PHONE}
    assert human("enrich", only_operational).splitlines() == [
        "Existence: unknown", "Status:    open", "phone: +14155551234 (high)",
    ]


def test_enrich_unavailable_existence_says_unknown():
    data = {"success": True, "status": {"existence_confidence": None},
            "operational_status": {"status": "open"}, "attributes": PHONE}
    assert human("enrich", data).splitlines()[:2] == ["Existence: unknown", "Status:    open"]


def test_enrich_without_status_blocks_is_unchanged():
    data = {"success": True, "status": None, "operational_status": None, "attributes": PHONE}
    assert human("enrich", data) == "phone: +14155551234 (high)"


def test_enrich_shows_the_same_lines_as_validate_for_the_same_verdict():
    verdict = {"existence_confidence": 0.94, "operational_status": {"status": "closed", "closure_reason": "permanent"}}
    enriched = human("enrich", {"success": True, "status": {"existence_confidence": 0.94},
                                "operational_status": verdict["operational_status"], "attributes": PHONE})
    assert enriched.splitlines()[:2] == human("validate", {"success": True, **verdict}).splitlines()


def test_enrich_ignores_status_blocks_that_are_not_objects():
    data = {"success": True, "status": "active", "operational_status": "open", "attributes": PHONE}
    assert human("enrich", data) == "phone: +14155551234 (high)"


def test_enrich_status_without_attributes_is_not_empty():
    data = {"success": True, "operational_status": {"status": "open"}, "attributes": {}}
    assert human("enrich", data) == "Existence: unknown\nStatus:    open"


def test_enrich_status_comes_before_summary_too():
    data = {"success": True, "operational_status": {"status": "open"}, "place_summary": "A small cafe.",
            "attributes": PHONE}
    assert human("enrich", data).splitlines() == [
        "Existence: unknown", "Status:    open", "phone: +14155551234 (high)", "Summary: A small cafe.",
    ]


def test_enrich_estimate_ignores_status_blocks():
    data = {"success": True, "attributes": {}, "operational_status": {"status": "open"},
            "meta": {"stopped_reason": "estimate_only", "estimated_credits": 1}}
    assert human("enrich", data) == "Estimated cost: 1 credit. Nothing was charged."


def test_enrich_summary_after_attributes():
    data = {"success": True, "place_summary": "A small cafe.",
            "attributes": {"phone": {"value": "+14155551234", "confidence": "high"}}}
    assert human("enrich", data).splitlines() == ["phone: +14155551234 (high)", "Summary: A small cafe."]


def test_enrich_without_attributes():
    assert human("enrich", {"success": True, "attributes": {}, "meta": {"stopped_reason": "completed"}}) \
        == "No attributes returned."


# usage

def test_usage():
    out = human("usage", FREE_USAGE)
    assert "free" in out
    assert "2500" in out
    assert "0.0%" in out


def test_usage_lifetime_hides_placeholder_reset_date():
    assert "2099" not in human("usage", FREE_USAGE)


def test_usage_shows_reset_date_for_periodic_plans():
    data = {**FREE_USAGE, "tier": "pro", "period": "monthly", "reset_date": "2026-11-01"}
    out = human("usage", data)
    assert "Resets" in out
    assert "2026-11-01" in out


def test_usage_progress_bar_fills_with_usage():
    data = {**FREE_USAGE, "current_usage": 1250, "available": 1250, "percentage_used": 50.0}
    out = human("usage", data)
    assert "█" * 10 + "░" * 10 in out
    assert "50.0%" in out


def test_usage_sparse_data_does_not_crash():
    out = human("usage", {"quota_limit": 100, "remaining": 88})
    assert "88" in out
    assert "100" in out


# pricing

def test_pricing():
    lines = human("pricing", PRICING_CARD).splitlines()
    assert lines == [
        "Phone call that reaches a person: 10 credits per answered call",
        "Place research: 5 credits per request",
        "Single-record validation and enrichment: 1 credit per request",
        "Standard attributes: 1 credit per place",
        "Research fields: 1 credit per place per field",
    ]


def test_pricing_without_rates():
    assert human("pricing", {"unit": "credits", "rates": []}) == "No rates returned."


# jobs

def test_job_status():
    data = {"batch_id": "b-1", "status": "running", "total_items": 3,
            "progress": {"processed": 2, "succeeded": 1, "failed": 1}}
    out = human("status", data)
    assert "b-1" in out
    assert "running" in out
    assert "2/3" in out
    assert "1 failed" in out


def test_job_status_without_progress():
    out = human("status", {"batch_id": "b-1", "status": "queued", "total_items": 3})
    assert out == "Job b-1: queued"


def test_job_status_shows_error():
    out = human("status", {"batch_id": "b-1", "status": "failed", "total_items": 3, "error": "Out of credits"})
    assert "failed" in out
    assert "Error: Out of credits" in out


def test_job_cancel():
    out = human("cancel", {"batch_id": "b-1", "status": "cancelled"})
    assert "b-1" in out
    assert "cancelled" in out
    assert "billed" in out


# account commands

def test_signup_adds_recover_hint():
    out = human("signup", {"success": True, "message": "If this is a new email, an API key has been sent."})
    assert out.splitlines() == [
        "If this is a new email, an API key has been sent.",
        "To recover a key from the terminal, run: voygr recover <email>",
    ]


def test_signup_without_message_still_has_hint():
    assert "voygr recover <email>" in human("signup", {"success": True})


def test_recover_uses_server_message():
    assert human("recover", {"message": "Check your inbox."}) == "Check your inbox."


def test_login_and_logout_messages():
    assert human("login", {"message": "API key saved"}) == "API key saved"
    assert human("logout", {"message": "API key removed"}) == "API key removed"


# colour and fallback

COLOURED_CASES = [
    ("validate", validate_result("open")),
    ("validate", validate_result("closed", closure_reason="permanent")),
    ("enrich", {"success": True, "operational_status": {"status": "closed"}, "attributes": {}}),
    ("login", {"message": "API key saved"}),
    ("status", {"batch_id": "b-1", "status": "completed", "total_items": 1,
                "progress": {"processed": 1, "succeeded": 1, "failed": 0}}),
]


@pytest.mark.parametrize("cmd,data", COLOURED_CASES)
def test_color_adds_ansi(cmd, data):
    assert "\x1b[" in human(cmd, data, color=True)


@pytest.mark.parametrize("cmd,data", COLOURED_CASES + [("usage", FREE_USAGE), ("pricing", PRICING_CARD)])
def test_no_color_has_no_ansi(cmd, data):
    assert "\x1b[" not in human(cmd, data, color=False)


def test_unknown_command_falls_back_to_json():
    data = {"name": "Café Zürich", "n": 1}
    out = human("whatever", data)
    assert json.loads(out) == data
    assert "Café Zürich" in out
    assert "\n" in out
