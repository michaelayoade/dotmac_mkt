"""Domain-specific notification factory methods for marketing events."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.notification import NotificationCreate
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)


class MarketingNotificationService:
    """Creates notifications for marketing-domain events.

    Wraps the generic NotificationService with domain-specific factory methods.
    Each method creates one notification per recipient, using flush() via the
    underlying service. Callers should commit.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._svc = NotificationService(db)

    def notify_post_published(
        self,
        *,
        post_id: UUID,
        post_title: str,
        channel_name: str,
        recipient_ids: list[UUID],
    ) -> None:
        """Create a notification for each recipient when a post is published."""
        for rid in recipient_ids:
            self._svc.create(
                NotificationCreate(
                    recipient_id=rid,
                    title=f"Post published: {post_title}",
                    message=f'"{post_title}" was published to {channel_name}.',
                    type="success",
                    entity_type="post",
                    entity_id=str(post_id),
                    action_url="/campaigns",
                )
            )
        logger.info(
            "Notified %d recipients about published Post %s",
            len(recipient_ids),
            post_id,
        )

    def notify_channel_disconnected(
        self,
        *,
        channel_id: UUID,
        channel_name: str,
        recipient_ids: list[UUID],
    ) -> None:
        """Notify admins when a channel enters disconnected/error state."""
        for rid in recipient_ids:
            self._svc.create(
                NotificationCreate(
                    recipient_id=rid,
                    title=f"Channel disconnected: {channel_name}",
                    message=f"{channel_name} lost its connection. Reconnect to resume syncing.",
                    type="warning",
                    entity_type="channel",
                    entity_id=str(channel_id),
                    action_url="/channels",
                )
            )
        logger.info(
            "Notified %d recipients about disconnected Channel %s",
            len(recipient_ids),
            channel_id,
        )

    def notify_task_assigned(
        self,
        *,
        task_id: UUID,
        task_title: str,
        campaign_name: str,
        assignee_id: UUID,
        assigner_id: UUID | None = None,
    ) -> None:
        """Notify a person when they are assigned a task."""
        self._svc.create(
            NotificationCreate(
                recipient_id=assignee_id,
                sender_id=assigner_id,
                title=f"Task assigned: {task_title}",
                message=f'You were assigned "{task_title}" in campaign {campaign_name}.',
                type="info",
                entity_type="task",
                entity_id=str(task_id),
                action_url="/tasks",
            )
        )
        logger.info("Notified %s about assigned Task %s", assignee_id, task_id)

    def notify_campaign_completed(
        self,
        *,
        campaign_id: UUID,
        campaign_name: str,
        member_ids: list[UUID],
    ) -> None:
        """Notify all campaign members when a campaign is marked completed."""
        for mid in member_ids:
            self._svc.create(
                NotificationCreate(
                    recipient_id=mid,
                    title=f"Campaign completed: {campaign_name}",
                    message=f'Campaign "{campaign_name}" has been marked as completed.',
                    type="success",
                    entity_type="campaign",
                    entity_id=str(campaign_id),
                    action_url=f"/campaigns/{campaign_id}",
                )
            )
        logger.info(
            "Notified %d members about completed Campaign %s",
            len(member_ids),
            campaign_id,
        )
