"""
SMS Provider Implementations
Single job: Send SMS messages via different providers (Twilio, AWS SNS)
"""

import logging
import boto3
from twilio.rest import Client
from botocore.exceptions import BotoCoreError, ClientError
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TwilioSMSProvider:
    """Handles SMS sending via Twilio."""
    
    def __init__(self, account_sid: str, auth_token: str, from_phone: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_phone = from_phone
        self._client = None
    
    @property
    def client(self):
        """Lazy-loaded Twilio client."""
        if self._client is None:
            self._client = Client(self.account_sid, self.auth_token)
        return self._client
    
    def send_sms(self, to_phone: str, message: str) -> Dict[str, Any]:
        """Send SMS via Twilio."""
        try:
            response = self.client.messages.create(
                to=to_phone,
                from_=self.from_phone,
                body=message
            )
            
            return {
                'success': True,
                'message_id': response.sid,
                'provider': 'twilio'
            }
        except Exception as e:
            logger.error(f"Twilio SMS failed to {to_phone}: {e}")
            return {
                'success': False,
                'error': str(e),
                'provider': 'twilio'
            }
    
    def test_connection(self) -> Dict[str, Any]:
        """Test Twilio configuration."""
        try:
            account = self.client.api.accounts(self.account_sid).fetch()
            return {
                'success': True,
                'account_name': account.friendly_name,
                'provider': 'twilio'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'provider': 'twilio'
            }


class AWSSNSSMSProvider:
    """Handles SMS sending via AWS SNS."""
    
    def __init__(self, region: str = 'us-east-2', aws_access_key_id: str = None, 
                 aws_secret_access_key: str = None, aws_session_token: str = None):
        self.region = region
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_session_token = aws_session_token
        self._client = None
    
    @property
    def client(self):
        """Lazy-loaded AWS SNS client."""
        if self._client is None:
            client_config = {'region_name': self.region}
            
            if self.aws_access_key_id and self.aws_secret_access_key:
                client_config.update({
                    'aws_access_key_id': self.aws_access_key_id,
                    'aws_secret_access_key': self.aws_secret_access_key
                })
                if self.aws_session_token:
                    client_config['aws_session_token'] = self.aws_session_token
            
            self._client = boto3.client('sns', **client_config)
        return self._client
    
    def send_sms(self, to_phone: str, message: str) -> Dict[str, Any]:
        """Send SMS via AWS SNS."""
        try:
            response = self.client.publish(
                PhoneNumber=to_phone,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SenderID': {
                        'DataType': 'String',
                        'StringValue': 'GitPhish'
                    },
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'
                    }
                }
            )
            
            return {
                'success': True,
                'message_id': response['MessageId'],
                'provider': 'aws'
            }
        except Exception as e:
            logger.error(f"AWS SNS SMS failed to {to_phone}: {e}")
            return {
                'success': False,
                'error': str(e),
                'provider': 'aws'
            }
    
    def test_connection(self) -> Dict[str, Any]:
        """Test AWS SNS configuration."""
        try:
            self.client.list_topics()
            return {
                'success': True,
                'region': self.region,
                'provider': 'aws'
            }
        except (BotoCoreError, ClientError) as e:
            return {
                'success': False,
                'error': str(e),
                'provider': 'aws'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'provider': 'aws'
            }


class SMSProviderFactory:
    """Factory for creating SMS providers."""
    
    @staticmethod
    def create_twilio_provider(account_sid: str, auth_token: str, from_phone: str) -> TwilioSMSProvider:
        """Create Twilio SMS provider."""
        return TwilioSMSProvider(account_sid, auth_token, from_phone)
    
    @staticmethod
    def create_aws_provider(region: str = 'us-east-2', aws_access_key_id: str = None,
                           aws_secret_access_key: str = None, aws_session_token: str = None) -> AWSSNSSMSProvider:
        """Create AWS SNS SMS provider."""
        return AWSSNSSMSProvider(region, aws_access_key_id, aws_secret_access_key, aws_session_token)