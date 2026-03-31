from __future__ import annotations

from app.adapters.base import ChannelAdapter
from app.adapters.google_ads import GoogleAdsAdapter
from app.adapters.google_analytics import GoogleAnalyticsAdapter
from app.adapters.linkedin import LinkedInAdapter
from app.adapters.meta import MetaAdapter
from app.adapters.meta_ads import MetaAdsAdapter
from app.adapters.twitter import TwitterAdapter
from app.models.channel import ChannelProvider

ADAPTER_MAP: dict[ChannelProvider, type[ChannelAdapter]] = {
    ChannelProvider.meta_instagram: MetaAdapter,
    ChannelProvider.meta_facebook: MetaAdapter,
    ChannelProvider.meta_ads: MetaAdsAdapter,
    ChannelProvider.twitter: TwitterAdapter,
    ChannelProvider.linkedin: LinkedInAdapter,
    ChannelProvider.linkedin_ads: LinkedInAdapter,
    ChannelProvider.google_ads: GoogleAdsAdapter,
    ChannelProvider.google_analytics: GoogleAnalyticsAdapter,
}


def get_adapter(provider: ChannelProvider, **kwargs: str) -> ChannelAdapter:
    """Instantiate the correct adapter for a given channel provider."""
    adapter_cls = ADAPTER_MAP.get(provider)
    if not adapter_cls:
        raise ValueError(f"No adapter for provider: {provider}")
    if adapter_cls is MetaAdapter:
        kwargs.setdefault("provider", provider)
    return adapter_cls(**kwargs)
