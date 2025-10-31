"""
SMS Campaigns API for GitPhish Admin Interface.
Provides REST endpoints for managing SMS campaigns using the SMSCampaignService.
"""

import logging
from typing import Dict, Any
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
        self._setup_routes()

    def _setup_routes(self):
        """Setup API routes."""

        @self.app.route('/api/sms-campaigns/start', methods=['POST'])
        def start_campaign():
            """Start a new SMS campaign."""
            try:
                data = request.get_json()

                required_fields = ['provider', 'name', 'messageTemplate']
                for field in required_fields:
                    if not data.get(field):
                        return jsonify({'success': False, 'error': f'{field} is required'}), 400

                provider = data['provider']

                if data.get('targetMethod') == 'file' and data.get('csvData'):
                    targets_result = self.sms_service.parse_csv_targets(data['csvData'])
                    if not targets_result['success']:
                        return jsonify({
                            'success': False,
                            'error': 'CSV parsing failed',
                            'errors': targets_result.get('errors', [])
                        }), 400
                    targets = targets_result['targets']
                elif data.get('targetMethod') == 'single':
                    if not data.get('targetEmail') or not data.get('targetPhone'):
                        return jsonify({'success': False, 'error': 'Email and phone required for single target'}), 400
                    targets = [{'email': data['targetEmail'], 'phone': data['targetPhone']}]
                else:
                    return jsonify({'success': False, 'error': 'Invalid target method'}), 400

                provider_config = self._extract_provider_config(data, provider)

                campaign_id = self.sms_service.create_campaign(
                    provider=provider,
                    targets=targets,
                    message_template=data['messageTemplate'],
                    name=data['name'],
                    client_id=data.get('clientId', '178c6fc778ccc68e1d6a'),
                    org_name=data.get('orgName', 'GitHub'),
                    skip_wait=data.get('skipWait', False),
                    **provider_config
                )

                if not self.sms_service.start_campaign(campaign_id):
                    return jsonify({'success': False, 'error': 'Failed to start campaign'}), 500

                logger.info(f"Started SMS campaign {campaign_id}")

                return jsonify({
                    'success': True,
                    'campaign_id': campaign_id,
                    'target_count': len(targets),
                    'message': 'Campaign started successfully'
                })

            except Exception as e:
                logger.error(f"Error starting campaign: {str(e)}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/list', methods=['GET'])
        def list_campaigns():
            """List all campaigns from database."""
            try:
                campaigns = self.sms_service.list_campaigns()
                return jsonify({'success': True, 'campaigns': campaigns})
            except Exception as e:
                logger.error(f"Error listing campaigns: {str(e)}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/stop/<campaign_id>', methods=['POST'])
        def stop_campaign(campaign_id):
            """Stop a running campaign."""
            try:
                if self.sms_service.stop_campaign(campaign_id):
                    logger.info(f"Stopped SMS campaign {campaign_id}")
                    return jsonify({'success': True, 'message': 'Campaign stopped successfully'})
                else:
                    return jsonify({'success': False, 'error': 'Campaign not found or already stopped'}), 404
            except Exception as e:
                logger.error(f"Error stopping campaign: {str(e)}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms-campaigns/logs/<campaign_id>', methods=['GET'])
        def get_campaign_logs(campaign_id):
            """Get campaign logs and status."""
            try:
                result = self.sms_service.get_campaign_logs(campaign_id)
                if not result:
                    return jsonify({'success': False, 'error': 'Campaign not found'}), 404

                return jsonify(result)
            except Exception as e:
                logger.error(f"Error getting campaign logs: {str(e)}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/sms/test-config', methods=['POST'])
        def test_provider_config():
            """Test SMS provider configuration."""
            try:
                data = request.get_json()
                provider = data.get('provider')

                if not provider:
                    return jsonify({'success': False, 'error': 'Provider is required'}), 400

                provider_config = self._extract_provider_config(data, provider)
                result = self.sms_service.test_provider_config(provider, provider_config)

                return jsonify(result)
            except Exception as e:
                logger.error(f"Error testing provider config: {str(e)}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)}), 500

    def _extract_provider_config(self, data: Dict[str, Any], provider: str) -> Dict[str, Any]:
        """Extract provider-specific configuration from request data."""
        config = {}

        if provider == 'twilio':
            if data.get('twilioSid'):
                config['sid'] = data['twilioSid']
            if data.get('twilioToken'):
                config['token'] = data['twilioToken']
            if data.get('fromPhone'):
                config['from_phone'] = data['fromPhone']

        elif provider == 'aws':
            if data.get('awsAccessKeyId'):
                config['access_key_id'] = data['awsAccessKeyId']
            if data.get('awsSecretAccessKey'):
                config['secret_access_key'] = data['awsSecretAccessKey']
            if data.get('awsSessionToken'):
                config['session_token'] = data['awsSessionToken']
            if data.get('awsRegion'):
                config['region'] = data['awsRegion']

        return config
