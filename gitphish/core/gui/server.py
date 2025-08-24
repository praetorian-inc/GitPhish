"""
Streamlined web-based admin interface for GitPhish.
"""

import os
import logging
from flask import Flask, render_template
from flask_cors import CORS

from gitphish.core.deployment.services.deployment_service import (
    DeploymentService,
)
from gitphish.core.accounts.services.deployer_service import (
    DeployerGitHubAccountService,
)
from gitphish.core.accounts.services.compromised_service import (
    CompromisedGitHubAccountService,
)
from gitphish.core.gui.api.accounts_api import AccountsAPI
from gitphish.core.gui.api.deployment_api import DeploymentAPI
from gitphish.core.gui.api.server_control_api import (
    ServerControlAPI,
)
from gitphish.core.gui.api.sms_campaigns_api import SMSCampaignsAPI


class GitPhishGuiServer:
    """Web-based GUI interface for GitPhish."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = Flask(
            __name__,
            template_folder=os.path.join(
                os.path.dirname(__file__),
                "templates",
            ),
        )
        self.app.secret_key = os.urandom(24)

        # Configure CORS
        CORS(self.app)

        # Initialize services
        self.deployment_service = DeploymentService()
        self.github_account_service = DeployerGitHubAccountService()
        self.compromised_account_service = CompromisedGitHubAccountService()

        # Setup page routes
        self._setup_page_routes()

        # Initialize API modules
        self.accounts_api = AccountsAPI(
            self.app,
            self.github_account_service,
            self.compromised_account_service,
        )
        self.deployment_api = DeploymentAPI(
            self.app,
            self.deployment_service,
            self.github_account_service,
        )
        self.server_control_api = ServerControlAPI(self.app)
        self.sms_campaigns_api = SMSCampaignsAPI(
            self.app,
            self.github_account_service,
            self.compromised_account_service
        )

        # Configure logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _setup_page_routes(self):
        """Setup Flask routes for web pages."""

        @self.app.route("/")
        def gui():
            """Main GUI page."""
            # Use ServerControlAPI's _get_gui_stats for unified stats
            stats = self.server_control_api._get_gui_stats()
            return render_template("dashboard.html", stats=stats)

        @self.app.route("/config")
        def config_page():
            """Configuration page."""
            return render_template("config.html")

        @self.app.route("/deploy")
        def deploy_management():
            """Deploy management page - combines full deployment functionality."""
            return render_template("deploy_management.html")

        @self.app.route("/auth")
        def auth_server():
            """Authentication server management page."""
            server_status = self.server_control_api.get_server_status()
            return render_template("auth_server.html", server_status=server_status)

        @self.app.route("/sms-campaigns")
        def sms_campaigns():
            """SMS campaigns management page."""
            return render_template("sms_campaigns.html")

        # Legacy routes - keeping for backward compatibility
        @self.app.route("/server-control")
        def server_control():
            """Server control panel - redirect to auth server."""
            return render_template(
                "auth_server.html",
                server_status=self.server_control_api.get_server_status(),
            )

        @self.app.route("/logs")
        def logs_page():
            """Logs and monitoring page."""
            return render_template("logs.html")

        @self.app.route("/github-pages")
        def github_pages():
            """GitHub Pages deployment management page."""
            deployments = self.deployment_api._get_deployment_status_from_db()
            return render_template("github_pages.html", deployments=deployments)

        @self.app.route("/github-accounts")
        def github_accounts():
            """GitHub accounts management page."""
            return render_template("github_accounts.html")

        @self.app.route("/compromised-accounts")
        def compromised_accounts():
            """Compromised accounts management page."""
            return render_template("compromised_accounts.html")

        @self.app.route("/health")
        def health_check():
            """Health check endpoint."""
            return {"status": "healthy", "service": "GitPhish Admin Server"}

        @self.app.route("/server-management")
        def server_management():
            return render_template("server_management.html")

        @self.app.route("/deployments-management")
        def deployments_management():
            return render_template("deployments_management.html")

    def run(self, debug: bool = False):
        """Run the admin web server."""
        self.logger.debug(f"Starting GitPhish Admin Server on {self.host}:{self.port}")

        self.app.run(
            host=self.host,
            port=self.port,
            debug=debug,
            threaded=True,
        )
