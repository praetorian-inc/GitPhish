"""
SMS Campaign model for GitPhish.
"""

import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Boolean, JSON
)
from sqlalchemy.orm import relationship
from gitphish.models.base import Base


class SMSCampaign(Base):
    """SMS Campaign database model."""
    
    __tablename__ = 'sms_campaigns'
    
    # Primary key
    id = Column(String, primary_key=True)
    
    # Campaign metadata
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False)  # 'twilio' or 'aws'
    
    # Campaign configuration
    config = Column(JSON)  # Stores provider-specific config
    target_method = Column(String, nullable=False)  # 'single' or 'file'
    targets = Column(JSON)  # List of target emails/phones
    message_template = Column(Text)
    oauth_scope = Column(String, default='repo user gist notifications workflow read:org read:public_key read:repo_hook read:user read:discussion')
    client_id = Column(String, nullable=True)  # GitHub OAuth app client ID
    org_name = Column(String, nullable=True)  # Organization name for phishing messages
    
    # Campaign state
    status = Column(String, default='pending')  # pending, running, completed, failed, stopped
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Campaign statistics
    sms_sent = Column(Integer, default=0)
    tokens_captured = Column(Integer, default=0)

    # Campaign logs
    logs = Column(Text, default='')

    # Optional settings
    skip_wait = Column(Boolean, default=False)  # Skip OAuth token polling
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert campaign to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'name': self.name,
            'provider': self.provider,
            'target_method': self.target_method,
            'target_count': len(self.targets) if self.targets else 0,
            'status': self.status,
            'started': self.started_at.isoformat() if self.started_at else None,
            'created': self.created_at.isoformat() if self.created_at else None,
            'completed': self.completed_at.isoformat() if self.completed_at else None,
            'sms_sent': self.sms_sent,
            'tokens_captured': self.tokens_captured
        }
    
    def add_log(self, message: str):
        """Add a log message to the campaign."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        log_entry = f"[{timestamp}] {message}\n"
        if self.logs:
            self.logs += log_entry
        else:
            self.logs = log_entry

    def get_runtime(self) -> str:
        """Get human-readable runtime duration."""
        if not self.started_at:
            return '0s'

        end_time = self.completed_at or datetime.now(timezone.utc)

        # Ensure both datetimes are timezone-aware for comparison
        start_time = self.started_at
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        duration = end_time - start_time
        
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"