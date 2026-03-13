from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.channel_metric import MetricType


class ChannelMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    channel_id: UUID
    post_id: UUID | None
    metric_date: date
    metric_type: MetricType
    value: float
    created_at: datetime
