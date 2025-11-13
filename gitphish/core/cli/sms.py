"""
SMS delivery CLI module for GitPhish campaigns.
Uses dynamic provider-based argument generation.
"""

import logging
import os
from typing import Any
from gitphish.core.sms import SMSCampaignService, ProviderFactory


def _validate_required_args(parser, args, provider_name):
    """Validate that required arguments are provided via CLI or environment.

    This is called after argparse parsing to check environment variables
    for arguments that weren't provided on the command line.
    """
    provider_class = ProviderFactory.get_provider_class(provider_name)
    missing = []

    for arg_spec in provider_class.get_arg_specs():
        if arg_spec.required:
            arg_name = arg_spec.name
            # Check if value provided via CLI or environment
            cli_value = vars(args).get(arg_name)
            env_value = os.getenv(arg_spec.env) if arg_spec.env else None

            if not cli_value and not env_value:
                # Required field missing from both sources
                arg_flag = arg_spec.flags[0]  # Use first flag (e.g., --sid)
                if arg_spec.env:
                    missing.append(f"{arg_flag} (or set {arg_spec.env})")
                else:
                    missing.append(arg_flag)

    if missing:
        parser.error(
            f"the following arguments are required (via CLI or environment): {', '.join(missing)}"
        )


def setup_sms_subparser(subparsers):
    """Add the 'sms' subparser and its options to the main parser."""
    sms_parser = subparsers.add_parser(
        'sms', help='SMS delivery for phishing campaigns'
    )
    sms_subparsers = sms_parser.add_subparsers(
        dest='provider', help='SMS delivery providers', required=True
    )

    # Get available providers
    available_providers = ProviderFactory.get_available_providers()

    for provider_name in available_providers:
        provider_class = ProviderFactory.get_provider_class(provider_name)

        # Create subparser for this provider
        provider_parser = sms_subparsers.add_parser(
            provider_name,
            help=f'Send SMS via {provider_name.title()}'
        )

        # Add common arguments - either single target OR CSV file
        provider_parser.add_argument(
            '-e', '--email', help='Target email address (for single target)'
        )
        provider_parser.add_argument(
            '-p', '--phone', help='Target phone number (for single target)'
        )
        provider_parser.add_argument(
            '--csv',
            help=(
                'CSV file with targets for batch sending. '
                'Format: "email,phone" with optional header row. '
                'Example: victim@example.com,+15551234567. '
                'Use instead of -e/-p'
            )
        )
        provider_parser.add_argument(
            '--message',
            required=True,
            help=(
                'SMS message template. Use {user_code} for GitHub code, '
                '{verification_uri} for URL, {email} for recipient. '
                'Example: "Hi {email}, verify at {verification_uri} with code {user_code}"'
            )
        )
        provider_parser.add_argument(
            '--client-id',
            default="178c6fc778ccc68e1d6a",
            help='GitHub OAuth app client ID (default: 178c6fc778ccc68e1d6a)'
        )
        provider_parser.add_argument(
            '--org-name',
            default="GitHub",
            help='Target organization name (default: GitHub)'
        )

        provider_parser.add_argument(
            '--debug', action='store_true', default=False,
            help='Enable debug logging'
        )
        provider_parser.add_argument(
            '--skip-wait', action='store_true', default=False,
            help='Skip waiting for OAuth tokens (send SMS only, no polling)'
        )

        # Add provider-specific arguments dynamically (now classmethod)
        for arg_spec in provider_class.get_arg_specs():
            # If argument has env variable fallback, it's not required on CLI
            is_required = arg_spec.required and not arg_spec.env

            # Update help text to mention environment variable
            help_text = arg_spec.help
            if arg_spec.env:
                help_text += f" (env: {arg_spec.env})"

            provider_parser.add_argument(
                *arg_spec.flags,
                required=is_required,
                help=help_text,
                type=arg_spec.type if isinstance(arg_spec.type, type) else str,
                choices=arg_spec.choices,
                default=arg_spec.default
            )

        # Set the handler function and store parser for validation
        provider_parser.set_defaults(
            func=send_sms_campaign,
            provider=provider_name,
            parser=provider_parser  # Store parser reference for error reporting
        )

    return sms_parser


def send_sms_campaign(args):
    """Send SMS via the specified provider using the campaign system."""
    # Configure logging FIRST before any imports/operations
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    else:
        # Suppress all logging for clean output (like deploy, manual modules)
        logging.basicConfig(level=logging.CRITICAL)
        # Also suppress SDK loggers specifically
        logging.getLogger('twilio.http_client').setLevel(logging.CRITICAL)
        logging.getLogger('boto3').setLevel(logging.CRITICAL)
        logging.getLogger('botocore').setLevel(logging.CRITICAL)
        logging.getLogger('urllib3').setLevel(logging.CRITICAL)

    # Validate target specification: either single target OR CSV file
    if args.csv:
        if args.email or args.phone:
            args.parser.error("Cannot use both --csv and -e/-p. Use --csv for batch or -e/-p for single target.")
    else:
        if not args.email or not args.phone:
            args.parser.error("Either --csv or both -e/--email and -p/--phone are required")

    # Validate that required args are provided via CLI or environment
    _validate_required_args(args.parser, args, args.provider)

    # Create service
    service = SMSCampaignService()

    # Handle batch sending from CSV
    if args.csv:
        return _send_batch_campaign(service, args)

    # Handle single target
    return _send_single_campaign(service, args)


def _send_batch_campaign(service, args):
    """Send SMS to multiple targets from CSV using the campaign system."""
    import os

    if not os.path.exists(args.csv):
        print(f"Error: CSV file not found: {args.csv}")
        return 1

    with open(args.csv, 'r') as f:
        csv_content = f.read()

    parse_result = service.parse_csv_targets(csv_content)

    if not parse_result['success']:
        print("Error: CSV parsing failed:")
        for error in parse_result.get('errors', []):
            print(f"  {error}")
        return 1

    targets = parse_result['targets']
    print(f"Found {len(targets)} targets in CSV")

    if parse_result.get('errors'):
        print(f"Warning: {len(parse_result['errors'])} rows had errors (skipped)")

    provider_config = _get_provider_config(args)

    print("\nCreating campaign...")
    campaign_id = service.create_campaign(
        provider=args.provider,
        targets=targets,
        message_template=args.message,
        name=f"CLI Batch Campaign from {os.path.basename(args.csv)}",
        client_id=args.client_id if hasattr(args, 'client_id') else None,
        org_name=args.org_name if hasattr(args, 'org_name') else None,
        skip_wait=args.skip_wait if hasattr(args, 'skip_wait') else False,
        **provider_config
    )
    print(f"Campaign ID: {campaign_id}")

    print("Starting campaign execution...")
    if not service.start_campaign(campaign_id):
        print("Error: Failed to start campaign")
        return 1

    return _monitor_campaign(service, campaign_id, len(targets))


def _send_single_campaign(service, args):
    """Send SMS to a single target using the campaign system."""
    targets = [{'email': args.email, 'phone': args.phone}]
    provider_config = _get_provider_config(args)

    print(f"Sending SMS to {args.phone}...")
    campaign_id = service.create_campaign(
        provider=args.provider,
        targets=targets,
        message_template=args.message,
        name=f"CLI Single Campaign to {args.email}",
        client_id=args.client_id if hasattr(args, 'client_id') else None,
        org_name=args.org_name if hasattr(args, 'org_name') else None,
        skip_wait=args.skip_wait if hasattr(args, 'skip_wait') else False,
        **provider_config
    )

    if not service.start_campaign(campaign_id):
        print("Error: Failed to start campaign")
        return 1

    return _monitor_campaign(service, campaign_id, 1)


def _get_provider_config(args) -> dict[str, Any]:
    """Extract provider-specific configuration from CLI arguments.

    Args:
        args: Parsed CLI arguments

    Returns:
        Provider config dict with values from CLI or environment
    """
    provider_class = ProviderFactory.get_provider_class(args.provider)
    provider_config = {}

    # Extract provider-specific arguments
    for arg_spec in provider_class.get_arg_specs():
        arg_name = arg_spec.name
        value = vars(args).get(arg_name) or (os.getenv(arg_spec.env) if arg_spec.env else None)
        if value:
            provider_config[arg_name] = value

    return provider_config


def _monitor_campaign(service, campaign_id, total_targets):
    """Monitor campaign progress and display status updates.

    Args:
        service: SMSCampaignService instance
        campaign_id: Campaign ID to monitor
        total_targets: Total number of targets

    Returns:
        0 on success, 1 on failure
    """
    import time

    print("\nMonitoring campaign progress...")
    last_log_count = 0

    try:
        while True:
            status = service.get_campaign_logs(campaign_id)
            if not status:
                print("Error: Campaign not found")
                return 1

            campaign_status = status.get('status')
            sms_sent = status.get('sms_sent', 0)
            logs = status.get('logs', [])

            if len(logs) > last_log_count:
                for log in logs[last_log_count:]:
                    timestamp = log.get('timestamp', '')
                    message = log.get('message', '')
                    print(f"  [{timestamp}] {message}")
                last_log_count = len(logs)

            if campaign_status in ['completed', 'failed', 'stopped']:
                print(f"\nCampaign {campaign_status}")
                print(f"SMS sent: {sms_sent}/{total_targets}")
                return 0 if campaign_status == 'completed' else 1

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Stopping campaign...")
        service.stop_campaign(campaign_id)
        print("Campaign stopped.")
        return 1
