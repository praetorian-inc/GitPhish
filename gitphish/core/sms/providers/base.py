"""
Provider interface for SMS delivery.

This module defines the minimal contract that concrete SMS providers must
implement so the rest of the system can remain provider-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


class SMSProvider(ABC):
    """Abstract base class for SMS providers."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def send_sms(
        self, phone: str, message: str, email: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Send an SMS message.

        Args:
            phone: E.164 formatted destination phone number.
            message: Message body to send.
            email: Optional email for correlation/templating.

        Returns:
            Tuple of (success: bool, error: Optional[str])
            - (True, None) on success
            - (False, "error message") on failure
        """

    @abstractmethod
    def test_config(self) -> dict[str, Any]:
        """Validate provider configuration and connectivity.

        Returns a dict like {"success": bool, "details": str}.
        """

    @classmethod
    @abstractmethod
    def get_arg_specs(cls) -> list[ArgSpec]:
        """Return argument specifications for CLI generation."""

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate a config dict against provider requirements.

        Returns {"success": bool, "errors": [..]}.
        """


@dataclass
class ArgSpec:
    """Specification for a single CLI argument.

    This is intentionally minimal and CLI-agnostic; the CLI layer will
    translate it into argparse parameters.
    """

    name: str
    flags: list[str]
    required: bool = False
    help: str = ""
    type: Optional[str] = "string"
    env: Optional[str] = None
    default: Optional[Any] = None
    choices: Optional[list[Any]] = None
    secret: bool = False
