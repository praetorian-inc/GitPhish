"""
OAuth Template Processing
Single job: Process OAuth device flow and replace template variables in messages
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class OAuthTemplateProcessor:
    """Handles OAuth device flow and template variable replacement."""
    
    def __init__(self):
        self._oauth_handler = None
    
    @property
    def oauth_handler(self):
        """Lazy-loaded OAuth handler."""
        if self._oauth_handler is None:
            from gitphish.core.manual.manual import ManualDeviceAuth
            self._oauth_handler = ManualDeviceAuth()
        return self._oauth_handler
    
    def has_oauth_variables(self, message: str) -> bool:
        """Check if message contains OAuth template variables."""
        oauth_vars = ['{verification_uri}', '{user_code}', '{email}', '{device_code}']
        return any(var in message for var in oauth_vars)
    
    def initiate_device_flow(self, client_id: str, org_name: str, email: str) -> Optional[Dict[str, Any]]:
        """Initiate OAuth device flow."""
        try:
            device_flow = self.oauth_handler.run_manual_device_code_flow(
                client_id=client_id,
                org_name=org_name,
                email=email,
                skip_wait=True  # Don't wait, just get device codes
            )
            
            if isinstance(device_flow, dict) and 'user_code' in device_flow:
                return device_flow
            else:
                logger.error("Failed to get device flow data")
                return None
                
        except Exception as e:
            logger.error(f"OAuth device flow initiation failed: {e}")
            return None
    
    def process_template(self, message: str, email: str, device_flow_data: Dict[str, Any]) -> str:
        """Replace OAuth template variables in message."""
        try:
            processed_message = message
            
            # Replace template variables
            processed_message = processed_message.replace('{email}', email or '')
            processed_message = processed_message.replace('{user_code}', device_flow_data.get('user_code', ''))
            processed_message = processed_message.replace('{verification_uri}', 
                                                        device_flow_data.get('verification_uri', 'https://github.com/login/device'))
            processed_message = processed_message.replace('{device_code}', device_flow_data.get('device_code', ''))
            
            return processed_message
        except Exception as e:
            logger.error(f"Template processing failed: {e}")
            return message
    
    def process_message_with_oauth(self, message: str, email: str, client_id: str, org_name: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Process message with OAuth integration if needed."""
        if not self.has_oauth_variables(message):
            return message, None
        
        if not client_id or not org_name:
            logger.error("OAuth variables found but client_id or org_name not provided")
            return message, None
        
        device_flow = self.initiate_device_flow(client_id, org_name, email)
        if not device_flow:
            return message, None
        
        processed_message = self.process_template(message, email, device_flow)
        return processed_message, device_flow
    
    def poll_for_token_completion(self, client_id: str, org_name: str, device_code: str, email: str) -> bool:
        """Poll for OAuth token completion."""
        try:
            success = self.oauth_handler.poll_for_token_only(
                client_id=client_id,
                org_name=org_name,
                device_code=device_code,
                email=email
            )
            return success
        except Exception as e:
            logger.error(f"OAuth token polling failed: {e}")
            return False