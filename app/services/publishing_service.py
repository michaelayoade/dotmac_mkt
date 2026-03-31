"""Publishes posts to external channels via adapters."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.adapters.registry import get_adapter
from app.models.asset import Asset, AssetType
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery, PostDeliveryStatus
from app.services.credential_service import CredentialService

logger = logging.getLogger(__name__)

PUBLISHABLE_PROVIDERS = {
    ChannelProvider.meta_instagram,
    ChannelProvider.meta_facebook,
    ChannelProvider.twitter,
    ChannelProvider.linkedin,
}

INSTAGRAM_UNSUPPORTED_MIME_TYPES = {
    "image/webp",
}


def _build_adapter_kwargs(creds: dict) -> dict[str, str]:
    """Extract adapter constructor kwargs from decrypted credentials."""
    kwargs: dict[str, str] = {"access_token": creds.get("access_token", "")}
    for key in (
        "account_id",
        "organization_id",
        "customer_id",
        "property_id",
        "developer_token",
    ):
        if key in creds:
            kwargs[key] = creds[key]
    return kwargs


def _adapter_for_provider_capabilities(channel: Channel):
    kwargs = {"access_token": ""}
    provider = channel.provider
    if provider.name.startswith("meta_") or provider.name == "twitter":
        kwargs["account_id"] = ""
    elif provider.name == "linkedin":
        kwargs["organization_id"] = ""
    elif provider.name == "google_ads":
        kwargs["customer_id"] = ""
        kwargs["developer_token"] = ""
    elif provider.name == "google_analytics":
        kwargs["property_id"] = ""
    return get_adapter(provider, **kwargs)


class PublishingService:
    """Publishes posts to external channels via adapters."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _delivery_content(self, post: Post, delivery: PostDelivery) -> str:
        return (delivery.content_override or post.content or "").strip()

    def _get_channel_adapter(self, channel: Channel):
        cred_svc = CredentialService()
        if not channel.credentials_encrypted:
            raise ValueError(f"Channel {channel.name} has no credentials")
        creds = cred_svc.decrypt(channel.credentials_encrypted)
        if not creds:
            raise ValueError(f"Failed to decrypt credentials for {channel.name}")

        adapter_kwargs = _build_adapter_kwargs(creds)
        return get_adapter(channel.provider, **adapter_kwargs)

    def _single_published_target(
        self, post: Post
    ) -> tuple[PostDelivery | None, Channel, str]:
        deliveries = list(post.deliveries)
        if len(deliveries) > 1:
            raise ValueError(
                "Cross-platform published posts cannot be edited in one action yet."
            )
        if len(deliveries) == 1:
            delivery = deliveries[0]
            channel = delivery.channel or self.db.get(Channel, delivery.channel_id)
            if channel is None:
                raise ValueError(f"Channel {delivery.channel_id} not found")
            external_post_id = delivery.external_post_id or post.external_post_id
            if not external_post_id:
                raise ValueError(f"Post {post.id} is missing an external post ID")
            return delivery, channel, external_post_id

        if not post.channel_id:
            raise ValueError(f"Post {post.id} has no channel assigned")
        channel = self.db.get(Channel, post.channel_id)
        if channel is None:
            raise ValueError(f"Channel {post.channel_id} not found")
        if not post.external_post_id:
            raise ValueError(f"Post {post.id} is missing an external post ID")
        return None, channel, post.external_post_id

    @staticmethod
    def _asset_publish_url(asset: Asset, provider: ChannelProvider) -> str | None:
        if provider == ChannelProvider.meta_instagram:
            return asset.preview_url or asset.drive_url
        return asset.drive_url or asset.preview_url

    @staticmethod
    def _instagram_asset_issue(post: Post) -> str | None:
        if not post.assets:
            return "Instagram publishing requires at least one asset."

        for asset in post.assets:
            if asset.asset_type not in {AssetType.image, AssetType.video}:
                return "Instagram publishing requires an image or video asset."
            mime_type = (asset.mime_type or "").lower()
            if mime_type in INSTAGRAM_UNSUPPORTED_MIME_TYPES:
                return (
                    f"Instagram does not support {mime_type} assets. "
                    "Upload a JPG or PNG instead."
                )

        if not any(
            PublishingService._asset_publish_url(asset, ChannelProvider.meta_instagram)
            for asset in post.assets
        ):
            return "Instagram publishing requires at least one asset with a media URL."

        return None

    @staticmethod
    def _media_urls_for_post(
        post: Post, provider: ChannelProvider | None = None
    ) -> list[str] | None:
        effective_provider = provider or (
            post.channel.provider if post.channel is not None else None
        )
        if effective_provider is None:
            return None
        urls = [
            url
            for asset in post.assets
            if asset.asset_type in {AssetType.image, AssetType.video}
            if (url := PublishingService._asset_publish_url(asset, effective_provider))
        ]
        return urls or None

    @staticmethod
    def supports_remote_update(channel: Channel | None) -> bool:
        if channel is None:
            return False
        return bool(
            getattr(
                _adapter_for_provider_capabilities(channel),
                "supports_remote_update",
                False,
            )
        )

    @staticmethod
    def supports_remote_delete(channel: Channel | None) -> bool:
        if channel is None:
            return False
        return bool(
            getattr(
                _adapter_for_provider_capabilities(channel),
                "supports_remote_delete",
                False,
            )
        )

    def publishability_issues(self, post: Post) -> dict[str, str]:
        targets = list(post.deliveries)
        if not targets and post.channel_id:
            channel = self.db.get(Channel, post.channel_id)
            if channel is not None:
                targets = [
                    PostDelivery(
                        post=post,
                        channel=channel,
                        channel_id=channel.id,
                        provider=channel.provider,
                        content_override=post.content,
                    )
                ]
        if not targets:
            return {"post": "Assign at least one channel before publishing."}

        issues: dict[str, str] = {}
        for delivery in targets:
            channel = delivery.channel or self.db.get(Channel, delivery.channel_id)
            if channel is None:
                issues[str(delivery.id)] = "Channel is missing."
                continue
            if channel.status != ChannelStatus.connected:
                issues[str(delivery.id)] = f"{channel.name} is not connected."
                continue
            if channel.provider not in PUBLISHABLE_PROVIDERS:
                issues[str(delivery.id)] = f"{channel.name} supports analytics only."
                continue
            if not self._delivery_content(post, delivery):
                issues[str(delivery.id)] = f"{channel.name} requires content."
                continue
            if channel.provider == ChannelProvider.meta_instagram:
                asset_issue = self._instagram_asset_issue(post)
                if asset_issue:
                    issues[str(delivery.id)] = asset_issue
        return issues

    def publish(self, post_id: UUID) -> Post:
        """Validate, publish via adapter, update post status.

        Raises ValueError if post not found, not ready, or channel not connected.
        Raises RuntimeError if all delivery publish attempts fail.
        """
        post = self.db.get(Post, post_id)
        if post is None:
            raise ValueError(f"Post {post_id} not found")

        if post.status == PostStatus.published:
            raise ValueError(f"Post {post_id} is already published")
        issues = self.publishability_issues(post)
        if issues:
            raise ValueError("; ".join(issues.values()))

        deliveries = list(post.deliveries)
        if not deliveries and post.channel_id:
            channel = self.db.get(Channel, post.channel_id)
            if channel is not None:
                fallback_delivery = PostDelivery(
                    post=post,
                    channel=channel,
                    post_id=post.id,
                    channel_id=channel.id,
                    provider=channel.provider,
                    content_override=post.content,
                    status=PostDeliveryStatus.draft,
                )
                self.db.add(fallback_delivery)
                self.db.flush()
                deliveries = [fallback_delivery]

        published_at = datetime.now(UTC)
        primary_external_post_id: str | None = None
        published_count = 0
        failed_messages: list[str] = []
        for delivery in deliveries:
            channel = delivery.channel or self.db.get(Channel, delivery.channel_id)
            if channel is None:
                delivery.status = PostDeliveryStatus.failed
                delivery.error_message = f"Channel {delivery.channel_id} not found"
                failed_messages.append(delivery.error_message)
                continue
            try:
                adapter = self._get_channel_adapter(channel)
                media_urls = self._media_urls_for_post(post, channel.provider)
                result = asyncio.run(
                    adapter.publish_post(
                        self._delivery_content(post, delivery),
                        media_urls=media_urls,
                        title=post.title,
                    )
                )
            except Exception as exc:
                delivery.status = PostDeliveryStatus.failed
                delivery.error_message = str(exc)
                delivery.external_post_id = None
                delivery.published_at = None
                failed_messages.append(f"{channel.name}: {exc}")
                logger.warning(
                    "Failed to publish Post %s to %s: %s",
                    post_id,
                    channel.name,
                    exc,
                )
                continue

            delivery.status = PostDeliveryStatus.published
            delivery.external_post_id = result.external_post_id
            delivery.published_at = published_at
            delivery.error_message = None
            published_count += 1
            if primary_external_post_id is None:
                primary_external_post_id = result.external_post_id

        if published_count == 0:
            self.db.flush()
            raise RuntimeError("; ".join(failed_messages) or "Publishing failed")

        post.status = PostStatus.published
        post.external_post_id = primary_external_post_id
        post.published_at = published_at
        self.db.flush()
        logger.info(
            "Published Post %s to %d channel deliveries",
            post_id,
            published_count,
        )
        return post

    def update_published_post(
        self,
        post_id: UUID,
        *,
        title: str | None,
        content: str | None,
        channel_id: UUID | None,
        scheduled_at: datetime | None,
    ) -> Post:
        """Update a published post remotely, then persist local state."""
        post = self.db.get(Post, post_id)
        if post is None:
            raise ValueError(f"Post {post_id} not found")
        if post.status != PostStatus.published:
            raise ValueError(f"Post {post_id} is not published")
        if content is None or not content.strip():
            raise ValueError("Published posts require content")
        delivery, channel, external_post_id = self._single_published_target(post)
        target_channel_id = (
            delivery.channel_id if delivery is not None else post.channel_id
        )
        if channel_id and channel_id != target_channel_id:
            raise ValueError("Cannot move a published post to a different channel")
        if channel.status != ChannelStatus.connected:
            raise ValueError(f"Channel {channel.name} is not connected")

        adapter = self._get_channel_adapter(channel)
        if not getattr(adapter, "supports_remote_update", False):
            raise ValueError(f"{channel.name} does not support remote post updates")

        media_urls = self._media_urls_for_post(post, channel.provider)
        result = asyncio.run(
            adapter.update_post(
                external_post_id,
                content,
                media_urls=media_urls,
                title=title,
            )
        )

        post.title = title if title is not None else post.title
        post.content = content
        post.scheduled_at = scheduled_at
        if delivery is not None:
            delivery.content_override = content
            if result.external_post_id:
                delivery.external_post_id = result.external_post_id
        if result.external_post_id:
            post.external_post_id = result.external_post_id
        self.db.flush()
        logger.info("Updated published Post %s on %s", post_id, channel.name)
        return post

    def delete_published_post(self, post_id: UUID) -> None:
        """Delete a published post remotely, then remove the local record."""
        post = self.db.get(Post, post_id)
        if post is None:
            raise ValueError(f"Post {post_id} not found")
        if post.status != PostStatus.published:
            raise ValueError(f"Post {post_id} is not published")
        _delivery, channel, external_post_id = self._single_published_target(post)
        if channel.status != ChannelStatus.connected:
            raise ValueError(f"Channel {channel.name} is not connected")

        adapter = self._get_channel_adapter(channel)
        if not getattr(adapter, "supports_remote_delete", False):
            raise ValueError(f"{channel.name} does not support remote post deletion")

        asyncio.run(adapter.delete_post(external_post_id))
        self.db.delete(post)
        self.db.flush()
        logger.info("Deleted published Post %s from %s", post_id, channel.name)

    def publish_due_posts(self) -> list[UUID]:
        """Find and publish all posts with status=planned and scheduled_at <= now.

        Returns list of successfully published post IDs.
        Errors are logged per-post; one failure does not block others.
        """
        now = datetime.now(UTC)
        stmt = (
            select(Post)
            .options(selectinload(Post.deliveries).selectinload(PostDelivery.channel))
            .where(Post.status == PostStatus.planned)
            .where(Post.scheduled_at.isnot(None))
            .where(Post.scheduled_at <= now)
            .order_by(Post.scheduled_at)
        )
        due_posts = list(self.db.scalars(stmt).all())

        published_ids: list[UUID] = []
        for post in due_posts:
            try:
                self.publish(post.id)
                published_ids.append(post.id)
            except (ValueError, RuntimeError, NotImplementedError) as e:
                logger.error("Failed to publish Post %s: %s", post.id, e)
        return published_ids
