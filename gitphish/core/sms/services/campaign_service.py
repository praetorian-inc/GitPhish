"""
SMS Campaign Service
Single job: Orchestrate SMS campaigns (single and batch) using providers and processors
"""

import logging
from typing import Dict, Any, List, Tuple, Optional
from .providers import SMSProviderFactory
from .oauth_processor import OAuthTemplateProcessor
from .csv_parser import CSVTargetParser

logger = logging.getLogger(__name__)


class SMSCampaignService:
    """Main service for orchestrating SMS campaigns."""
    
    def __init__(self):
        self.oauth_processor = OAuthTemplateProcessor()
        self.csv_parser = CSVTargetParser()
    
    def run_single_campaign(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run a single SMS campaign.
        
        Args:
            config: Campaign configuration containing:
                - provider: 'twilio' or 'aws'
                - email: Target email
                - phone: Target phone  
                - message: Message template
                - Provider-specific credentials
                - OAuth config (optional)
        
        Returns:
            Campaign result dictionary
        """
        try:
            # Extract base config
            provider = config['provider']
            email = config['email']
            phone = config['phone']
            message = config['message']
            
            # Process OAuth template if needed
            processed_message, device_flow = self.oauth_processor.process_message_with_oauth(
                message=message,
                email=email,
                client_id=config.get('client_id'),
                org_name=config.get('org_name')
            )
            
            # Create SMS provider
            sms_provider = self._create_sms_provider(config)
            if not sms_provider:
                return {'success': False, 'error': f'Failed to create {provider} provider'}
            
            # Send SMS
            sms_result = sms_provider.send_sms(phone, processed_message)
            
            result = {
                'success': sms_result['success'],
                'email': email,
                'phone': phone,
                'provider': provider,
                'message_id': sms_result.get('message_id'),
                'sms_sent': 1 if sms_result['success'] else 0,
                'device_flow': device_flow
            }
            
            if not sms_result['success']:
                result['error'] = sms_result['error']
            
            # Poll for OAuth completion if requested
            if (sms_result['success'] and device_flow and config.get('poll_tokens', False)):
                oauth_success = self.oauth_processor.poll_for_token_completion(
                    client_id=config['client_id'],
                    org_name=config['org_name'],
                    device_code=device_flow.get('device_code'),
                    email=email
                )
                result['oauth_completed'] = oauth_success
            
            return result
            
        except Exception as e:
            logger.error(f"Single campaign failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'email': config.get('email'),
                'phone': config.get('phone')
            }
    
    def run_batch_campaign(self, config: Dict[str, Any], targets: List[Tuple[str, str]]) -> Dict[str, Any]:
        """
        Run a batch SMS campaign with multiple targets.
        
        Args:
            config: Base campaign configuration
            targets: List of (email, phone) tuples
        
        Returns:
            Batch campaign result dictionary
        """
        try:
            results = []
            successful_campaigns = 0
            
            for email, phone in targets:
                # Create individual campaign config
                individual_config = config.copy()
                individual_config.update({
                    'email': email,
                    'phone': phone
                })
                
                # Run individual campaign
                result = self.run_single_campaign(individual_config)
                result['target_email'] = email
                result['target_phone'] = phone
                results.append(result)
                
                if result['success']:
                    successful_campaigns += 1
            
            return {
                'success': True,
                'total_targets': len(targets),
                'successful_campaigns': successful_campaigns,
                'failed_campaigns': len(targets) - successful_campaigns,
                'success_rate': (successful_campaigns / len(targets) * 100) if targets else 0,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Batch campaign failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'total_targets': len(targets) if targets else 0,
                'successful_campaigns': 0,
                'failed_campaigns': len(targets) if targets else 0
            }
    
    def parse_csv_targets(self, csv_data: str) -> Dict[str, Any]:
        """
        Parse CSV target data.
        
        Args:
            csv_data: CSV string data
        
        Returns:
            Dictionary with targets and validation info
        """
        targets = self.csv_parser.parse_csv_data(csv_data)
        validation_summary = self.csv_parser.get_validation_summary(csv_data)
        
        return {
            'targets': targets,
            'validation': validation_summary
        }
    
    def test_provider_config(self, provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test SMS provider configuration.
        
        Args:
            provider: 'twilio' or 'aws'
            config: Provider configuration
        
        Returns:
            Test result dictionary
        """
        try:
            sms_provider = self._create_sms_provider({'provider': provider, **config})
            if not sms_provider:
                return {'success': False, 'error': f'Failed to create {provider} provider'}
            
            return sms_provider.test_connection()
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'provider': provider}
    
    def _create_sms_provider(self, config: Dict[str, Any]):
        """Create SMS provider based on configuration."""
        provider = config['provider']
        
        if provider == 'twilio':
            return SMSProviderFactory.create_twilio_provider(
                account_sid=config['twilio_sid'],
                auth_token=config['twilio_token'], 
                from_phone=config['from_phone']
            )
        elif provider == 'aws':
            return SMSProviderFactory.create_aws_provider(
                region=config.get('aws_region', 'us-east-2'),
                aws_access_key_id=config.get('aws_access_key_id'),
                aws_secret_access_key=config.get('aws_secret_access_key'),
                aws_session_token=config.get('aws_session_token')
            )
        else:
            logger.error(f"Unknown SMS provider: {provider}")
            return None