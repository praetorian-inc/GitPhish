import argparse
import logging
import sys
import os

from gitphish.models.database import initialize_database
from gitphish.core.cli.server import setup_server_subparser
from gitphish.core.cli.gui import setup_gui_subparser
from gitphish.core.cli.deploy import setup_deploy_subparser
from gitphish.core.cli.manual import setup_manual_subparser
from gitphish.core.cli.postex import setup_postex_subparser
from gitphish.core.cli.sms_campaigns import setup_sms_campaigns_subparser, handle_sms_campaigns_command

GITPHISH_VERSION = "0.2.0"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Main execution function."""
    # Initialize database first - this should happen for all modes
    try:
        initialize_database()
        logger.debug("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        return 1

    parser = argparse.ArgumentParser(
        description="GitPhish - GitHub Phishing Assessment Tool"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"GitPhish {GITPHISH_VERSION}",
        help="Show program's version number and exit.",
    )

    # Global GitHub token option
    parser.add_argument(
        "--github-token",
        help="GitHub Personal Access Token (env: GITHUB_DEPLOY_TOKEN)",
    )

    # Subcommands for different modes
    subparsers = parser.add_subparsers(dest="mode", help="Operation modes")

    setup_gui_subparser(subparsers)
    setup_deploy_subparser(subparsers)
    setup_server_subparser(subparsers)
    setup_manual_subparser(subparsers)
    setup_postex_subparser(subparsers)
    setup_sms_campaigns_subparser(subparsers)

    parser.set_defaults(func=lambda args: parser.print_help())

    args = parser.parse_args()
    args._parser = parser

    # Centralize token resolution
    args.github_token = args.github_token or os.getenv("GITHUB_DEPLOY_TOKEN")

    sys.exit(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
