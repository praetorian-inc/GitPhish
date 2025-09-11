"""
SMS delivery CLI module for GitPhish campaigns.
Uses modular SMS services from core.sms package.
"""

import logging
import os
from gitphish.core.sms import SMSCampaignService


def setup_sms_campaigns_subparser(parent_parser):
    """Setup SMS campaigns subparser."""
    sms_parser = parent_parser.add_parser('sms', help='SMS delivery for phishing campaigns')
    sms_subparsers = sms_parser.add_subparsers(dest='sms_command', help='SMS delivery providers')
    
    # Twilio SMS delivery
    twilio_parser = sms_subparsers.add_parser('twilio', help='Send SMS via Twilio')
    twilio_parser.add_argument('-e', '--email', required=True, help='Target email address')
    twilio_parser.add_argument('-p', '--phone', required=True, help='Target phone number')
    twilio_parser.add_argument('--sid', required=True, help='Twilio Account SID')
    twilio_parser.add_argument('--token', required=True, help='Twilio Auth Token')
    twilio_parser.add_argument('--from-phone', required=True, help='Twilio phone number')
    twilio_parser.add_argument('--message', required=True, help='SMS message template')
    twilio_parser.add_argument('--client-id', help='OAuth app client ID')
    twilio_parser.add_argument('--org-name', help='Target organization name') 
    twilio_parser.add_argument('--scope', default='repo user', help='OAuth scopes for token requests')
    twilio_parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    twilio_parser.add_argument('--poll-tokens', action='store_true', help='Poll for OAuth token completion after sending SMS')
    twilio_parser.set_defaults(func=send_twilio_campaign)
    
    # AWS SNS SMS delivery
    aws_parser = sms_subparsers.add_parser('aws', help='Send SMS via AWS SNS')
    aws_parser.add_argument('-e', '--email', required=True, help='Target email address')
    aws_parser.add_argument('-p', '--phone', required=True, help='Target phone number')
    aws_parser.add_argument('--region', default='us-east-2', help='AWS region')
    aws_parser.add_argument('--message', required=True, help='SMS message template')
    aws_parser.add_argument('--client-id', help='OAuth app client ID')
    aws_parser.add_argument('--org-name', help='Target organization name')
    aws_parser.add_argument('--scope', default='repo user', help='OAuth scopes for token requests')
    aws_parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    aws_parser.add_argument('--poll-tokens', action='store_true', help='Poll for OAuth token completion after sending SMS')
    aws_parser.set_defaults(func=send_aws_campaign)
    
    return sms_parser


def _create_campaign_config(args, provider):
    """Create campaign configuration from CLI arguments."""
    config = {
        'provider': provider,
        'email': args.email,
        'phone': args.phone,
        'message': args.message,
        'client_id': getattr(args, 'client_id', None),
        'org_name': getattr(args, 'org_name', None),
        'debug': getattr(args, 'debug', False),
        'poll_tokens': getattr(args, 'poll_tokens', False)
    }
    
    # Add provider-specific config
    if provider == 'twilio':
        config.update({
            'twilio_sid': args.sid,
            'twilio_token': args.token,
            'from_phone': args.from_phone
        })
    elif provider == 'aws':
        config.update({
            'aws_region': getattr(args, 'region', 'us-east-2'),
            'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
            'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY'),
            'aws_session_token': os.getenv('AWS_SESSION_TOKEN')
        })
    
    return config


def send_twilio_campaign(args):
    """Send SMS via Twilio with optional OAuth integration."""
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
    
    # Create service and config
    service = SMSCampaignService()
    config = _create_campaign_config(args, 'twilio')
    
    # Run campaign
    logging.info("📱 Starting Twilio SMS campaign")
    result = service.run_single_campaign(config)
    
    if result['success']:
        logging.info("✅ SMS sent successfully")
        if result.get('oauth_completed'):
            logging.info("🎉 OAuth token completed!")
        elif result.get('device_flow'):
            logging.info("⏰ OAuth polling timed out - this is normal")
        return 0
    else:
        logging.error(f"❌ Campaign failed: {result.get('error', 'Unknown error')}")
        return 1


def send_aws_campaign(args):
    """Send SMS via AWS SNS with optional OAuth integration."""
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
    
    # Create service and config
    service = SMSCampaignService()
    config = _create_campaign_config(args, 'aws')
    
    # Run campaign
    logging.info("📱 Starting AWS SNS SMS campaign")
    result = service.run_single_campaign(config)
    
    if result['success']:
        logging.info("✅ SMS sent successfully")
        if result.get('oauth_completed'):
            logging.info("🎉 OAuth token completed!")
        elif result.get('device_flow'):
            logging.info("⏰ OAuth polling timed out - this is normal")
        return 0
    else:
        logging.error(f"❌ Campaign failed: {result.get('error', 'Unknown error')}")
        return 1