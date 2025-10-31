"""
Factory for constructing SMS providers from a provider name and config.
"""

from typing import Any

from .base import SMSProvider
from .twilio import TwilioProvider
from .aws import AWSProvider


class ProviderFactory:
    """Simple factory to resolve providers by name."""

    _PROVIDERS = {
        "twilio": TwilioProvider,
        "aws": AWSProvider,
    }

    @classmethod
    def get_provider(cls, name: str, config: dict[str, Any]) -> SMSProvider:
        provider_name = (name or "").strip().lower()
        if provider_name not in cls._PROVIDERS:
            raise ValueError(f"Unsupported SMS provider: {name}")
        return cls._PROVIDERS[provider_name](config)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available provider names."""
        return list(cls._PROVIDERS.keys())

    @classmethod
    def get_provider_class(cls, name: str):
        """Get provider class by name."""
        provider_name = (name or "").strip().lower()
        if provider_name not in cls._PROVIDERS:
            raise ValueError(f"Unsupported SMS provider: {name}")
        return cls._PROVIDERS[provider_name]
