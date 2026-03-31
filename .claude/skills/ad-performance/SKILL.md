---
name: ad-performance
description: Query the PostgreSQL database to analyze ad performance metrics across all channels (Meta, Google Ads, LinkedIn, Twitter) and provide actionable insights with derived metrics like CTR, CPC, and CPA
allowed-tools: Bash, Read
argument-hint: [date-range or channel-name]
---

# Ad Performance Analysis

Analyze ad performance data from the dotmac_mkt database and provide actionable insights.
Use `$ARGUMENTS` if the user passes a date range (e.g., "30d", "90d") or channel name to filter by.

## Instructions

When the user invokes `/ad-performance`, connect to the PostgreSQL database and run a comprehensive ad performance analysis. Use the Bash tool to execute Python scripts with `poetry run python -c "..."` that query the database directly via SQLAlchemy.

### Database Connection

```python
from sqlalchemy import create_engine, text
engine = create_engine("postgresql+psycopg://postgres:postgres@localhost:5441/dotmac_mkt")
```

Note: The database runs inside Docker and is exposed on `localhost:5441`. Table names are **plural** (channels, channel_metrics, campaigns, posts).

### Step 1: Gather Data

Run queries to collect:

1. **Channel overview** — All connected channels with provider, status, last sync time
2. **Metric totals (last 30 days)** — Per-channel totals for: impressions, reach, clicks, engagement, spend, conversions
3. **Daily trends (last 30 days)** — Daily totals for impressions, clicks, spend, conversions per channel
4. **Top performing posts** — Posts ranked by impressions and engagement
5. **Campaign rollups** — Per-campaign totals for key metrics
6. **Week-over-week comparison** — This week vs last week for key metrics

Use these query patterns:

```python
# Channel overview
SELECT c.id, c.name, c.provider, c.status, c.last_synced_at,
       COUNT(DISTINCT m.metric_date) as days_with_data
FROM channels c
LEFT JOIN channel_metrics m ON m.channel_id = c.id
GROUP BY c.id, c.name, c.provider, c.status, c.last_synced_at

# Per-channel metric totals (last 30 days)
SELECT c.name, c.provider, m.metric_type, SUM(m.value) as total
FROM channel_metrics m
JOIN channels c ON m.channel_id = c.id
WHERE m.metric_date >= CURRENT_DATE - INTERVAL '30 days'
  AND m.post_id IS NULL
GROUP BY c.name, c.provider, m.metric_type
ORDER BY c.name, m.metric_type

# Daily trends
SELECT m.metric_date, c.provider, m.metric_type, SUM(m.value) as total
FROM channel_metrics m
JOIN channels c ON m.channel_id = c.id
WHERE m.metric_date >= CURRENT_DATE - INTERVAL '30 days'
  AND m.metric_type IN ('impressions', 'clicks', 'spend', 'conversions')
GROUP BY m.metric_date, c.provider, m.metric_type
ORDER BY m.metric_date

# Top posts by impressions
SELECT p.title, c.name as channel_name, camp.name as campaign_name,
       SUM(m.value) as impressions
FROM channel_metrics m
JOIN posts p ON m.post_id = p.id
JOIN channels c ON p.channel_id = c.id
LEFT JOIN campaigns camp ON p.campaign_id = camp.id
WHERE m.metric_type = 'impressions'
  AND m.metric_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY p.id, p.title, c.name, camp.name
ORDER BY impressions DESC
LIMIT 10

# Campaign performance
SELECT camp.name, camp.status, m.metric_type, SUM(m.value) as total
FROM channel_metrics m
JOIN posts p ON m.post_id = p.id
JOIN campaigns camp ON p.campaign_id = camp.id
WHERE m.metric_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY camp.id, camp.name, camp.status, m.metric_type
ORDER BY camp.name, m.metric_type

# Week-over-week
SELECT
  CASE WHEN m.metric_date >= CURRENT_DATE - INTERVAL '7 days' THEN 'this_week'
       ELSE 'last_week' END as period,
  m.metric_type, SUM(m.value) as total
FROM channel_metrics m
WHERE m.metric_date >= CURRENT_DATE - INTERVAL '14 days'
  AND m.metric_type IN ('impressions', 'clicks', 'spend', 'conversions', 'engagement')
GROUP BY period, m.metric_type
ORDER BY m.metric_type, period
```

### Step 2: Compute Derived Metrics

Calculate from the raw data:
- **CTR** (Click-Through Rate): clicks / impressions * 100
- **CPC** (Cost Per Click): spend / clicks
- **CPM** (Cost Per Mille): spend / impressions * 1000
- **Conversion Rate**: conversions / clicks * 100
- **CPA** (Cost Per Acquisition): spend / conversions
- **ROAS** hint: if revenue data exists

### Step 3: Present Analysis

Format the output as a clear report with these sections:

#### Overview
- Date range analyzed
- Number of active channels
- Total spend, impressions, clicks, conversions

#### Per-Channel Performance Table
| Channel | Provider | Impressions | Clicks | CTR | Spend | Conv | CPA |
Use markdown tables for readability.

#### Trends & Momentum
- Week-over-week changes (with directional arrows)
- Identify channels trending up or down
- Flag any anomalies (sudden drops/spikes)

#### Top Performers
- Best performing posts/campaigns
- Highest CTR channels
- Best CPA channels

#### Recommendations
Provide specific, actionable advice:
- Budget reallocation suggestions (shift spend toward better CPA channels)
- Underperforming channels that need attention
- Opportunities to scale what's working
- Content type insights if post data is available

### Step 4: Handle Edge Cases
- If no metrics exist, inform the user and suggest connecting channels or running a sync
- If only some channels have data, analyze what's available and note gaps
- If spend data is missing, skip cost-based metrics and note it

### Notes
- Always use `text()` wrapper for raw SQL queries
- Close the engine connection after queries
- Format numbers with commas and 2 decimal places for currency
- Use percentage formatting for rates
- If the user provides arguments like a date range or specific channel, filter accordingly
