"""
AWS SNS SMS provider implementation.
Uses boto3 to publish SMS messages via AWS SNS.
"""
from typing import Any, Optional
import logging
import boto3

from .base import SMSProvider, ArgSpec

logger = logging.getLogger(__name__)


class AWSProvider(SMSProvider):
    """AWS SNS SMS provider.

    Expected config keys: region, access_key_id, secret_access_key,
    session_token (optional)
    """

    def send_sms(
        self,
        phone: str,
        message: str,
        email: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """Send SMS via AWS SNS.

        Args:
            phone: E.164 formatted phone number
            message: SMS message body
            email: Optional email for correlation

        Returns:
            Tuple of (success: bool, error: Optional[str])
        """
        region = self.config.get("region", "us-east-2")
        access_key = self.config.get("access_key_id")
        secret_key = self.config.get("secret_access_key")
        session_token = self.config.get("session_token")

        # Build session kwargs
        session_kwargs: dict[str, Any] = {
            "region_name": region,
        }
        if access_key and secret_key:
            session_kwargs.update(
                {
                    "aws_access_key_id": access_key,
                    "aws_secret_access_key": secret_key,
                }
            )
            if session_token:
                session_kwargs["aws_session_token"] = session_token

        # Send SMS via AWS SNS
        try:
            client = boto3.client("sns", **session_kwargs)
            client.publish(PhoneNumber=phone, Message=message)
            return (True, None)
        except Exception as e:
            error_msg = f"AWS SNS error: {type(e).__name__}: {str(e)}"
            logger.error(f"AWS SNS SMS failed for {phone}: {error_msg}")
            return (False, error_msg)

    def test_config(self) -> dict[str, Any]:
        region = self.config.get("region", "us-east-2")
        access_key = self.config.get("access_key_id")
        secret_key = self.config.get("secret_access_key")
        session_token = self.config.get("session_token")

        if not access_key or not secret_key:
            return {
                "success": False,
                "error": "Missing access_key_id or secret_access_key",
            }

        session_kwargs: dict[str, Any] = {
            "region_name": region,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
        }
        if session_token:
            session_kwargs["aws_session_token"] = session_token

        try:
            client = boto3.client("sns", **session_kwargs)
            client.get_sms_attributes()
            return {
                "success": True,
                "details": f"AWS SNS credentials valid for region {region}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"AWS authentication failed: {type(e).__name__}: {str(e)}",
            }

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        errors = []
        if not config.get("access_key_id"):
            errors.append("access_key_id is required")
        if not config.get("secret_access_key"):
            errors.append("secret_access_key is required")
        # region optional; default applied by provider
        return {"success": len(errors) == 0, "errors": errors}

    @classmethod
    def get_arg_specs(cls) -> list[ArgSpec]:
        return [
            ArgSpec(
                name="access_key_id",
                flags=["--access-key-id"],
                required=True,
                help="AWS Access Key ID",
                env="AWS_ACCESS_KEY_ID",
                secret=True,
            ),
            ArgSpec(
                name="secret_access_key",
                flags=["--secret-access-key"],
                required=True,
                help="AWS Secret Access Key",
                env="AWS_SECRET_ACCESS_KEY",
                secret=True,
            ),
            ArgSpec(
                name="session_token",
                flags=["--session-token"],
                required=False,
                help="AWS Session Token (optional)",
                env="AWS_SESSION_TOKEN",
                secret=True,
            ),
            ArgSpec(
                name="region",
                flags=["--region"],
                required=False,
                help="AWS region",
                env="AWS_DEFAULT_REGION",
                default="us-east-2",
                choices=[
                    "us-east-1",
                    "us-east-2",
                    "us-west-2",
                    "eu-west-1",
                    "eu-central-1",
                ],
            ),
        ]
