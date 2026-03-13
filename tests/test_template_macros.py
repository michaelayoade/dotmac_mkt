from __future__ import annotations

from app.templates import templates


def _render(snippet: str, **context) -> str:
    wrapped = "{% autoescape true %}" + snippet + "{% endautoescape %}"
    return templates.env.from_string(wrapped).render(**context)


def test_sortable_th_renders_expected_query_params() -> None:
    html = _render(
        """
{% from "components/macros.html" import sortable_th %}
<table><thead><tr>{{ sortable_th("Email", "email", "email", "desc", "/", {"page": 2}) }}</tr></thead></table>
"""
    )
    assert "sort=email" in html
    assert "dir=asc" in html
    assert "page=2" in html


def test_status_badge_renders_status_text() -> None:
    html = _render(
        """
{% from "components/macros.html" import status_badge %}
{{ status_badge("active") }}
"""
    )
    assert "Active" in html
