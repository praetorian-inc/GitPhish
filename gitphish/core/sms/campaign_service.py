"""
SMS Campaign service for GitPhish.
Handles campaign creation, execution, and management.
"""

import os
import uuid
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from gitphish.models.database import db_session_scope, get_database_manager
from gitphish.models.sms.campaign import SMSCampaign
from gitphish.core.cli.sms_campaigns import send_twilio_sms, send_aws_sms


logger = logging.getLogger(__name__)


class SMSCampaignService:
    """Service for managing SMS campaigns."""
    
    def __init__(self):
        # Dictionary to store running campaign threads
        self.running_campaigns = {}
        # Initialize database
        get_database_manager()
    
    def create_campaign(self, data: Dict[str, Any]) -> str:
        """Create a new SMS campaign."""
        campaign_id = f"sms_{uuid.uuid4().hex[:8]}"
        
        # Prepare targets list
        targets = []
        if data.get('targetMethod') == 'single':
            if data.get('targetEmail') and data.get('targetPhone'):
                targets.append({
                    'email': data['targetEmail'],
                    'phone': data['targetPhone']
                })
        
        # Prepare provider config
        config = {}
        if data.get('provider') == 'twilio':
            config = {
                'sid': data.get('twilioSid'),
                'token': data.get('twilioToken'),
                'from_phone': data.get('fromPhone')
            }
        elif data.get('provider') == 'aws':
            config = {
                'access_key_id': data.get('awsAccessKeyId'),
                'secret_access_key': data.get('awsSecretAccessKey'),
                'session_token': data.get('awsSessionToken'),
                'region': data.get('awsRegion', 'us-east-2')
            }
        
        # Create campaign in database
        with db_session_scope() as session:
            campaign = SMSCampaign(
                id=campaign_id,
                name=data.get('name', 'Unnamed Campaign'),
                platform=data.get('platform', 'github'),
                provider=data.get('provider'),
                config=config,
                target_method=data.get('targetMethod', 'single'),
                targets=targets,
                message_template=data.get('messageTemplate', ''),
                oauth_scope=data.get('scope', 'repo user'),
                encryption_key=data.get('encryptionKey'),
                proxy_url=data.get('proxyUrl'),
                debug_mode=data.get('debug', False)
            )
            
            campaign.add_log(f"Campaign '{campaign.name}' created with {len(targets)} targets")
            session.add(campaign)
            session.commit()
        
        return campaign_id
    
    def start_campaign(self, campaign_id: str) -> bool:
        """Start a campaign execution in a background thread."""
        if campaign_id in self.running_campaigns:
            logger.warning(f"Campaign {campaign_id} is already running")
            return False
        
        # Get campaign from database
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found")
                return False
            
            # Update status to running
            campaign.status = 'running'
            campaign.started_at = datetime.now(timezone.utc)
            campaign.add_log("Campaign started")
            session.commit()
        
        # Start campaign in background thread
        thread = threading.Thread(target=self._execute_campaign, args=(campaign_id,))
        thread.daemon = True
        self.running_campaigns[campaign_id] = thread
        thread.start()
        
        logger.info(f"Campaign {campaign_id} started in background thread")
        return True
    
    def _execute_campaign(self, campaign_id: str):
        """Execute the campaign (runs in background thread)."""
        logger.info(f"Executing campaign {campaign_id}")
        
        try:
            with db_session_scope() as session:
                campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                if not campaign:
                    logger.error(f"Campaign {campaign_id} not found during execution")
                    return
                
                # Set up AWS credentials if using AWS
                if campaign.provider == 'aws' and campaign.config:
                    if campaign.config.get('access_key_id'):
                        os.environ['AWS_ACCESS_KEY_ID'] = campaign.config['access_key_id']
                    if campaign.config.get('secret_access_key'):
                        os.environ['AWS_SECRET_ACCESS_KEY'] = campaign.config['secret_access_key']
                    if campaign.config.get('session_token'):
                        os.environ['AWS_SESSION_TOKEN'] = campaign.config['session_token']
                
                campaign.add_log(f"Starting SMS delivery for {len(campaign.targets)} targets")
                session.commit()
                
                # Send SMS to each target
                for i, target in enumerate(campaign.targets, 1):
                    if campaign.status == 'stopped':
                        campaign.add_log("Campaign stopped by user")
                        break
                    
                    email = target.get('email')
                    phone = target.get('phone')
                    
                    # Prepare message with sample OAuth data
                    message = self._prepare_message(campaign.message_template, email)
                    
                    campaign.add_log(f"Sending SMS {i}/{len(campaign.targets)} to {phone}")
                    session.commit()
                    
                    # Send SMS
                    success = False
                    if campaign.provider == 'twilio':
                        success = send_twilio_sms(
                            phone=phone,
                            message=message,
                            sid=campaign.config.get('sid'),
                            token=campaign.config.get('token'),
                            from_phone=campaign.config.get('from_phone'),
                            email=email
                        )
                    elif campaign.provider == 'aws':
                        success = send_aws_sms(
                            phone=phone,
                            message=message,
                            region=campaign.config.get('region', 'us-east-2'),
                            email=email
                        )
                    
                    if success:
                        campaign.sms_sent += 1
                        campaign.add_log(f"✅ SMS sent successfully to {phone}")
                    else:
                        campaign.add_log(f"❌ Failed to send SMS to {phone}")
                    
                    session.commit()
                    
                    # Small delay between sends
                    time.sleep(1)
                
                # Mark campaign as completed
                campaign.status = 'completed'
                campaign.completed_at = datetime.now(timezone.utc)
                campaign.add_log(f"Campaign completed. SMS sent: {campaign.sms_sent}/{len(campaign.targets)}")
                session.commit()
                
        except Exception as e:
            logger.error(f"Error executing campaign {campaign_id}: {str(e)}")
            with db_session_scope() as session:
                campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                if campaign:
                    campaign.status = 'failed'
                    campaign.completed_at = datetime.now(timezone.utc)
                    campaign.add_log(f"Campaign failed: {str(e)}")
                    session.commit()
        
        finally:
            # Remove from running campaigns
            if campaign_id in self.running_campaigns:
                del self.running_campaigns[campaign_id]
    
    def _prepare_message(self, template: str, email: str) -> str:
        """Prepare SMS message with OAuth variables."""
        # For this implementation, we'll use placeholder OAuth data
        # In a real campaign, this would integrate with GitHub OAuth device flow
        variables = {
            'email': email,
            'verification_uri': 'https://github.com/login/device',
            'user_code': 'ABCD-1234',
            'device_code': 'sample_device_code_1234567890'
        }
        
        message = template
        for var, value in variables.items():
            message = message.replace(f'{{{var}}}', value)
        
        return message
    
    def stop_campaign(self, campaign_id: str) -> bool:
        """Stop a running campaign."""
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if not campaign:
                return False
            
            campaign.status = 'stopped'
            campaign.completed_at = datetime.now(timezone.utc)
            campaign.add_log("Campaign stopped by user")
            session.commit()
        
        # The background thread will check the status and stop gracefully
        if campaign_id in self.running_campaigns:
            logger.info(f"Campaign {campaign_id} marked for stopping")
        
        return True
    
    def list_campaigns(self) -> List[Dict[str, Any]]:
        """List all campaigns."""
        with db_session_scope() as session:
            campaigns = session.query(SMSCampaign).order_by(SMSCampaign.created_at.desc()).all()
            return [campaign.to_dict() for campaign in campaigns]
    
    def get_campaign_logs(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """Get campaign logs and status."""
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if not campaign:
                return None
            
            return {
                'success': True,
                'output': campaign.logs or 'No logs yet...',
                'stats': {
                    'status': campaign.status,
                    'sms_sent': campaign.sms_sent,
                    'tokens_captured': campaign.tokens_captured,
                    'runtime': campaign.get_runtime()
                },
                'tokens': campaign.captured_tokens or []
            }


# Global service instance
_campaign_service: Optional[SMSCampaignService] = None


def get_campaign_service() -> SMSCampaignService:
    """Get the global campaign service instance."""
    global _campaign_service
    if _campaign_service is None:
        _campaign_service = SMSCampaignService()
    return _campaign_service