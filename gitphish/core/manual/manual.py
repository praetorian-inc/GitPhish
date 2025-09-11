import logging
from gitphish.config.auth import GitHubAuthConfig
from gitphish.core.clients.auth.github_oauth_client import GitHubDeviceAuth
from gitphish.core.common.file import TokenStorageManager

logger = logging.getLogger(__name__)


class ManualDeviceAuth:
    """Manual device code authentication handler."""

    def __init__(self):
        self.auth_client = None

    def run_manual_device_code_flow(
        self, client_id: str, org_name: str, email: str = None, skip_wait: bool = False
    ) -> dict:
        print("\n🎯 Starting Manual GitHub Device Code Authentication")
        print("=" * 50)
        print(f"Client ID: {client_id}")
        print(f"Organization: {org_name}")
        print("=" * 50)

        config = GitHubAuthConfig(client_id=client_id, org_name=org_name)
        self.auth_client = GitHubDeviceAuth(config)

        try:
            print("\n📱 Step 1: Initiating device flow...")
            device_flow = self.auth_client.initiate_device_flow()

            print("✅ Device flow initiated!")
            print(f"   User Code: {device_flow['user_code']}")
            print(
                f"   Verification URI: "
                f"{device_flow.get('verification_uri', 'https://github.com/login/device')}"
            )
            print(
                f"   Expires in: " f"{device_flow.get('expires_in', 'Unknown')} seconds"
            )

            print("\n👤 Step 2: Complete authorization")
            print("=" * 50)
            print(
                f"1. Open: "
                f"{device_flow.get('verification_uri', 'https://github.com/login/device')}"
            )
            print(f"2. Enter code: {device_flow['user_code']}")
            print("3. Complete the authorization")
            print("=" * 50)

            if skip_wait:
                print("\n⏭️  Skipping token polling as requested (--skip-wait)")
                print(f"   Device code: {device_flow['device_code']}")
                return device_flow

            print("\n🔄 Step 3: Polling for access token (starting immediately)...")
            access_token = self.auth_client.poll_for_token(
                device_flow["device_code"], 5, email or ""
            )

            if access_token:
                print("\n🎉 SUCCESS! Authentication completed!")
                print(f"   Access token: {access_token[:20]}...")
                self.save_access_token(access_token, email)
                device_flow["access_token"] = access_token
                return device_flow
            else:
                print("\n❌ Authentication failed or timed out")
                return {"error": "Authentication failed or timed out"}

        except Exception as e:
            print(f"\n❌ Error during authentication: {str(e)}")
            return {"error": str(e)}
        finally:
            if self.auth_client:
                self.auth_client.close()

    def save_access_token(self, token: str, email: str = None):
        filename = TokenStorageManager.save_token_simple(token, email)
        print(f"💾 Token saved to: {filename}")

    def poll_for_token_only(
        self, client_id: str, org_name: str, device_code: str, email: str = None
    ) -> bool:
        print("\n🔄 Polling for access token using provided device code...")
        config = GitHubAuthConfig(client_id=client_id, org_name=org_name)
        self.auth_client = GitHubDeviceAuth(config)
        try:
            access_token = self.auth_client.poll_for_token(device_code, 5, email or "")
            if access_token:
                print("\n🎉 SUCCESS! Authentication completed!")
                print(f"   Access token: {access_token[:20]}...")
                self.save_access_token(access_token, email)
                return True
            else:
                print("\n❌ Authentication failed or timed out")
                return False
        except Exception as e:
            print(f"\n❌ Error during polling: {str(e)}")
            return False
        finally:
            if self.auth_client:
                self.auth_client.close()
