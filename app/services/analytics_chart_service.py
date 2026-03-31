"""Chart data building and CSV export for analytics."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel_metric import ChannelMetric

logger = logging.getLogger(__name__)

METRIC_STYLES: dict[str, tuple[str, str]] = {
    "impressions": ("Impressions", "#6366f1"),
    "reach": ("Reach", "#22c55e"),
    "clicks": ("Clicks", "#eab308"),
    "engagement": ("Engagement", "#ef4444"),
    "spend": ("Spend", "#0f766e"),
    "conversions": ("Conversions", "#0891b2"),
    "likes": ("Likes", "#db2777"),
    "shares": ("Shares", "#7c3aed"),
    "retweets": ("Retweets", "#2563eb"),
    "sessions": ("Sessions", "#0ea5e9"),
    "pageviews": ("Pageviews", "#14b8a6"),
    "users": ("Users", "#84cc16"),
    "bounce_rate": ("Bounce Rate", "#f97316"),
}

FALLBACK_COLORS: tuple[str, ...] = (
    "#6366f1",
    "#22c55e",
    "#eab308",
    "#ef4444",
    "#0ea5e9",
    "#db2777",
    "#7c3aed",
    "#14b8a6",
)


class AnalyticsChartService:
    """Chart data building and CSV export for analytics."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def metric_style(metric_key: str, index: int = 0) -> tuple[str, str]:
        """Return (label, color) for a metric key."""
        if metric_key in METRIC_STYLES:
            return METRIC_STYLES[metric_key]
        return (
            metric_key.replace("_", " ").title(),
            FALLBACK_COLORS[index % len(FALLBACK_COLORS)],
        )

    @staticmethod
    def prepare_chart_channel_metrics(
        channel_metrics: list[dict[str, object]],
        metric_keys: list[str],
    ) -> list[dict[str, object]]:
        """Drop all-zero channels from visual charts to keep them readable."""
        return [
            row
            for row in channel_metrics
            if any(
                float(row["metrics"].get(metric, 0)) > 0  # type: ignore[union-attr]
                for metric in metric_keys
            )
        ]

    @staticmethod
    def build_time_series_chart(
        daily_rows: list[dict[str, str | float]],
        metric_keys: list[str],
    ) -> dict:
        """Build SVG-ready time series chart data.

        Returns dict with width, height, max_value, series, labels, grid_lines.
        Empty dict if no data.
        """
        if not daily_rows or not metric_keys:
            return {}

        grouped: dict[str, dict[str, float]] = {}
        for row in daily_rows:
            grouped.setdefault(str(row["date"]), {})
            grouped[str(row["date"])][str(row["metric_type"])] = float(row["total"])
        dates = sorted(grouped.keys())

        width = 760
        height = 220
        pad_x = 20
        pad_y = 20
        inner_width = width - (pad_x * 2)
        inner_height = height - (pad_y * 2)
        max_value = max(
            max(float(grouped[d].get(metric, 0)) for metric in metric_keys)
            for d in dates
        )
        if max_value <= 0:
            max_value = 1

        point_count = len(dates)
        denominator = max(point_count - 1, 1)
        series = []
        for index, metric in enumerate(metric_keys):
            label, color = AnalyticsChartService.metric_style(metric, index)
            points = []
            markers = []
            for point_index, chart_date in enumerate(dates):
                x = pad_x + (inner_width * point_index / denominator)
                if point_count == 1:
                    x = width / 2
                value = float(grouped[chart_date].get(metric, 0))
                y = height - pad_y - ((value / max_value) * inner_height)
                points.append(f"{x:.1f},{y:.1f}")
                markers.append(
                    {
                        "x": round(x, 1),
                        "y": round(y, 1),
                        "value": value,
                        "date": chart_date,
                    }
                )
            series.append(
                {
                    "key": metric,
                    "label": label,
                    "color": color,
                    "points": " ".join(points),
                    "markers": markers,
                }
            )

        return {
            "width": width,
            "height": height,
            "max_value": max_value,
            "series": series,
            "labels": [{"date": d, "short": d[5:]} for d in dates],
            "grid_lines": [
                {"y": pad_y + (inner_height * step / 4)} for step in range(5)
            ],
        }

    @staticmethod
    def build_channel_strengths(
        channel_metrics: list[dict[str, object]],
        metric_keys: list[str],
    ) -> list[dict[str, object]]:
        """Normalize per-channel metrics for a non-JS strengths view."""
        if not channel_metrics or not metric_keys:
            return []

        maxima = {
            metric: max(
                float(row["metrics"].get(metric, 0))  # type: ignore[union-attr]
                for row in channel_metrics
            )
            or 1
            for metric in metric_keys
        }
        strengths = []
        for row in channel_metrics:
            metrics = []
            for index, metric in enumerate(metric_keys):
                label, color = AnalyticsChartService.metric_style(metric, index)
                value = float(row["metrics"].get(metric, 0))  # type: ignore[union-attr]
                metrics.append(
                    {
                        "key": metric,
                        "label": label,
                        "value": value,
                        "pct": round((value / maxima[metric]) * 100)
                        if maxima[metric]
                        else 0,
                        "color": color,
                    }
                )
            strengths.append(
                {
                    "channel_name": row.get("channel_name", "Unknown"),
                    "metrics": metrics,
                }
            )
        return strengths

    def export_csv(
        self,
        *,
        start_date: date,
        end_date: date,
        metric_date: date | None = None,
        post_id: UUID | None = None,
    ) -> str:
        """Export metrics for date range as CSV string.

        Returns the CSV content. Caller wraps in StreamingResponse.
        """
        stmt = (
            select(ChannelMetric)
            .where(ChannelMetric.metric_date >= start_date)
            .where(ChannelMetric.metric_date <= end_date)
        )
        if metric_date is not None:
            stmt = stmt.where(ChannelMetric.metric_date == metric_date)
        if post_id is not None:
            stmt = stmt.where(ChannelMetric.post_id == post_id)
        stmt = stmt.order_by(ChannelMetric.metric_date, ChannelMetric.channel_id)
        metrics = list(self.db.scalars(stmt).all())

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "channel_id", "post_id", "metric_type", "value"])
        for m in metrics:
            writer.writerow(
                [
                    m.metric_date.isoformat(),
                    str(m.channel_id),
                    str(m.post_id) if m.post_id else "",
                    m.metric_type.value,
                    str(float(m.value)),
                ]
            )
        return output.getvalue()
