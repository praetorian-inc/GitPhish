"""
Twilio SMS provider implementation.
Uses the Twilio REST API to send SMS messages.
"""

from typing import Any, Optional
import logging
from twilio.rest import Client

from .base import SMSProvider, ArgSpec

logger = logging.getLogger(__name__)


class TwilioProvider(SMSProvider):
    """Twilio SMS provider.

    Expected config keys: sid, token, from_phone
    """

    def send_sms(
        self,
        phone: str,
        message: str,
        email: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """Send SMS via Twilio.

        Args:
            phone: E.164 formatted phone number
            message: SMS message body
            email: Optional email for correlation

        Returns:
            Tuple of (success: bool, error: Optional[str])
        """
        sid = self.config.get("sid")
        token = self.config.get("token")
        from_phone = self.config.get("from_phone")

        if not sid or not token or not from_phone:
            error_msg = "Twilio config missing required fields: sid/token/from_phone"
            logger.error(error_msg)
            return (False, error_msg)

        # Send SMS via Twilio API
        try:
            client = Client(sid, token)
            client.messages.create(
                body=message,
                from_=from_phone,
                to=phone,
            )
            return (True, None)
        except Exception as e:
            error_msg = f"Twilio error: {type(e).__name__}: {str(e)}"
            logger.error(f"Twilio SMS failed for {phone}: {error_msg}")
            return (False, error_msg)

    def test_config(self) -> dict[str, Any]:
        sid = self.config.get("sid")
        token = self.config.get("token")
        from_phone = self.config.get("from_phone")

        if not sid or not token:
            return {"success": False, "error": "Missing sid or token"}

        try:
            client = Client(sid, token)
            # Validate credentials by fetching account info
            account = client.api.accounts(sid).fetch()
            return {
                "success": True,
                "details": f"Twilio credentials valid for account {account.friendly_name}",
                "from_phone": from_phone,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Twilio authentication failed: {type(e).__name__}: {str(e)}",
            }

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        errors = []
        if not config.get("sid"):
            errors.append("sid is required")
        if not config.get("token"):
            errors.append("token is required")
        if not config.get("from_phone"):
            errors.append("from_phone is required")
        return {"success": len(errors) == 0, "errors": errors}

    @classmethod
    def get_arg_specs(cls) -> list[ArgSpec]:
        return [
            ArgSpec(
                name="sid",
                flags=["--sid"],
                required=True,
                help="Twilio Account SID",
                env="TWILIO_SID",
            ),
            ArgSpec(
                name="token",
                flags=["--token"],
                required=True,
                help="Twilio Auth Token",
                env="TWILIO_TOKEN",
                secret=True,
            ),
            ArgSpec(
                name="from_phone",
                flags=["--from-phone"],
                required=True,
                help=(
                    "Sender phone number (E.164)"
                ),
                env="TWILIO_FROM",
            ),
        ]
