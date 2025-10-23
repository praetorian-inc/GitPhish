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
    platform = Column(String, nullable=False, default='github')
    provider = Column(String, nullable=False)  # 'twilio' or 'aws'
    
    # Campaign configuration
    config = Column(JSON)  # Stores provider-specific config
    target_method = Column(String, nullable=False)  # 'single' or 'file'
    targets = Column(JSON)  # List of target emails/phones
    message_template = Column(Text)
    oauth_scope = Column(String, default='repo user')
    
    # Campaign state
    status = Column(String, default='pending')  # pending, running, completed, failed, stopped
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Campaign statistics
    sms_sent = Column(Integer, default=0)
    tokens_captured = Column(Integer, default=0)
    
    # Campaign logs and results
    logs = Column(Text, default='')
    captured_tokens = Column(JSON, default=list)
    
    # Optional settings
    encryption_key = Column(String, nullable=True)
    proxy_url = Column(String, nullable=True)
    debug_mode = Column(Boolean, default=False)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert campaign to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'name': self.name,
            'platform': self.platform,
            'provider': self.provider,
            'target_method': self.target_method,
            'target_count': len(self.targets) if self.targets else 0,
            'status': self.status,
            'started': self.started_at.isoformat() if self.started_at else None,
            'created': self.created_at.isoformat() if self.created_at else None,
            'completed': self.completed_at.isoformat() if self.completed_at else None,
            'sms_sent': self.sms_sent,
            'tokens_captured': self.tokens_captured,
            'debug_mode': self.debug_mode
        }
    
    def add_log(self, message: str):
        """Add a log message to the campaign."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        log_entry = f"[{timestamp}] {message}\n"
        if self.logs:
            self.logs += log_entry
        else:
            self.logs = log_entry
    
    def add_captured_token(self, email: str, access_token: str, user_code: str = None):
        """Add a captured token to the campaign."""
        if not self.captured_tokens:
            self.captured_tokens = []
        
        token_data = {
            'email': email,
            'access_token': access_token,
            'user_code': user_code,
            'captured_at': datetime.now(timezone.utc).timestamp()
        }
        
        self.captured_tokens.append(token_data)
        self.tokens_captured = len(self.captured_tokens)
    
    def get_runtime(self) -> str:
        """Get human-readable runtime duration."""
        if not self.started_at:
            return '0s'
        
        end_time = self.completed_at or datetime.now(timezone.utc)
        duration = end_time - self.started_at
        
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