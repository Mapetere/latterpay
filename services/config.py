"""
Configuration Module for LatterPay
===================================
Centralized configuration management with:
- Environment variable handling
- Feature flags
- Payment gateway configuration
- Donation types and menus

Author: Nyasha Mapetere
Version: 2.1.0
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION CLASSES
# ============================================================================

@dataclass
class WhatsAppConfig:
    """WhatsApp API configuration."""
    access_token: str = field(default_factory=lambda: os.getenv("WHATSAPP_TOKEN", ""))
    phone_number_id: str = field(default_factory=lambda: os.getenv("PHONE_NUMBER_ID", ""))
    verify_token: str = field(default_factory=lambda: os.getenv("VERIFY_TOKEN", ""))
    bot_number: str = field(default_factory=lambda: os.getenv("WHATSAPP_BOT_NUMBER", ""))
    api_version: str = "v18.0"
    
    @property
    def api_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"


@dataclass
class PaynowConfig:
    """Paynow payment gateway configuration."""
    # ZWG (local currency) integration
    zwg_integration_id: str = field(default_factory=lambda: os.getenv("PAYNOW_ZWG_ID", "21227"))
    zwg_integration_key: str = field(default_factory=lambda: os.getenv("PAYNOW_ZWG_KEY", ""))
    
    # USD integration
    usd_integration_id: str = field(default_factory=lambda: os.getenv("PAYNOW_USD_ID", "21116"))
    usd_integration_key: str = field(default_factory=lambda: os.getenv("PAYNOW_USD_KEY", ""))
    
    # URLs
    return_url: str = field(default_factory=lambda: os.getenv(
        "PAYNOW_RETURN_URL", 
        "https://latterpay-production.up.railway.app/payment-return"
    ))
    result_url: str = field(default_factory=lambda: os.getenv(
        "PAYNOW_RESULT_URL",
        "https://latterpay-production.up.railway.app/payment-result"
    ))
    
    # Payment limits
    max_amount: float = 480.0
    min_amount: float = 1.0
    
    def get_integration(self, currency: str = "ZWG") -> tuple:
        """Get integration ID and key for currency."""
        if currency.upper() == "USD":
            return self.usd_integration_id, self.usd_integration_key
        return self.zwg_integration_id, self.zwg_integration_key


@dataclass
class SecurityConfig:
    """Security-related configuration."""
    meta_app_secret: str = field(default_factory=lambda: os.getenv("META_APP_SECRET", ""))
    private_key_passphrase: str = field(default_factory=lambda: os.getenv("PRIVATE_KEY_PASSPHRASE", ""))
    flask_secret_key: str = field(default_factory=lambda: os.getenv("FLASK_SECRET_KEY", ""))
    
    # Rate limiting
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    
    # Session
    session_timeout_minutes: int = 5
    session_warning_minutes: int = 4


@dataclass
class AdminConfig:
    """Admin and notification configuration."""
    admin_phone: str = field(default_factory=lambda: os.getenv("ADMIN_PHONE", ""))
    finance_phone: str = field(default_factory=lambda: os.getenv("FINANCE_PHONE", ""))
    notification_email: str = field(default_factory=lambda: os.getenv("NOTIFICATION_EMAIL", ""))
    
    @property
    def admin_phones(self) -> List[str]:
        """Get list of admin phone numbers."""
        phones = [self.admin_phone, self.finance_phone]
        return [p for p in phones if p]
    
    def is_admin(self, phone: str) -> bool:
        """Check if phone number is an admin."""
        return phone in self.admin_phones


@dataclass  
class FeatureFlags:
    """Feature toggles for the application."""
    enable_registration: bool = field(default_factory=lambda: 
        os.getenv("ENABLE_REGISTRATION", "true").lower() == "true")
    enable_donations: bool = field(default_factory=lambda:
        os.getenv("ENABLE_DONATIONS", "true").lower() == "true")
    enable_meta_flows: bool = field(default_factory=lambda:
        os.getenv("ENABLE_META_FLOWS", "true").lower() == "true")
    enable_webhook_verification: bool = field(default_factory=lambda:
        os.getenv("ENABLE_WEBHOOK_VERIFICATION", "false").lower() == "true")
    debug_mode: bool = field(default_factory=lambda:
        os.getenv("DEBUG", "false").lower() == "true")


# ============================================================================
# DONATION CONFIGURATION
# ============================================================================

class DonationConfig:
    """Configuration for donation types and menus."""
    
    # Default donation types
    DEFAULT_DONATION_TYPES = [
        "Monthly Contributions",
        "August Conference", 
        "Youth Conference",
        "Construction Contribution",
        "Pastoral Support",
        "Other"
    ]
    
    def __init__(self):
        self._types = self.DEFAULT_DONATION_TYPES.copy()
        self._load_custom_types()
    
    def _load_custom_types(self):
        """Load custom donation types from file."""
        try:
            import json
            if os.path.exists(CUSTOM_TYPES_FILE):
                with open(CUSTOM_TYPES_FILE, 'r') as f:
                    custom = json.load(f)
                    if isinstance(custom, list):
                        # Insert custom types before "Other"
                        for t in custom:
                            if t not in self._types:
                                self._types.insert(-1, t)
        except Exception as e:
            logger.warning(f"Failed to load custom donation types: {e}")
    
    @property
    def types(self) -> List[str]:
        """Get all donation types."""
        return self._types
    
    def get_menu(self) -> str:
        """Generate formatted menu string."""
        lines = []
        for i, dtype in enumerate(self._types, 1):
            lines.append(f"*{i}.* {dtype}")
        return "\n".join(lines)
    
    def get_type_by_index(self, index: int) -> Optional[str]:
        """Get donation type by 1-based index."""
        if 1 <= index <= len(self._types):
            return self._types[index - 1]
        return None
    
    def is_valid_choice(self, choice: str) -> bool:
        """Check if choice is a valid donation type index."""
        try:
            index = int(choice)
            return 1 <= index <= len(self._types)
        except ValueError:
            return False
    
    def add_custom_type(self, dtype: str) -> bool:
        """Add a custom donation type."""
        if dtype and dtype not in self._types:
            self._types.insert(-1, dtype)  # Before "Other"
            self._save_custom_types()
            return True
        return False
    
    def _save_custom_types(self):
        """Save custom types to file."""
        try:
            import json
            custom = [t for t in self._types if t not in self.DEFAULT_DONATION_TYPES]
            with open(CUSTOM_TYPES_FILE, 'w') as f:
                json.dump(custom, f)
        except Exception as e:
            logger.error(f"Failed to save custom donation types: {e}")


# ============================================================================
# PAYMENT METHOD CONFIGURATION
# ============================================================================

class PaymentMethodConfig:
    """Configuration for payment methods."""
    
    PAYMENT_METHODS = {
        "1": {"name": "EcoCash", "code": "ecocash", "emoji": "📱"},
        "2": {"name": "OneMoney", "code": "onemoney", "emoji": "📱"},
        "3": {"name": "TeleCash", "code": "telecash", "emoji": "📱"},
        "4": {"name": "USD Transfer", "code": "usd", "emoji": "💵"},
    }
    
    CURRENCIES = {
        "1": {"name": "USD", "symbol": "$", "code": "USD"},
        "2": {"name": "ZWG", "symbol": "ZWG", "code": "ZWG"},
    }
    
    @classmethod
    def get_method(cls, choice: str) -> Optional[Dict]:
        """Get payment method by choice number."""
        return cls.PAYMENT_METHODS.get(choice)
    
    @classmethod
    def get_currency(cls, choice: str) -> Optional[Dict]:
        """Get currency by choice number."""
        return cls.CURRENCIES.get(choice)
    
    @classmethod
    def get_methods_menu(cls) -> str:
        """Generate payment methods menu."""
        lines = []
        for key, method in cls.PAYMENT_METHODS.items():
            lines.append(f"*{key}.* {method['name']} {method['emoji']}")
        return "\n".join(lines)
    
    @classmethod
    def get_currency_menu(cls) -> str:
        """Generate currency selection menu."""
        lines = []
        for key, currency in cls.CURRENCIES.items():
            lines.append(f"*{key}.* {currency['name']}")
        return "\n".join(lines)


# ============================================================================
# FILE PATHS
# ============================================================================

# Data files
CUSTOM_TYPES_FILE = "custom_donation_types.json"
PAYMENTS_FILE = "donation_payment.json"
DATABASE_FILE = "botdata.db"

# Key files
PRIVATE_KEY_FILE = "private.pem"
PUBLIC_KEY_FILE = "public.pem"

# Log directory
LOG_DIR = "logs"


# ============================================================================
# GLOBAL CONFIGURATION INSTANCES
# ============================================================================

# Initialize configurations
whatsapp_config = WhatsAppConfig()
paynow_config = PaynowConfig()
security_config = SecurityConfig()
admin_config = AdminConfig()
feature_flags = FeatureFlags()
donation_config = DonationConfig()
payment_method_config = PaymentMethodConfig()


# ============================================================================
# LEGACY COMPATIBILITY EXPORTS
# ============================================================================

# These maintain backward compatibility with existing code
finance_phone = admin_config.finance_phone
access_token = whatsapp_config.access_token
phone_number_id = whatsapp_config.phone_number_id
admin_phone = admin_config.admin_phone
donation_types = donation_config.types

# Legacy menu format
menu = [
    "1. *Monthly Contributions*",
    "2. *August Conference*",
    "3. *Youth Conference*",
    "4. *Construction Contribution*",
    "5. *Pastoral Support*",
    "6. *Other*"
]


# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_config() -> Dict[str, List[str]]:
    """
    Validate configuration and return any warnings/errors.
    
    Returns:
        Dictionary with 'errors' and 'warnings' lists
    """
    errors = []
    warnings = []
    
    # Check required WhatsApp config
    if not whatsapp_config.access_token:
        errors.append("WHATSAPP_TOKEN not configured")
    if not whatsapp_config.phone_number_id:
        errors.append("PHONE_NUMBER_ID not configured")
    if not whatsapp_config.verify_token:
        warnings.append("VERIFY_TOKEN not configured - webhook verification disabled")
    
    # Check Paynow config
    if not paynow_config.zwg_integration_key:
        warnings.append("PAYNOW_ZWG_KEY not configured - ZWG payments may fail")
    if not paynow_config.usd_integration_key:
        warnings.append("PAYNOW_USD_KEY not configured - USD payments may fail")
    
    # Check security config
    if not security_config.meta_app_secret:
        warnings.append("META_APP_SECRET not configured - signature verification disabled")
    if not security_config.flask_secret_key:
        warnings.append("FLASK_SECRET_KEY not configured - using random key")
    
    # Check admin config
    if not admin_config.admin_phone:
        warnings.append("ADMIN_PHONE not configured - admin features limited")
    
    return {
        "errors": errors,
        "warnings": warnings
    }


def print_config_status():
    """Print configuration status to logs."""
    result = validate_config()
    
    for error in result['errors']:
        logger.error(f"Config Error: {error}")
    
    for warning in result['warnings']:
        logger.warning(f"Config Warning: {warning}")
    
    if not result['errors']:
        logger.info("Configuration validation passed")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Configuration classes
    'WhatsAppConfig',
    'PaynowConfig', 
    'SecurityConfig',
    'AdminConfig',
    'FeatureFlags',
    'DonationConfig',
    'PaymentMethodConfig',
    
    # Configuration instances
    'whatsapp_config',
    'paynow_config',
    'security_config', 
    'admin_config',
    'feature_flags',
    'donation_config',
    'payment_method_config',
    
    # File paths
    'CUSTOM_TYPES_FILE',
    'PAYMENTS_FILE',
    'DATABASE_FILE',
    'PRIVATE_KEY_FILE',
    'PUBLIC_KEY_FILE',
    'LOG_DIR',
    
    # Legacy exports
    'finance_phone',
    'access_token',
    'phone_number_id',
    'admin_phone',
    'donation_types',
    'menu',
    
    # Utilities
    'validate_config',
    'print_config_status',
]
