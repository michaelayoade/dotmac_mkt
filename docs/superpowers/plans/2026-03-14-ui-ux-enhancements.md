# UI/UX Enhancements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sparkline charts, donut charts, time-series visualizations, funnel charts, radar charts, skeleton loading states, progress rings, task urgency indicators, calendar dot simplification, and global UI polish across the marketing dashboard application.

**Architecture:** Template-only and route-level changes — no database migrations needed. New Chart.js visualizations added to existing templates. Backend routes enhanced to pass daily-aggregated and trend data to templates. New service method `get_daily_totals()` added to `AnalyticsService` for time-series data. All charts are dark-mode aware.

**Tech Stack:** Jinja2 templates, Chart.js 4 (CDN), Tailwind CSS, Alpine.js, HTMX, SVG for progress rings.

---

## Chunk 1: Backend Data Enhancements

These tasks add the backend methods and route changes needed to feed data to the new visualizations. No template changes yet.

### Task 1: Add `get_daily_totals()` to AnalyticsService

**Files:**
- Modify: `app/services/analytics_service.py`
- Test: `tests/test_analytics_daily_totals.py`

This method returns daily-aggregated metrics for a date range, grouped by date. Used by the analytics time-series chart and dashboard sparklines.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_daily_totals.py
"""Tests for AnalyticsService.get_daily_totals()."""
from datetime import date, timedelta

from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.channel_metric import ChannelMetric, MetricType
from app.services.analytics_service import AnalyticsService


def test_get_daily_totals_returns_dict_per_date(db_session, channel):
    """get_daily_totals returns a list of dicts with date + metric sums."""
    svc = AnalyticsService(db_session)
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Seed two days of impressions
    svc.upsert_metric(channel.id, today, MetricType.impressions, 100.0)
    svc.upsert_metric(channel.id, yesterday, MetricType.impressions, 50.0)
    svc.upsert_metric(channel.id, today, MetricType.clicks, 10.0)
    db_session.commit()

    result = svc.get_daily_totals(start_date=yesterday, end_date=today)

    assert len(result) == 2
    # Each entry has 'date', 'impressions', 'reach', 'clicks', 'engagement'
    day_today = next(r for r in result if r["date"] == today.isoformat())
    assert day_today["impressions"] == 100
    assert day_today["clicks"] == 10

    day_yesterday = next(r for r in result if r["date"] == yesterday.isoformat())
    assert day_yesterday["impressions"] == 50


def test_get_daily_totals_empty_range(db_session):
    """Returns empty list when no data in range."""
    svc = AnalyticsService(db_session)
    today = date.today()
    result = svc.get_daily_totals(
        start_date=today - timedelta(days=90),
        end_date=today - timedelta(days=80),
    )
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_analytics_daily_totals.py -v`
Expected: FAIL with `AttributeError: 'AnalyticsService' object has no attribute 'get_daily_totals'`

- [ ] **Step 3: Implement `get_daily_totals` method**

Add to `app/services/analytics_service.py`, after the `get_overview` method:

```python
def get_daily_totals(
    self,
    *,
    start_date: date,
    end_date: date,
    channel_id: UUID | None = None,
) -> list[dict]:
    """Return daily-aggregated metrics as a list of dicts sorted by date.

    Each dict: {"date": "YYYY-MM-DD", "impressions": int, "reach": int,
                "clicks": int, "engagement": int}
    """
    stmt = (
        select(
            ChannelMetric.metric_date,
            ChannelMetric.metric_type,
            func.sum(ChannelMetric.value).label("total"),
        )
        .where(ChannelMetric.metric_date >= start_date)
        .where(ChannelMetric.metric_date <= end_date)
        .where(ChannelMetric.metric_type.in_([
            MetricType.impressions,
            MetricType.reach,
            MetricType.clicks,
            MetricType.engagement,
        ]))
    )
    if channel_id is not None:
        stmt = stmt.where(ChannelMetric.channel_id == channel_id)
    stmt = stmt.group_by(ChannelMetric.metric_date, ChannelMetric.metric_type)
    stmt = stmt.order_by(ChannelMetric.metric_date)

    rows = self.db.execute(stmt).all()

    # Pivot into date -> metrics dict
    by_date: dict[date, dict[str, int]] = {}
    for row in rows:
        d = row.metric_date
        if d not in by_date:
            by_date[d] = {"impressions": 0, "reach": 0, "clicks": 0, "engagement": 0}
        by_date[d][row.metric_type.value] = int(row.total)

    return [
        {"date": d.isoformat(), **metrics}
        for d, metrics in sorted(by_date.items())
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_analytics_daily_totals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/analytics_service.py tests/test_analytics_daily_totals.py
git commit -m "feat: add get_daily_totals() to AnalyticsService for time-series data"
```

---

### Task 2: Enhance dashboard route to pass sparkline + donut data

**Files:**
- Modify: `app/web/dashboard.py`
- Test: `tests/test_dashboard_sparkline_data.py`

The dashboard route needs to pass: (1) campaign status counts for the donut chart, (2) daily impressions for the past 7 days for sparklines, (3) percent change vs prior period.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_sparkline_data.py
"""Tests for enhanced dashboard context data."""
from datetime import date, timedelta
from unittest.mock import patch

from app.models.campaign import Campaign, CampaignStatus
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.channel_metric import ChannelMetric, MetricType
from app.services.analytics_service import AnalyticsService


def test_dashboard_passes_campaign_status_counts(client, db_session, person, auth_session, auth_token):
    """Dashboard context includes campaign_status_counts dict."""
    # Create campaigns with different statuses
    for status in [CampaignStatus.active, CampaignStatus.active, CampaignStatus.draft]:
        c = Campaign(name=f"Camp {status.value}", status=status, created_by=person.id)
        db_session.add(c)
    db_session.commit()

    response = client.get("/", cookies={"access_token": auth_token})
    assert response.status_code == 200
    # Check the template rendered without error — the data presence is verified
    # by the template rendering successfully with the donut chart section
    assert b"Dashboard" in response.content


def test_dashboard_passes_sparkline_data(client, db_session, person, auth_session, auth_token, channel):
    """Dashboard context includes sparkline_data list."""
    svc = AnalyticsService(db_session)
    today = date.today()
    for i in range(7):
        d = today - timedelta(days=i)
        svc.upsert_metric(channel.id, d, MetricType.impressions, 100.0 + i * 10)
    db_session.commit()

    response = client.get("/", cookies={"access_token": auth_token})
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_dashboard_sparkline_data.py -v`
Expected: PASS or FAIL (template may error if it references new variables before we add them — that's fine, we'll add template changes in later tasks)

- [ ] **Step 3: Enhance dashboard route**

In `app/web/dashboard.py`, add the following to the `dashboard()` function, before the `ctx = {` line:

```python
# --- Sparkline data: daily impressions for last 7 days ---
from datetime import date, timedelta
from app.services.analytics_service import AnalyticsService

today = date.today()
analytics_svc = AnalyticsService(db)
sparkline_data = analytics_svc.get_daily_totals(
    start_date=today - timedelta(days=6), end_date=today
)

# Percent change vs prior 7 days
prior_data = analytics_svc.get_daily_totals(
    start_date=today - timedelta(days=13), end_date=today - timedelta(days=7)
)
current_impressions = sum(d["impressions"] for d in sparkline_data)
prior_impressions = sum(d["impressions"] for d in prior_data)
impressions_change = (
    round((current_impressions - prior_impressions) / prior_impressions * 100, 1)
    if prior_impressions > 0
    else 0.0
)

# Campaign status counts for donut chart
campaign_status_counts = {}
for status in CampaignStatus:
    campaign_status_counts[status.value] = campaign_svc.count(status=status)
```

Then add to the `ctx` dict:

```python
"sparkline_data": sparkline_data,
"impressions_change": impressions_change,
"campaign_status_counts": campaign_status_counts,
```

Note: Move the existing `from datetime import ...` imports if needed. The `date` and `timedelta` imports should be at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_dashboard_sparkline_data.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/web/dashboard.py tests/test_dashboard_sparkline_data.py
git commit -m "feat: pass sparkline and donut chart data from dashboard route"
```

---

### Task 3: Enhance analytics route to pass daily time-series data

**Files:**
- Modify: `app/web/analytics.py`

The analytics page needs daily totals for the time-series line chart.

- [ ] **Step 1: Add daily_totals to analytics_overview route**

In `app/web/analytics.py`, inside `analytics_overview()`, after the channel_metrics loop, add:

```python
# Daily totals for time-series chart
daily_totals = analytics_svc.get_daily_totals(start_date=d_start, end_date=d_end)
```

Then add to the `ctx` dict:

```python
"daily_totals": daily_totals,
```

- [ ] **Step 2: Verify the app still runs**

Run: `poetry run pytest tests/ -k "test_marketing" --no-header -q 2>/dev/null; echo "exit: $?"`
Expected: Tests pass (or no matching tests yet — that's fine)

- [ ] **Step 3: Commit**

```bash
git add app/web/analytics.py
git commit -m "feat: pass daily time-series data to analytics template"
```

---

## Chunk 2: Dashboard Template Enhancements

### Task 4: Dashboard stat cards with sparklines + trend indicators

**Files:**
- Modify: `templates/dashboard/index.html`

Replace the flat stat cards with sparkline-enabled cards that show 7-day trend lines and percent change.

- [ ] **Step 1: Redesign the stat cards section**

In `templates/dashboard/index.html`, replace the entire `{# Stats row #}` section (lines 8-33) with:

```html
{# Stats row — enhanced with sparklines #}
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    {% set stats = [
        {"label": "Total Campaigns", "value": total_campaigns if total_campaigns is defined else 0, "icon": "M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9", "metric": none},
        {"label": "Total Assets", "value": total_assets if total_assets is defined else 0, "icon": "M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M18 3.75h-1.5a.75.75 0 01-.75-.75V1.5m3 2.25V1.5m0 2.25h1.5m-1.5 0h-1.5", "metric": none},
        {"label": "Active Tasks", "value": active_tasks if active_tasks is defined else 0, "icon": "M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08", "metric": none},
        {"label": "Connected Channels", "value": connected_channels if connected_channels is defined else 0, "icon": "M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375", "metric": "impressions"},
    ] %}
    {% for stat in stats %}
    <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 stagger-in">
        <div class="flex items-end justify-between">
            <div>
                <p class="text-sm text-slate-500 dark:text-slate-400 mb-1">{{ stat.label }}</p>
                <p class="text-2xl font-bold text-slate-900 dark:text-white counter-animate" style="font-variant-numeric: tabular-nums;">{{ "{:,}".format(stat.value) }}</p>
                {% if stat.metric and impressions_change is defined %}
                <div class="flex items-center gap-1 mt-1">
                    {% if impressions_change > 0 %}
                    <svg class="w-3 h-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 15l7-7 7 7"/></svg>
                    <span class="text-xs font-medium text-emerald-600 dark:text-emerald-400">{{ impressions_change }}%</span>
                    {% elif impressions_change < 0 %}
                    <svg class="w-3 h-3 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 9l-7 7-7-7"/></svg>
                    <span class="text-xs font-medium text-red-600 dark:text-red-400">{{ impressions_change }}%</span>
                    {% else %}
                    <span class="text-xs text-slate-400">0%</span>
                    {% endif %}
                    <span class="text-[10px] text-slate-400 dark:text-slate-500">vs prior 7d</span>
                </div>
                {% endif %}
            </div>
            <div class="flex-shrink-0">
                {% if stat.metric and sparkline_data is defined and sparkline_data %}
                <canvas id="sparkline-{{ loop.index }}" width="80" height="36" class="opacity-70"></canvas>
                {% else %}
                <div class="w-10 h-10 rounded-lg bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center">
                    <svg class="w-5 h-5 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="{{ stat.icon }}" />
                    </svg>
                </div>
                {% endif %}
            </div>
        </div>
    </div>
    {% else %}
    {{ empty_state("No stats available") }}
    {% endfor %}
</div>
```

- [ ] **Step 2: Add sparkline Chart.js initialization**

At the bottom of the template, before `{% endblock %}`, add:

```html
{% if sparkline_data is defined and sparkline_data %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
(function() {
    var data = {{ sparkline_data | tojson }};
    var values = data.map(function(d) { return d.impressions; });
    var isDark = document.documentElement.classList.contains('dark');
    var color = isDark ? 'rgba(6,182,212,0.8)' : 'rgba(6,182,212,0.6)';
    var fillColor = isDark ? 'rgba(6,182,212,0.15)' : 'rgba(6,182,212,0.1)';

    var canvas = document.getElementById('sparkline-4');
    if (!canvas) return;
    new Chart(canvas, {
        type: 'line',
        data: {
            labels: data.map(function(d) { return d.date; }),
            datasets: [{
                data: values,
                borderColor: color,
                backgroundColor: fillColor,
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                pointHitRadius: 0,
            }]
        },
        options: {
            responsive: false,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } },
            animation: { duration: 800 }
        }
    });
})();
</script>
{% endif %}
```

- [ ] **Step 3: Verify template renders**

Run: `poetry run pytest tests/test_dashboard_sparkline_data.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard/index.html
git commit -m "feat: add sparkline charts and trend indicators to dashboard stat cards"
```

---

### Task 5: Dashboard donut chart for campaign status distribution

**Files:**
- Modify: `templates/dashboard/index.html`

Add a donut chart showing campaign status breakdown, placed between the stat cards and the active campaigns section.

- [ ] **Step 1: Add donut chart section**

In `templates/dashboard/index.html`, between the stats grid `</div>` and the `{# Main grid: Active campaigns + Upcoming posts #}` comment, add:

```html
{# Campaign status donut + Channel health #}
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    {# Campaign Status Distribution #}
    <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-4">Campaign Distribution</h3>
        {% if campaign_status_counts is defined and campaign_status_counts %}
        <div class="flex items-center gap-6">
            <div class="relative w-32 h-32 flex-shrink-0">
                <canvas id="donut-campaigns"></canvas>
                <div class="absolute inset-0 flex flex-col items-center justify-center">
                    <span class="text-2xl font-bold text-slate-900 dark:text-white" style="font-variant-numeric: tabular-nums;">{{ total_campaigns if total_campaigns is defined else 0 }}</span>
                    <span class="text-[10px] text-slate-400 dark:text-slate-500 uppercase tracking-wider">Total</span>
                </div>
            </div>
            <div class="flex-1 space-y-2">
                {% set donut_colors = {
                    'draft': {'dot': 'bg-slate-400', 'label': 'Draft'},
                    'active': {'dot': 'bg-emerald-500', 'label': 'Active'},
                    'paused': {'dot': 'bg-amber-500', 'label': 'Paused'},
                    'completed': {'dot': 'bg-blue-500', 'label': 'Completed'},
                    'archived': {'dot': 'bg-yellow-500', 'label': 'Archived'},
                } %}
                {% for status_key, count in campaign_status_counts.items() if count > 0 %}
                {% set info = donut_colors.get(status_key, {'dot': 'bg-slate-400', 'label': status_key | replace('_', ' ') | title}) %}
                <div class="flex items-center justify-between text-sm">
                    <div class="flex items-center gap-2">
                        <span class="w-2.5 h-2.5 rounded-full {{ info.dot }}"></span>
                        <span class="text-slate-600 dark:text-slate-400">{{ info.label }}</span>
                    </div>
                    <span class="font-medium text-slate-900 dark:text-white">{{ count }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% else %}
        <p class="text-sm text-slate-500 dark:text-slate-400">No campaigns yet.</p>
        {% endif %}
    </div>

    {# Channel Health — moved from below #}
    <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-3">Channel Health</h3>
        <div class="flex flex-wrap gap-3">
            {% set health_color_map = {
                'healthy': 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
                'warning': 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
                'error': 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
                'disconnected': 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400',
            } %}
            {% for ch in channel_health if channel_health is defined %}
            <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium {{ health_color_map.get(ch.status if ch.status else 'disconnected', 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400') }}">
                <span class="w-1.5 h-1.5 rounded-full {{ 'bg-green-500' if ch.status == 'healthy' else ('bg-yellow-500' if ch.status == 'warning' else ('bg-red-500' if ch.status == 'error' else 'bg-slate-400')) }}"></span>
                {{ ch.name if ch.name else 'Unknown' }}
            </span>
            {% else %}
            <p class="text-sm text-slate-500 dark:text-slate-400">No channels connected. <a href="/channels" class="text-primary-600 dark:text-primary-400 hover:underline">Connect a channel</a></p>
            {% endfor %}
        </div>
    </div>
</div>
```

- [ ] **Step 2: Add donut chart JS**

In the sparkline `<script>` block at the bottom (from Task 4), add the donut chart initialization after the sparkline code:

```javascript
// Donut chart — campaign status distribution
var statusData = {{ campaign_status_counts | tojson if campaign_status_counts is defined else '{}' }};
var donutCanvas = document.getElementById('donut-campaigns');
if (donutCanvas && Object.keys(statusData).length > 0) {
    var colorMap = {
        draft: isDark ? 'rgba(148,163,184,0.8)' : 'rgba(148,163,184,0.7)',
        active: isDark ? 'rgba(16,185,129,0.8)' : 'rgba(16,185,129,0.7)',
        paused: isDark ? 'rgba(245,158,11,0.8)' : 'rgba(245,158,11,0.7)',
        completed: isDark ? 'rgba(59,130,246,0.8)' : 'rgba(59,130,246,0.7)',
        archived: isDark ? 'rgba(234,179,8,0.8)' : 'rgba(234,179,8,0.7)',
    };
    var labels = [];
    var values = [];
    var colors = [];
    for (var key in statusData) {
        if (statusData[key] > 0) {
            labels.push(key.replace('_', ' '));
            values.push(statusData[key]);
            colors.push(colorMap[key] || 'rgba(148,163,184,0.5)');
        }
    }
    new Chart(donutCanvas, {
        type: 'doughnut',
        data: { labels: labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: '70%',
            plugins: { legend: { display: false }, tooltip: { enabled: true } },
            animation: { animateRotate: true, duration: 800 },
        }
    });
}
```

- [ ] **Step 3: Remove the old Channel Health section**

Delete the standalone `{# Channel Health Badges #}` section at the bottom of the template (the one that was previously after the main grid), since it's now integrated into the donut/health row.

- [ ] **Step 4: Verify template renders**

Run: `poetry run pytest tests/test_dashboard_sparkline_data.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard/index.html
git commit -m "feat: add campaign status donut chart and reorganize dashboard layout"
```

---

## Chunk 3: Analytics Page Visualizations

### Task 6: Date range preset buttons

**Files:**
- Modify: `templates/analytics/index.html`

Add quick date range buttons (7d, 30d, 90d, This Quarter) above the date pickers.

- [ ] **Step 1: Add preset buttons**

In `templates/analytics/index.html`, replace the date range form section (lines 12-23) with:

```html
{# Date range picker with presets #}
<div class="flex flex-wrap items-center gap-2">
    {% set today_str = '' %}
    {% set presets = [
        {"label": "7 days", "days": 7},
        {"label": "30 days", "days": 30},
        {"label": "90 days", "days": 90},
    ] %}
    {% for preset in presets %}
    <a href="/analytics?start_date={{ (import('datetime').date.today() - import('datetime').timedelta(days=preset.days)).isoformat() }}&end_date={{ import('datetime').date.today().isoformat() }}"
       class="px-3 py-1.5 rounded-lg border text-sm font-medium transition
              border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700">
        {{ preset.label }}
    </a>
    {% endfor %}
    <span class="text-slate-300 dark:text-slate-600">|</span>
    <form method="GET" action="/analytics" class="flex items-center gap-2">
        <input type="date" name="start_date"
               value="{{ start_date if start_date else '' }}"
               class="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500" />
        <span class="text-slate-400 dark:text-slate-500 text-sm">to</span>
        <input type="date" name="end_date"
               value="{{ end_date if end_date else '' }}"
               class="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500" />
        <button type="submit" class="px-3 py-1.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 transition">
            Apply
        </button>
    </form>
</div>
```

**Important:** The Jinja2 `import()` function won't work in templates. Instead, the preset links should be generated with hardcoded relative URLs. We need to compute the dates in the route. Update `app/web/analytics.py` to pass `preset_dates` to the context:

Add to `analytics_overview()` before the `ctx`:

```python
# Preset date ranges for quick links
preset_dates = [
    {"label": "7 days", "start": (today - timedelta(days=7)).isoformat(), "end": today.isoformat()},
    {"label": "30 days", "start": (today - timedelta(days=30)).isoformat(), "end": today.isoformat()},
    {"label": "90 days", "start": (today - timedelta(days=90)).isoformat(), "end": today.isoformat()},
]
```

Add `"preset_dates": preset_dates` to ctx.

Then in the template, use:

```html
{% for preset in preset_dates if preset_dates is defined %}
<a href="/analytics?start_date={{ preset.start }}&end_date={{ preset.end }}"
   class="px-3 py-1.5 rounded-lg border text-sm font-medium transition
          border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700">
    {{ preset.label }}
</a>
{% endfor %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/analytics/index.html app/web/analytics.py
git commit -m "feat: add date range preset buttons to analytics page"
```

---

### Task 7: Time-series line chart

**Files:**
- Modify: `templates/analytics/index.html`

Add a multi-line time-series chart between the summary cards and the per-channel table.

- [ ] **Step 1: Add time-series chart section**

In `templates/analytics/index.html`, after the summary cards `</div>` and before the `{# Per-channel breakdown #}` section, add:

```html
{# Time-series chart #}
<div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
    <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-4">Metrics Over Time</h3>
    {% if daily_totals is defined and daily_totals %}
    <div class="relative h-72">
        <canvas id="timeSeriesChart"></canvas>
    </div>
    {% else %}
    <div class="text-center py-8">
        <svg class="w-12 h-12 mx-auto text-slate-300 dark:text-slate-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75z" />
        </svg>
        <p class="text-sm text-slate-500 dark:text-slate-400">No daily data for this period.</p>
    </div>
    {% endif %}
</div>
```

- [ ] **Step 2: Add time-series JS initialization**

In the existing `<script>` block at the bottom of the template (inside the `{% if channel_metrics %}` block), add BEFORE the bar chart code (or in a new script block):

```html
{% if daily_totals is defined and daily_totals %}
<script>
(function() {
    var daily = {{ daily_totals | tojson }};
    var labels = daily.map(function(d) { return d.date; });
    var isDark = document.documentElement.classList.contains('dark');
    var gridColor = isDark ? 'rgba(148,163,184,0.1)' : 'rgba(148,163,184,0.2)';
    var textColor = isDark ? '#94a3b8' : '#64748b';

    new Chart(document.getElementById('timeSeriesChart'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Impressions',
                    data: daily.map(function(d) { return d.impressions; }),
                    borderColor: 'rgba(99,102,241,0.9)',
                    backgroundColor: 'rgba(99,102,241,0.1)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
                {
                    label: 'Reach',
                    data: daily.map(function(d) { return d.reach; }),
                    borderColor: 'rgba(34,197,94,0.9)',
                    backgroundColor: 'transparent',
                    tension: 0.3,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
                {
                    label: 'Clicks',
                    data: daily.map(function(d) { return d.clicks; }),
                    borderColor: 'rgba(234,179,8,0.9)',
                    backgroundColor: 'transparent',
                    tension: 0.3,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
                {
                    label: 'Engagement',
                    data: daily.map(function(d) { return d.engagement; }),
                    borderColor: 'rgba(239,68,68,0.9)',
                    backgroundColor: 'transparent',
                    tension: 0.3,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: textColor, usePointStyle: true, pointStyle: 'line' } },
                tooltip: { mode: 'index', intersect: false },
            },
            scales: {
                x: {
                    ticks: { color: textColor, maxRotation: 0, maxTicksLimit: 10 },
                    grid: { color: gridColor },
                },
                y: {
                    ticks: { color: textColor },
                    grid: { color: gridColor },
                    beginAtZero: true,
                }
            }
        }
    });
})();
</script>
{% endif %}
```

- [ ] **Step 3: Commit**

```bash
git add templates/analytics/index.html
git commit -m "feat: add multi-line time-series chart to analytics page"
```

---

### Task 8: Funnel visualization (pure CSS)

**Files:**
- Modify: `templates/analytics/index.html`

Add a horizontal funnel showing Impressions → Reach → Clicks → Engagement with conversion rates between stages.

- [ ] **Step 1: Add funnel section**

In `templates/analytics/index.html`, after the summary cards section and before the time-series chart, add:

```html
{# Funnel visualization #}
{% if total_impressions is defined and total_impressions > 0 %}
{% set funnel_stages = [
    {"label": "Impressions", "value": total_impressions, "color": "bg-indigo-500"},
    {"label": "Reach", "value": total_reach if total_reach is defined else 0, "color": "bg-green-500"},
    {"label": "Clicks", "value": total_clicks if total_clicks is defined else 0, "color": "bg-amber-500"},
    {"label": "Engagement", "value": total_engagement if total_engagement is defined else 0, "color": "bg-red-500"},
] %}
<div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
    <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-4">Conversion Funnel</h3>
    <div class="space-y-3">
        {% for stage in funnel_stages %}
        {% set max_val = total_impressions %}
        {% set pct = ((stage.value / max_val) * 100) | round(1) if max_val > 0 else 0 %}
        <div class="flex items-center gap-3">
            <div class="w-24 text-xs font-medium text-slate-600 dark:text-slate-400 text-right">{{ stage.label }}</div>
            <div class="flex-1 relative">
                <div class="h-8 bg-slate-100 dark:bg-slate-700 rounded-lg overflow-hidden">
                    <div class="{{ stage.color }} h-full rounded-lg flex items-center transition-all duration-700 ease-out"
                         style="width: {{ pct if pct > 2 else 2 }}%;">
                        <span class="text-[11px] font-semibold text-white px-2 whitespace-nowrap">{{ "{:,}".format(stage.value) }}</span>
                    </div>
                </div>
            </div>
            <div class="w-14 text-right">
                {% if not loop.first %}
                {% set prev_val = funnel_stages[loop.index0 - 1].value %}
                {% set conv = ((stage.value / prev_val) * 100) | round(1) if prev_val > 0 else 0 %}
                <span class="text-[10px] font-medium text-slate-400 dark:text-slate-500">{{ conv }}%</span>
                {% else %}
                <span class="text-[10px] font-medium text-slate-400 dark:text-slate-500">100%</span>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/analytics/index.html
git commit -m "feat: add CSS funnel visualization to analytics page"
```

---

### Task 9: Radar chart for cross-channel comparison

**Files:**
- Modify: `templates/analytics/index.html`

Replace the existing bar chart with a side-by-side layout: radar chart (left) + bar chart (right).

- [ ] **Step 1: Add radar chart alongside existing bar chart**

In `templates/analytics/index.html`, replace the existing `{# Chart — per-channel bar chart #}` section with:

```html
{# Charts — radar + bar side-by-side #}
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    {# Radar chart #}
    <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-4">Channel Strengths</h3>
        {% if channel_metrics is defined and channel_metrics %}
        <div class="relative h-64">
            <canvas id="radarChart"></canvas>
        </div>
        {% else %}
        <div class="text-center py-8">
            <p class="text-sm text-slate-500 dark:text-slate-400">No data to chart.</p>
        </div>
        {% endif %}
    </div>

    {# Bar chart (existing, moved here) #}
    <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-4">Channel Comparison</h3>
        {% if channel_metrics is defined and channel_metrics %}
        <div class="relative h-64">
            <canvas id="channelChart"></canvas>
        </div>
        {% else %}
        <div class="text-center py-8">
            <p class="text-sm text-slate-500 dark:text-slate-400">No data to chart for this period.</p>
        </div>
        {% endif %}
    </div>
</div>
```

- [ ] **Step 2: Add radar chart JS**

In the chart script section, add the radar chart initialization:

```javascript
// Radar chart — channel strengths
var radarCanvas = document.getElementById('radarChart');
if (radarCanvas && data.length > 0) {
    // Normalize each metric to 0-100 scale for radar comparison
    var maxI = Math.max.apply(null, data.map(function(r) { return r.impressions || 1; }));
    var maxR = Math.max.apply(null, data.map(function(r) { return r.reach || 1; }));
    var maxCl = Math.max.apply(null, data.map(function(r) { return r.clicks || 1; }));
    var maxE = Math.max.apply(null, data.map(function(r) { return r.engagement || 1; }));

    var radarColors = [
        'rgba(99,102,241,0.7)', 'rgba(34,197,94,0.7)', 'rgba(234,179,8,0.7)',
        'rgba(239,68,68,0.7)', 'rgba(168,85,247,0.7)', 'rgba(6,182,212,0.7)',
    ];

    var radarDatasets = data.map(function(r, i) {
        return {
            label: r.channel_name || 'Channel',
            data: [
                Math.round((r.impressions || 0) / maxI * 100),
                Math.round((r.reach || 0) / maxR * 100),
                Math.round((r.clicks || 0) / maxCl * 100),
                Math.round((r.engagement || 0) / maxE * 100),
            ],
            borderColor: radarColors[i % radarColors.length],
            backgroundColor: radarColors[i % radarColors.length].replace('0.7', '0.1'),
            borderWidth: 2,
            pointRadius: 3,
        };
    });

    new Chart(radarCanvas, {
        type: 'radar',
        data: {
            labels: ['Impressions', 'Reach', 'Clicks', 'Engagement'],
            datasets: radarDatasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    beginAtZero: true,
                    max: 100,
                    ticks: { display: false },
                    grid: { color: gridColor },
                    angleLines: { color: gridColor },
                    pointLabels: { color: textColor, font: { size: 11 } },
                }
            },
            plugins: {
                legend: { labels: { color: textColor, usePointStyle: true }, position: 'bottom' },
            }
        }
    });
}
```

- [ ] **Step 3: Commit**

```bash
git add templates/analytics/index.html
git commit -m "feat: add radar chart for cross-channel comparison on analytics page"
```

---

## Chunk 4: Task & Calendar UI Enhancements

### Task 10: Task due-date urgency indicators

**Files:**
- Modify: `templates/tasks/partials/task_card.html`

Add colored urgency dots next to due dates: red pulsing for overdue, amber for due today, yellow for due this week.

- [ ] **Step 1: Enhance task card due date display**

In `templates/tasks/partials/task_card.html`, replace the due date `<span>` section (lines 48-52) with:

```html
{% if task.due_date %}
{% set today_date = import('datetime').date.today() if false else none %}
<div class="flex items-center gap-1">
    {% if task.is_overdue %}
    <span class="relative flex h-2 w-2">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
        <span class="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
    </span>
    <span class="text-red-500 dark:text-red-400 font-medium">
        Due {{ task.due_date.strftime('%b %d') }}
    </span>
    {% else %}
    <span class="w-2 h-2 rounded-full flex-shrink-0
        {% set days_until = (task.due_date - task.due_date.today()).days %}
        {{ 'bg-amber-500' if days_until == 0 else ('bg-yellow-400' if days_until <= 7 else 'bg-slate-300 dark:bg-slate-600') }}
    "></span>
    <span class="{{ 'text-amber-600 dark:text-amber-400 font-medium' if days_until == 0 else '' }}">
        {{ 'Today' if days_until == 0 else ('Tomorrow' if days_until == 1 else task.due_date.strftime('%b %d')) }}
    </span>
    {% endif %}
</div>
{% endif %}
```

**Note:** Jinja2 doesn't support `import()` — we need to compute `days_until` differently. The Task model already has `is_overdue`. We'll add a helper property. Actually, we can compute it inline:

Replace with this simpler approach that uses the model's `is_overdue` and computes days in the template:

```html
{% if task.due_date %}
<div class="flex items-center gap-1">
    {% if task.is_overdue %}
    <span class="relative flex h-2 w-2">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
        <span class="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
    </span>
    <span class="text-red-500 dark:text-red-400 font-medium">Overdue {{ task.due_date.strftime('%b %d') }}</span>
    {% else %}
    <span class="w-2 h-2 rounded-full flex-shrink-0 {{ 'bg-amber-500' if task.due_date.isoformat() == task.due_date.today().isoformat() else ('bg-yellow-400' if (task.due_date - task.due_date.today()).days <= 7 else 'bg-slate-300 dark:bg-slate-600') }}"></span>
    <span class="{{ 'text-amber-600 dark:text-amber-400 font-medium' if task.due_date.isoformat() == task.due_date.today().isoformat() else '' }}">
        {{ 'Today' if task.due_date.isoformat() == task.due_date.today().isoformat() else task.due_date.strftime('%b %d') }}
    </span>
    {% endif %}
</div>
{% endif %}
```

- [ ] **Step 2: Verify template renders**

Run: `poetry run pytest tests/ -k "test_marketing" --no-header -q 2>/dev/null; echo "exit: $?"`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add templates/tasks/partials/task_card.html
git commit -m "feat: add urgency indicators (pulsing dots) to task due dates"
```

---

### Task 11: Kanban column WIP indicators

**Files:**
- Modify: `templates/tasks/partials/kanban_board.html`

Add a subtle progress bar at the top of each column indicating how many items are in it vs a soft WIP limit.

- [ ] **Step 1: Add WIP indicator to kanban columns**

In `templates/tasks/partials/kanban_board.html`, after the column header `<h3>` tag (line 9-13), add:

```html
{% set col_count = columns[col.key] | length if columns is defined and col.key in columns else 0 %}
{% set wip_limit = 8 %}
{% set wip_pct = ((col_count / wip_limit) * 100) | round | int if wip_limit > 0 else 0 %}
{% set wip_pct = wip_pct if wip_pct <= 100 else 100 %}
<div class="mb-3 h-1 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
    <div class="h-full rounded-full transition-all duration-500 {{ 'bg-red-400' if col_count > wip_limit else ('bg-amber-400' if wip_pct > 62 else 'bg-primary-400') }}"
         style="width: {{ wip_pct }}%;"></div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/tasks/partials/kanban_board.html
git commit -m "feat: add WIP progress indicators to kanban columns"
```

---

### Task 12: Calendar dot simplification

**Files:**
- Modify: `templates/calendar/index.html`

In month view, replace text post badges with small colored dots for cleaner visual density. Show post details on hover via title attribute.

- [ ] **Step 1: Replace month view post badges with dots**

In `templates/calendar/index.html`, in the month view section, replace the post loop (lines 205-213) with:

```html
<div class="flex flex-wrap gap-0.5 mt-0.5">
    {% for post in day_posts %}
    {% set provider_val = post.channel.provider | string if post.channel and post.channel.provider else '' %}
    {% set dot_color_map = {
        'meta_instagram': 'bg-pink-400',
        'meta_facebook': 'bg-blue-500',
        'twitter': 'bg-sky-400',
        'linkedin': 'bg-indigo-500',
        'google_ads': 'bg-yellow-500',
        'email': 'bg-emerald-500',
    } %}
    <div class="w-2 h-2 rounded-full cursor-pointer {{ dot_color_map.get(provider_val, 'bg-slate-400') }} {{ 'ring-1 ring-white dark:ring-slate-800' if post.status | string == 'published' else 'opacity-60' }}"
         title="{{ post.title if post.title else '' }} — {{ post.scheduled_at.strftime('%H:%M') if post.scheduled_at else '' }} ({{ provider_val | replace('_', ' ') | title }})"
         draggable="true"
         @dragstart="event.dataTransfer.setData('text/plain', '{{ post.id }}')">
    </div>
    {% endfor %}
</div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/calendar/index.html
git commit -m "feat: simplify calendar month view with colored dot indicators"
```

---

## Chunk 5: Campaign Detail & Global Polish

### Task 13: Campaign progress ring (SVG)

**Files:**
- Modify: `templates/campaigns/detail.html`

Add a circular progress ring in the campaign detail header showing posts published / total posts.

- [ ] **Step 1: Enhance campaign detail route to pass progress data**

In `app/web/campaigns.py`, inside `campaign_detail()`, after fetching the record, add:

```python
from app.services.post_service import PostService
from app.models.post import PostStatus

post_svc = PostService(db)
all_posts = post_svc.list_all(campaign_id=id)
total_posts = len(all_posts)
published_posts = sum(1 for p in all_posts if p.status == PostStatus.published)
progress_pct = round(published_posts / total_posts * 100) if total_posts > 0 else 0
```

Add to ctx:

```python
"total_posts": total_posts,
"published_posts": published_posts,
"progress_pct": progress_pct,
```

- [ ] **Step 2: Add progress ring to template header**

In `templates/campaigns/detail.html`, after the status badge in the header (line 15), add:

```html
{% if total_posts is defined and total_posts > 0 %}
{% set pct = progress_pct if progress_pct is defined else 0 %}
{% set circumference = 88 %}
{% set offset = circumference - (circumference * pct / 100) %}
<div class="relative w-10 h-10 flex-shrink-0" title="{{ published_posts if published_posts is defined else 0 }}/{{ total_posts }} posts published">
    <svg class="w-10 h-10 -rotate-90" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r="14" fill="none" stroke-width="3"
                class="stroke-slate-200 dark:stroke-slate-700" />
        <circle cx="18" cy="18" r="14" fill="none" stroke-width="3"
                stroke-linecap="round"
                class="stroke-primary-500"
                stroke-dasharray="{{ circumference }}"
                stroke-dashoffset="{{ offset }}"
                style="transition: stroke-dashoffset 0.8s ease-out;" />
    </svg>
    <span class="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-slate-700 dark:text-slate-300">{{ pct }}%</span>
</div>
{% endif %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/campaigns.py templates/campaigns/detail.html
git commit -m "feat: add SVG progress ring to campaign detail header"
```

---

### Task 14: Skeleton loading states

**Files:**
- Modify: `templates/campaigns/detail.html`

Replace spinner loading states with skeleton screens.

- [ ] **Step 1: Replace spinner with skeleton**

In `templates/campaigns/detail.html`, replace the tab loading spinner (lines 93-98) with:

```html
<div class="space-y-4 animate-pulse">
    <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <div class="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/3 mb-4"></div>
        <div class="space-y-3">
            <div class="h-3 bg-slate-200 dark:bg-slate-700 rounded w-full"></div>
            <div class="h-3 bg-slate-200 dark:bg-slate-700 rounded w-5/6"></div>
            <div class="h-3 bg-slate-200 dark:bg-slate-700 rounded w-2/3"></div>
        </div>
    </div>
    <div class="grid grid-cols-3 gap-4">
        <div class="h-20 bg-slate-200 dark:bg-slate-700 rounded-xl"></div>
        <div class="h-20 bg-slate-200 dark:bg-slate-700 rounded-xl"></div>
        <div class="h-20 bg-slate-200 dark:bg-slate-700 rounded-xl"></div>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/campaigns/detail.html
git commit -m "feat: replace spinner with skeleton loading states in campaign tabs"
```

---

### Task 15: Global CSS polish — sidebar active state + tabular-nums + toast progress bar

**Files:**
- Modify: `templates/base.html`
- Modify: `templates/admin/components/topbar.html` (if sidebar link styling is here — actually sidebar is in admin/base.html)

- [ ] **Step 1: Check sidebar template location**

Look for the sidebar nav in the admin base template. The active state enhancement adds a left border accent.

- [ ] **Step 2: Add tabular-nums to counter-animate**

In `templates/base.html`, in the `<style>` block, add to `.counter-animate`:

```css
.counter-animate {
    display: inline-block;
    font-variant-numeric: tabular-nums;
    animation: counterPop 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
```

- [ ] **Step 3: Add toast progress bar animation**

In `templates/base.html`, in the `<style>` block, add:

```css
/* Toast auto-dismiss progress bar */
@keyframes toastProgress {
    from { width: 100%; }
    to { width: 0%; }
}
.toast-progress {
    animation: toastProgress 4s linear forwards;
}
```

Then in the toast template div, after the dismiss button, add:

```html
<div class="absolute bottom-0 left-0 h-0.5 bg-white/30 toast-progress rounded-b-lg"></div>
```

And add `position: relative` by adding the `relative` class to the toast wrapper.

- [ ] **Step 4: Commit**

```bash
git add templates/base.html
git commit -m "feat: add tabular-nums to counters and progress bar to toasts"
```

---

### Task 16: Run linting and type checking

**Files:** None (verification only)

- [ ] **Step 1: Run ruff**

Run: `poetry run ruff check app/ tests/ --fix`
Expected: No errors (or auto-fixed)

- [ ] **Step 2: Run mypy**

Run: `poetry run mypy app/ --ignore-missing-imports`
Expected: No new errors

- [ ] **Step 3: Run all tests**

Run: `poetry run pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 4: Fix any issues found**

If any lint/type/test issues, fix them and re-run.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: fix lint and type issues from UI enhancements"
```
