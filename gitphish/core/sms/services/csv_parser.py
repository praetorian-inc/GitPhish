"""
CSV Target Parser
Single job: Parse and validate CSV data containing email,phone target pairs
"""

import csv
import io
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class CSVTargetParser:
    """Handles parsing and validation of CSV target data."""
    
    def __init__(self):
        pass
    
    def parse_csv_data(self, csv_data: str) -> List[Tuple[str, str]]:
        """Parse CSV data and extract email,phone pairs."""
        targets = []
        
        try:
            csv_file = io.StringIO(csv_data)
            reader = csv.reader(csv_file)
            
            for row_num, row in enumerate(reader, 1):
                if len(row) >= 2:
                    email = row[0].strip()
                    phone = row[1].strip()
                    
                    if self._validate_target_pair(email, phone, row_num):
                        targets.append((email, phone))
                else:
                    logger.warning(f"Row {row_num}: Insufficient columns (need at least 2: email, phone)")
                    
        except Exception as e:
            logger.error(f"CSV parsing error: {e}")
            
        return targets
    
    def _validate_target_pair(self, email: str, phone: str, row_num: int) -> bool:
        """Validate a single email,phone target pair."""
        if not email or not phone:
            logger.warning(f"Row {row_num}: Empty email or phone")
            return False
        
        if not self._validate_email(email):
            logger.warning(f"Row {row_num}: Invalid email format: {email}")
            return False
        
        if not self._validate_phone(phone):
            logger.warning(f"Row {row_num}: Invalid phone format: {phone}")
            return False
        
        return True
    
    def _validate_email(self, email: str) -> bool:
        """Basic email validation."""
        return '@' in email and '.' in email.split('@')[-1]
    
    def _validate_phone(self, phone: str) -> bool:
        """Basic phone validation - allow various formats."""
        cleaned_phone = phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
        return cleaned_phone.isdigit() and len(cleaned_phone) >= 10
    
    def get_validation_summary(self, csv_data: str) -> dict:
        """Get validation summary without parsing."""
        try:
            csv_file = io.StringIO(csv_data)
            reader = csv.reader(csv_file)
            
            total_rows = 0
            valid_rows = 0
            errors = []
            
            for row_num, row in enumerate(reader, 1):
                total_rows += 1
                
                if len(row) < 2:
                    errors.append(f"Row {row_num}: Insufficient columns")
                    continue
                
                email = row[0].strip()
                phone = row[1].strip()
                
                if not email or not phone:
                    errors.append(f"Row {row_num}: Empty email or phone")
                    continue
                
                if not self._validate_email(email):
                    errors.append(f"Row {row_num}: Invalid email: {email}")
                    continue
                
                if not self._validate_phone(phone):
                    errors.append(f"Row {row_num}: Invalid phone: {phone}")
                    continue
                
                valid_rows += 1
            
            return {
                'total_rows': total_rows,
                'valid_rows': valid_rows,
                'invalid_rows': total_rows - valid_rows,
                'errors': errors,
                'success_rate': (valid_rows / total_rows * 100) if total_rows > 0 else 0
            }
            
        except Exception as e:
            return {
                'total_rows': 0,
                'valid_rows': 0,
                'invalid_rows': 0,
                'errors': [f"CSV parsing failed: {e}"],
                'success_rate': 0
            }