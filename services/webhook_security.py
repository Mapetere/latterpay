"""
Webhook Security Module for LatterPay
======================================
Provides webhook signature verification for:
- Meta/WhatsApp webhook validation
- Paynow IPN (Instant Payment Notification) validation

Author: Nyasha Mapetere
Version: 2.1.0
"""

import hmac
import hashlib
import logging
import os
from functools import wraps
from flask import request, abort, jsonify
from typing import Optional, Callable

logger = logging.getLogger(__name__)


# ============================================================================
# WEBHOOK SIGNATURE VERIFICATION
# ============================================================================

class WebhookSecurity:
    """
    Handles webhook signature verification for incoming requests.
    """
    
    def __init__(self):
        self.app_secret = os.getenv("META_APP_SECRET", "")
        self.paynow_secret = os.getenv("PAYNOW_SECRET", "")
    
    def verify_meta_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify Meta/WhatsApp webhook signature.
        
        The signature is provided in the X-Hub-Signature-256 header.
        It's computed as HMAC-SHA256 of the payload using the app secret.
        
        Args:
            payload: Raw request body bytes
            signature: Signature from X-Hub-Signature-256 header
            
        Returns:
            True if signature is valid
        """
        if not self.app_secret:
            logger.warning("META_APP_SECRET not configured, skipping signature verification")
            return True  # Skip verification if secret not configured
        
        if not signature:
            logger.warning("No signature provided in request")
            return False
        
        try:
            # Remove 'sha256=' prefix if present
            if signature.startswith('sha256='):
                signature = signature[7:]
            
            # Calculate expected signature
            expected = hmac.new(
                self.app_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Use constant-time comparison to prevent timing attacks
            is_valid = hmac.compare_digest(expected, signature)
            
            if not is_valid:
                logger.warning("Invalid webhook signature")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False
    
    def verify_paynow_signature(self, data: dict, signature: str) -> bool:
        """
        Verify Paynow IPN signature.
        
        Paynow uses a hash of sorted parameters.
        
        Args:
            data: IPN data dictionary
            signature: Hash from Paynow
            
        Returns:
            True if signature is valid
        """
        if not self.paynow_secret:
            logger.warning("PAYNOW_SECRET not configured, skipping verification")
            return True
        
        if not signature:
            return False
        
        try:
            # Build hash string from sorted parameters
            # Exclude the hash itself
            params = {k: v for k, v in data.items() if k.lower() != 'hash'}
            
            # Sort and concatenate
            sorted_params = sorted(params.items())
            to_hash = ''.join([str(v) for k, v in sorted_params])
            to_hash += self.paynow_secret
            
            # Calculate hash
            expected = hashlib.sha512(to_hash.encode('utf-8')).hexdigest().upper()
            
            return hmac.compare_digest(expected, signature.upper())
            
        except Exception as e:
            logger.error(f"Paynow signature verification error: {e}")
            return False


# ============================================================================
# DECORATOR FOR ROUTE PROTECTION
# ============================================================================

webhook_security = WebhookSecurity()


def require_webhook_signature(func: Callable) -> Callable:
    """
    Decorator to require valid webhook signature.
    
    Usage:
        @app.route('/webhook', methods=['POST'])
        @require_webhook_signature
        def webhook():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if request.method == 'POST':
            signature = request.headers.get('X-Hub-Signature-256', '')
            payload = request.get_data()
            
            if not webhook_security.verify_meta_signature(payload, signature):
                logger.warning(f"Rejected request with invalid signature from {request.remote_addr}")
                return jsonify({
                    "status": "error",
                    "message": "Invalid signature"
                }), 401
        
        return func(*args, **kwargs)
    return wrapper


def require_paynow_signature(func: Callable) -> Callable:
    """
    Decorator to require valid Paynow IPN signature.
    
    Usage:
        @app.route('/payment-result', methods=['POST'])
        @require_paynow_signature
        def payment_result():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            data = request.form.to_dict() or request.get_json() or {}
            signature = data.get('hash', '') or data.get('Hash', '')
            
            if not webhook_security.verify_paynow_signature(data, signature):
                logger.warning(f"Rejected Paynow IPN with invalid signature")
                return "INVALID SIGNATURE", 401
        except Exception as e:
            logger.error(f"Error processing Paynow signature: {e}")
            # Allow through if we can't parse - Paynow might send different formats
            pass
        
        return func(*args, **kwargs)
    return wrapper


# ============================================================================
# REQUEST VALIDATION
# ============================================================================

class RequestValidator:
    """
    Validate incoming request data for security and correctness.
    """
    
    # Maximum sizes for validation
    MAX_MESSAGE_LENGTH = 4096
    MAX_NAME_LENGTH = 100
    MAX_NOTE_LENGTH = 500
    
    @staticmethod
    def validate_webhook_payload(data: dict) -> tuple[bool, str]:
        """
        Validate webhook payload structure.
        
        Args:
            data: Incoming webhook data
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(data, dict):
            return False, "Invalid payload format"
        
        # Check for required WhatsApp structure
        if 'entry' in data:
            try:
                entry = data['entry'][0]
                changes = entry.get('changes', [{}])[0]
                value = changes.get('value', {})
                
                # Check for valid message structure
                if 'messages' in value:
                    messages = value['messages']
                    if not isinstance(messages, list):
                        return False, "Invalid messages format"
                    
                    for msg in messages:
                        if not isinstance(msg, dict):
                            return False, "Invalid message format"
                        
                        # Validate message ID
                        if not msg.get('id'):
                            return False, "Missing message ID"
                        
                        # Validate sender
                        if not msg.get('from'):
                            return False, "Missing sender"
                
                return True, ""
                
            except (IndexError, KeyError, TypeError) as e:
                return False, f"Malformed payload: {str(e)}"
        
        # Check for encrypted flow data
        if 'encrypted_flow_data' in data:
            required_fields = ['encrypted_flow_data', 'encrypted_aes_key', 'initial_vector']
            missing = [f for f in required_fields if not data.get(f)]
            if missing:
                return False, f"Missing fields: {', '.join(missing)}"
            return True, ""
        
        # Unknown but valid payload
        return True, ""
    
    @staticmethod
    def sanitize_user_input(text: str, max_length: int = None) -> str:
        """
        Sanitize user input text.
        
        Args:
            text: Raw user input
            max_length: Optional maximum length
            
        Returns:
            Sanitized text
        """
        if not text:
            return ""
        
        # Convert to string if needed
        text = str(text)
        
        # Remove null bytes and control characters (except newlines/tabs)
        text = ''.join(
            char for char in text 
            if char >= ' ' or char in '\n\t'
        )
        
        # Normalize whitespace
        text = ' '.join(text.split())
        
        # Apply length limit
        if max_length:
            text = text[:max_length]
        
        return text.strip()
    
    @staticmethod
    def validate_phone_number(phone: str) -> tuple[bool, str, str]:
        """
        Validate and normalize phone number.
        
        Args:
            phone: Raw phone number input
            
        Returns:
            Tuple of (is_valid, normalized_phone, error_message)
        """
        if not phone:
            return False, "", "Phone number is required"
        
        # Remove all non-digit characters
        digits = ''.join(c for c in phone if c.isdigit())
        
        # Validate length
        if len(digits) < 9 or len(digits) > 15:
            return False, "", "Invalid phone number length"
        
        # Normalize Zimbabwe numbers
        if digits.startswith('0') and len(digits) == 10:
            # Local format: 0771234567 -> 263771234567
            normalized = '263' + digits[1:]
        elif digits.startswith('263') and len(digits) == 12:
            # Already international
            normalized = digits
        elif digits.startswith('7') and len(digits) == 9:
            # Short format: 771234567 -> 263771234567
            normalized = '263' + digits
        else:
            # Keep as-is for other countries
            normalized = digits
        
        return True, normalized, ""
    
    @staticmethod
    def validate_amount(amount_str: str, min_val: float = 0.01, 
                       max_val: float = 480) -> tuple[bool, float, str]:
        """
        Validate payment amount.
        
        Args:
            amount_str: Amount as string
            min_val: Minimum allowed amount
            max_val: Maximum allowed amount
            
        Returns:
            Tuple of (is_valid, amount, error_message)
        """
        if not amount_str:
            return False, 0.0, "Amount is required"
        
        # Clean input
        amount_str = amount_str.strip().replace(',', '.')
        
        # Remove currency symbols
        for symbol in ['$', 'USD', 'ZWG', 'ZWL']:
            amount_str = amount_str.replace(symbol, '').strip()
        
        try:
            amount = float(amount_str)
            
            if amount < min_val:
                return False, 0.0, f"Amount must be at least {min_val}"
            
            if amount > max_val:
                return False, 0.0, f"Maximum amount is {max_val}"
            
            # Round to 2 decimal places
            amount = round(amount, 2)
            
            return True, amount, ""
            
        except ValueError:
            return False, 0.0, "Invalid amount format. Use numbers like 50 or 50.00"


# ============================================================================
# IP ALLOWLISTING (Optional)
# ============================================================================

class IPAllowlist:
    """
    Optional IP allowlisting for additional security.
    """
    
    # Meta/Facebook IP ranges (example - should be updated)
    META_IP_RANGES = [
        "66.220.144.0/20",
        "69.63.176.0/20",
        "69.171.224.0/19",
        "74.119.76.0/22",
        "103.4.96.0/22",
        "157.240.0.0/16",
        "173.252.64.0/18",
        "179.60.192.0/22",
        "185.60.216.0/22",
        "204.15.20.0/22",
    ]
    
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._allowed_ips = set()
        
        if enabled:
            self._load_allowed_ips()
    
    def _load_allowed_ips(self):
        """Load allowed IP addresses."""
        # Add Meta IP ranges
        # In production, you'd expand CIDR ranges
        pass
    
    def is_allowed(self, ip: str) -> bool:
        """
        Check if IP is allowed.
        
        Args:
            ip: IP address to check
            
        Returns:
            True if allowed (or if allowlisting is disabled)
        """
        if not self.enabled:
            return True
        
        # In development, always allow localhost
        if ip in ['127.0.0.1', 'localhost', '::1']:
            return True
        
        return ip in self._allowed_ips


# ============================================================================
# RATE LIMITING BY IP
# ============================================================================

class IPRateLimiter:
    """
    Simple IP-based rate limiter for webhook endpoints.
    """
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = {}
        self._lock = __import__('threading').Lock()
    
    def is_allowed(self, ip: str) -> bool:
        """
        Check if IP is within rate limits.
        
        Args:
            ip: IP address
            
        Returns:
            True if within limits
        """
        import time
        now = time.time()
        
        with self._lock:
            # Clean old entries
            self._requests = {
                k: v for k, v in self._requests.items()
                if now - v['window_start'] < self.window_seconds
            }
            
            if ip not in self._requests:
                self._requests[ip] = {
                    'count': 1,
                    'window_start': now
                }
                return True
            
            entry = self._requests[ip]
            
            # Check if window expired
            if now - entry['window_start'] >= self.window_seconds:
                entry['count'] = 1
                entry['window_start'] = now
                return True
            
            # Check if within limits
            if entry['count'] >= self.max_requests:
                return False
            
            entry['count'] += 1
            return True


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

request_validator = RequestValidator()
ip_rate_limiter = IPRateLimiter(max_requests=100, window_seconds=60)


__all__ = [
    'WebhookSecurity',
    'webhook_security',
    'require_webhook_signature',
    'require_paynow_signature',
    'RequestValidator',
    'request_validator',
    'IPAllowlist',
    'IPRateLimiter',
    'ip_rate_limiter',
]
