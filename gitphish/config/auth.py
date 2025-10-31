# config.py
from dataclasses import dataclass


@dataclass
class GitHubAuthConfig:
    """Configuration class for GitHub authentication."""

    client_id: str
    org_name: str
    base_url: str = "https://github.com"
    timeout: int = 900  # 15 minutes
    default_interval: int = 5
    scopes: str = (
        "repo workflow user gist notifications read:org read:public_key read:repo_hook "
        "read:user read:discussion"
    )
    max_concurrent_auths: int = 10
