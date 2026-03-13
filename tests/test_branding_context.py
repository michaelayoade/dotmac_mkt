from __future__ import annotations

from app.services.branding import save_branding
from app.services.branding_context import (
    branding_context_from_values,
    load_branding_context,
)


def test_load_branding_context_includes_brand_and_css(db_session) -> None:
    context = load_branding_context(db_session)
    assert "branding" in context
    assert "brand" in context
    assert "org_branding" in context
    assert context["brand"]["name"]
    assert "--brand-primary:" in context["org_branding"]["css"]


def test_branding_context_from_saved_values(db_session) -> None:
    save_branding(
        db_session,
        {
            "display_name": "Acme Ops",
            "tagline": "Automation",
            "brand_mark": "AO",
            "primary_color": "#224466",
            "accent_color": "#EEAA33",
            "font_family_display": "Outfit",
            "font_family_body": "Inter",
        },
    )
    context = branding_context_from_values(
        load_branding_context(db_session)["branding"]
    )
    assert context["brand"]["name"] == "Acme Ops"
    assert context["brand"]["mark"] == "AO"
    assert "--brand-primary: #224466;" in context["org_branding"]["css"]
