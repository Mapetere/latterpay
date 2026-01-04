"""
Smart Conversation Engine for LatterPay
========================================
AI-powered conversation handling with:
- Natural language understanding
- User memory & profile management
- Consolidated data collection
- Context-aware responses
- Intent detection

Author: Nyasha Mapetere
Version: 3.0.0
"""

import re
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# ============================================================================
# USER PROFILE & MEMORY
# ============================================================================

@dataclass
class UserProfile:
    """Persistent user profile for returning users."""
    phone: str
    name: str = ""
    congregation: str = ""
    email: str = ""
    preferred_currency: str = "ZWG"
    preferred_payment_method: str = "EcoCash"
    # Separate totals by currency
    total_usd: float = 0.0
    total_zwg: float = 0.0
    donation_count: int = 0
    last_donation_date: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    
    @property
    def total_donations(self) -> float:
        """Total across all currencies (for backward compatibility)."""
        return self.total_usd + self.total_zwg
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UserProfile':
        # Handle legacy 'total_donations' field
        if 'total_donations' in data and 'total_usd' not in data:
            # Migrate old data - assume it was ZWG
            data['total_zwg'] = data.pop('total_donations', 0)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class UserMemory:
    """Manages persistent user profiles and preferences.
    
    Automatically uses PostgreSQL when DATABASE_URL is set,
    falls back to SQLite otherwise.
    """
    
    def __init__(self, db_path: str = "botdata.db"):
        self.db_path = db_path
        self.use_postgres = False
        self.pg_pool = None
        self._init_db()
    
    def _init_db(self):
        """Initialize database connection and tables."""
        import os
        
        DATABASE_URL = os.getenv("DATABASE_URL")
        logger.info(f"DATABASE_URL found: {bool(DATABASE_URL)}")
        if DATABASE_URL:
            logger.info(f"DATABASE_URL starts with: {DATABASE_URL[:30]}...")
        
        if DATABASE_URL:
            try:
                import psycopg2
                from psycopg2 import pool
                
                # Fix Railway URL format
                db_url = DATABASE_URL
                if db_url.startswith("postgres://"):
                    db_url = db_url.replace("postgres://", "postgresql://", 1)
                
                self.pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, db_url)
                self.use_postgres = True
                logger.info("UserMemory: Successfully connected to PostgreSQL")
                
                # Ensure table exists
                conn = self.pg_pool.getconn()
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        phone TEXT PRIMARY KEY,
                        name TEXT,
                        congregation TEXT,
                        email TEXT,
                        preferred_currency TEXT DEFAULT 'ZWG',
                        preferred_payment_method TEXT DEFAULT 'EcoCash',
                        total_usd REAL DEFAULT 0,
                        total_zwg REAL DEFAULT 0,
                        donation_count INTEGER DEFAULT 0,
                        last_donation_date TEXT,
                        created_at TEXT,
                        last_seen TEXT
                    )
                """)
                conn.commit()
                self.pg_pool.putconn(conn)
                
            except Exception as e:
                logger.warning(f"PostgreSQL init failed, using SQLite: {e}")
                self.use_postgres = False
        
        if not self.use_postgres:
            # SQLite fallback
            logger.info("UserMemory: Using SQLite")
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        phone TEXT PRIMARY KEY,
                        name TEXT,
                        congregation TEXT,
                        email TEXT,
                        preferred_currency TEXT DEFAULT 'ZWG',
                        preferred_payment_method TEXT DEFAULT 'EcoCash',
                        total_usd REAL DEFAULT 0,
                        total_zwg REAL DEFAULT 0,
                        donation_count INTEGER DEFAULT 0,
                        last_donation_date TEXT,
                        created_at TEXT,
                        last_seen TEXT
                    )
                """)
                
                # Migrate old schema if needed
                try:
                    cursor.execute("ALTER TABLE user_profiles ADD COLUMN total_usd REAL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE user_profiles ADD COLUMN total_zwg REAL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to init user profiles table: {e}")
    
    def get_profile(self, phone: str) -> Optional[UserProfile]:
        """Get user profile by phone number."""
        try:
            if self.use_postgres and self.pg_pool:
                conn = self.pg_pool.getconn()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM user_profiles WHERE phone = %s", (phone,))
                    row = cursor.fetchone()
                    if row:
                        columns = [desc[0] for desc in cursor.description]
                        return UserProfile.from_dict(dict(zip(columns, row)))
                    return None
                finally:
                    self.pg_pool.putconn(conn)
            else:
                conn = sqlite3.connect(self.db_path, timeout=10)
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM user_profiles WHERE phone = ?", (phone,))
                row = cursor.fetchone()
                conn.close()
                
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    return UserProfile.from_dict(dict(zip(columns, row)))
                return None
        except Exception as e:
            logger.error(f"Failed to get profile for {phone}: {e}")
            return None
    
    def save_profile(self, profile: UserProfile):
        """Save or update user profile."""
        try:
            if self.use_postgres and self.pg_pool:
                conn = self.pg_pool.getconn()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO user_profiles 
                        (phone, name, congregation, email, preferred_currency, 
                         preferred_payment_method, total_usd, total_zwg, donation_count,
                         last_donation_date, created_at, last_seen)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (phone) DO UPDATE SET
                            name = EXCLUDED.name,
                            congregation = EXCLUDED.congregation,
                            email = EXCLUDED.email,
                            preferred_currency = EXCLUDED.preferred_currency,
                            preferred_payment_method = EXCLUDED.preferred_payment_method,
                            total_usd = EXCLUDED.total_usd,
                            total_zwg = EXCLUDED.total_zwg,
                            donation_count = EXCLUDED.donation_count,
                            last_donation_date = EXCLUDED.last_donation_date,
                            last_seen = EXCLUDED.last_seen
                    """, (
                        profile.phone, profile.name, profile.congregation, profile.email,
                        profile.preferred_currency, profile.preferred_payment_method,
                        profile.total_usd, profile.total_zwg, profile.donation_count,
                        profile.last_donation_date, profile.created_at,
                        datetime.now().isoformat()
                    ))
                    conn.commit()
                finally:
                    self.pg_pool.putconn(conn)
            else:
                conn = sqlite3.connect(self.db_path, timeout=10)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO user_profiles 
                    (phone, name, congregation, email, preferred_currency, 
                     preferred_payment_method, total_usd, total_zwg, donation_count,
                     last_donation_date, created_at, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    profile.phone, profile.name, profile.congregation, profile.email,
                    profile.preferred_currency, profile.preferred_payment_method,
                    profile.total_usd, profile.total_zwg, profile.donation_count,
                    profile.last_donation_date, profile.created_at,
                    datetime.now().isoformat()
                ))
                conn.commit()
                conn.close()
            logger.debug(f"Saved profile for {profile.phone}")
        except Exception as e:
            logger.error(f"Failed to save profile: {e}")
    
    def update_donation_stats(self, phone: str, amount: float, currency: str = "ZWG"):
        """Update user's donation statistics with currency-specific totals."""
        profile = self.get_profile(phone)
        if profile:
            if currency.upper() == "USD":
                profile.total_usd += amount
            else:
                profile.total_zwg += amount
            profile.donation_count += 1
            profile.last_donation_date = datetime.now().isoformat()
            self.save_profile(profile)
    
    def save_user_from_session(self, phone: str, session_data: dict):
        """Save or update user profile from session data."""
        logger.info(f"save_user_from_session called for {phone} with data: {session_data}")
        
        try:
            # Get existing profile or create new one
            profile = self.get_profile(phone)
            logger.info(f"Existing profile for {phone}: {profile}")
            
            if profile:
                # Update existing profile
                if session_data.get("name"):
                    profile.name = session_data["name"]
                if session_data.get("region"):
                    profile.congregation = session_data["region"]
                if session_data.get("currency"):
                    profile.preferred_currency = session_data["currency"]
                if session_data.get("payment_method"):
                    profile.preferred_payment_method = session_data["payment_method"]
                logger.info(f"Updated profile: {profile}")
            else:
                # Create new profile
                profile = UserProfile(
                    phone=phone,
                    name=session_data.get("name", ""),
                    congregation=session_data.get("region", ""),
                    preferred_currency=session_data.get("currency", "ZWG"),
                    preferred_payment_method=session_data.get("payment_method", "EcoCash"),
                    created_at=datetime.now().isoformat()
                )
                logger.info(f"Created new profile: {profile}")
            
            self.save_profile(profile)
            logger.info(f"Successfully saved profile for {phone}: name={profile.name}, congregation={profile.congregation}")
        except Exception as e:
            logger.error(f"Failed to save user from session: {e}", exc_info=True)


# ============================================================================
# NATURAL LANGUAGE UNDERSTANDING
# ============================================================================

@dataclass
class ParsedIntent:
    """Represents a parsed user intent."""
    intent: str  # donate, register, check_status, help, cancel, greeting, unknown
    confidence: float = 0.0
    entities: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


class NaturalLanguageEngine:
    """
    Lightweight NLU engine for understanding user messages.
    Extracts intents and entities without external APIs.
    """
    
    # Intent patterns (regex-based for speed)
    INTENT_PATTERNS = {
        'donate': [
            r'\b(donate|donation|pay|give|contribute|offering|tithe)\b',
            r'\b(send|transfer)\s+(money|funds|payment)\b',
            r'\$?\d+\.?\d*',  # Amount mentioned
        ],
        'register': [
            r'\b(register|signup|sign up|join|enroll|volunteer)\b',
        ],
        'check_status': [
            r'\b(check|status|confirm|verify|track)\b',
            r'\b(my payment|my donation)\b',
        ],
        'help': [
            r'\b(help|assist|support|how|what|guide)\b',
            r'\?$',
        ],
        'cancel': [
            r'\b(cancel|stop|quit|exit|abort|nevermind)\b',
        ],
        'greeting': [
            r'^(hi|hello|hey|good\s*(morning|afternoon|evening)|howzit|mhoro|salibonani)\b',
        ],
        'menu_choice': [
            r'^[1-9]$',  # Single digit for menu selection
        ],
    }
    
    # Entity extraction patterns
    ENTITY_PATTERNS = {
        'amount': r'\$?(\d+(?:\.\d{1,2})?)',
        'currency': r'\b(usd|zwg|dollars?|rtgs)\b',
        'phone': r'(?:0|\+?263)(\d{9})',
        'email': r'[\w\.-]+@[\w\.-]+\.\w+',
        'name': r'(?:my name is|i\'m|i am)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
        'purpose': r'(?:for|towards?)\s+(conference|construction|pastoral|monthly|youth|contribution)',
    }
    
    # Purpose keyword mapping
    PURPOSE_KEYWORDS = {
        'monthly': 'Monthly Contributions',
        'contribution': 'Monthly Contributions',
        'august': 'August Conference',
        'conference': 'August Conference',
        'youth': 'Youth Conference',
        'construction': 'Construction Contribution',
        'building': 'Construction Contribution',
        'pastoral': 'Pastoral Support',
        'pastor': 'Pastoral Support',
    }
    
    def parse(self, text: str) -> ParsedIntent:
        """Parse user message and extract intent + entities."""
        text_lower = text.lower().strip()
        
        # Detect intent
        intent, confidence = self._detect_intent(text_lower)
        
        # Extract entities
        entities = self._extract_entities(text_lower)
        
        return ParsedIntent(
            intent=intent,
            confidence=confidence,
            entities=entities,
            raw_text=text
        )
    
    def _detect_intent(self, text: str) -> Tuple[str, float]:
        """Detect the primary intent from text."""
        scores = {}
        
        for intent, patterns in self.INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    score += 1
            if score > 0:
                scores[intent] = score / len(patterns)
        
        if not scores:
            return 'unknown', 0.0
        
        best_intent = max(scores, key=scores.get)
        return best_intent, scores[best_intent]
    
    def _extract_entities(self, text: str) -> Dict[str, Any]:
        """Extract entities from text."""
        entities = {}
        
        # Amount
        amount_match = re.search(self.ENTITY_PATTERNS['amount'], text)
        if amount_match:
            try:
                entities['amount'] = float(amount_match.group(1))
            except ValueError:
                pass
        
        # Currency
        currency_match = re.search(self.ENTITY_PATTERNS['currency'], text, re.IGNORECASE)
        if currency_match:
            curr = currency_match.group(1).lower()
            entities['currency'] = 'USD' if curr in ['usd', 'dollar', 'dollars'] else 'ZWG'
        
        # Phone
        phone_match = re.search(self.ENTITY_PATTERNS['phone'], text)
        if phone_match:
            entities['phone'] = '263' + phone_match.group(1)
        
        # Email
        email_match = re.search(self.ENTITY_PATTERNS['email'], text)
        if email_match:
            entities['email'] = email_match.group(0)
        
        # Name
        name_match = re.search(self.ENTITY_PATTERNS['name'], text, re.IGNORECASE)
        if name_match:
            entities['name'] = name_match.group(1).title()
        
        # Donation purpose
        for keyword, purpose in self.PURPOSE_KEYWORDS.items():
            if keyword in text:
                entities['donation_type'] = purpose
                break
        
        return entities


# ============================================================================
# SMART CONVERSATION FLOW
# ============================================================================

class SmartConversation:
    """
    Intelligent conversation handler that:
    - Remembers returning users
    - Consolidates data collection steps
    - Uses natural language understanding
    - Provides personalized responses
    """
    
    def __init__(self):
        self.memory = UserMemory()
        self.nlu = NaturalLanguageEngine()
    
    def get_personalized_greeting(self, phone: str) -> Tuple[str, Optional[UserProfile]]:
        """Generate a personalized greeting based on user history and time."""
        profile = self.memory.get_profile(phone)
        
        # Use Zimbabwe timezone (UTC+2)
        from datetime import timezone, timedelta
        zim_tz = timezone(timedelta(hours=2))
        now = datetime.now(zim_tz)
        hour = now.hour
        
        # Time-based greeting
        if 5 <= hour < 12:
            time_greeting = "Good morning"
        elif 12 <= hour < 17:
            time_greeting = "Good afternoon"
        elif 17 <= hour < 21:
            time_greeting = "Good evening"
        else:
            time_greeting = "Hello"
        
        # Special seasonal greetings
        is_new_year_period = now.month == 1 and now.day <= 20
        
        if profile and profile.name:
            # Returning user
            name = profile.name.split()[0]  # First name only
            
            # For returning users: Happy New Year REPLACES the time greeting during Jan 1-20
            if is_new_year_period:
                main_greeting = f"Happy New Year {name}!"
            else:
                main_greeting = f"{time_greeting} {name}!"
            
            if profile.donation_count > 0:
                # Has donated before - show currency-specific totals
                totals_parts = []
                if profile.total_usd > 0:
                    totals_parts.append(f"*${profile.total_usd:.2f} USD*")
                if profile.total_zwg > 0:
                    totals_parts.append(f"*ZWG {profile.total_zwg:.2f}*")
                
                if totals_parts:
                    totals_text = " and ".join(totals_parts)
                else:
                    totals_text = "*$0.00*"
                
                greeting = (
                    f"{main_greeting}\n\n"
                    f"Welcome back to *LatterPay*!\n"
                    f"You've made *{profile.donation_count}* donation(s) totaling {totals_text}.\n\n"
                    f"Thank you for your continued support!"
                )
            else:
                greeting = (
                    f"{main_greeting}\n\n"
                    f"Welcome back to *LatterPay*!"
                )
        else:
            # New user - ALWAYS gets normal time-based greeting (no Happy New Year)
            greeting = (
                f"{time_greeting}!\n\n"
                f"Welcome to *LatterPay* - your trusted platform for donations and data collection.\n\n"
                f"I'm here to help you make contributions quickly and securely."
            )
        
        return greeting, profile
    
    def get_quick_donation_prompt(self, profile: Optional[UserProfile]) -> str:
        """Generate a smart donation prompt based on user history."""
        if profile and profile.name and profile.congregation:
            # Returning user with saved info - offer quick donate
            return (
                f"\n\n💡 *Quick Donate*\n"
                f"I remember your details:\n"
                f"• Name: *{profile.name}*\n"
                f"• Congregation: *{profile.congregation}*\n"
                f"• Preferred: *{profile.preferred_payment_method}* ({profile.preferred_currency})\n\n"
                f"Just tell me the *amount* and *purpose*!\n"
                f"_Example: \"50 for conference\" or \"100 monthly contribution\"_\n\n"
                f"Or type *new* to enter different details."
            )
        else:
            return (
                f"\n\n*What would you like to do?*\n\n"
                f"1️⃣ Make a Donation\n"
                f"2️⃣ Register as a Volunteer\n"
                f"3️⃣ Check Payment Status\n"
                f"4️⃣ Get Help\n\n"
                f"_Reply with a number or just tell me what you need!_"
            )
    
    def save_user_from_session(self, phone: str, session_data: dict):
        """Save user profile from session data - wrapper for memory method."""
        self.memory.save_user_from_session(phone, session_data)
    
    def process_natural_input(self, phone: str, text: str, session: Dict) -> Dict:
        """
        Process natural language input and extract all possible data.
        Returns updated session data and next step.
        """
        parsed = self.nlu.parse(text)
        profile = self.memory.get_profile(phone)
        
        result = {
            'intent': parsed.intent,
            'data': session.get('data', {}),
            'next_step': None,
            'response': None,
            'skip_steps': [],
        }
        
        # Merge entities into session data
        for key, value in parsed.entities.items():
            result['data'][key] = value
        
        # If returning user, auto-fill from profile
        if profile:
            if 'name' not in result['data'] and profile.name:
                result['data']['name'] = profile.name
                result['skip_steps'].append('name')
            if 'region' not in result['data'] and profile.congregation:
                result['data']['region'] = profile.congregation
                result['skip_steps'].append('region')
            if 'currency' not in result['data']:
                result['data']['currency'] = profile.preferred_currency
            if 'payment_method' not in result['data']:
                result['data']['payment_method'] = profile.preferred_payment_method
        
        # Determine how complete the donation data is
        required_fields = ['name', 'region', 'donation_type', 'amount', 'currency']
        missing = [f for f in required_fields if f not in result['data']]
        
        if parsed.intent == 'donate' or 'amount' in parsed.entities:
            if not missing:
                # All data collected! Skip to confirmation
                result['next_step'] = 'awaiting_confirmation'
            elif len(missing) <= 2:
                # Almost there - ask for missing fields in one message
                result['next_step'] = 'collect_missing'
                result['missing_fields'] = missing
            else:
                # Need more info - start guided flow
                result['next_step'] = 'name' if 'name' in missing else missing[0]
        
        return result
    
    def generate_consolidated_prompt(self, missing_fields: List[str]) -> str:
        """Generate a single prompt for multiple missing fields."""
        prompts = {
            'name': "your *full name*",
            'region': "your *congregation*",
            'donation_type': "the *purpose* (e.g., conference, monthly, construction)",
            'amount': "the *amount* you wish to donate",
            'currency': "your preferred *currency* (USD or ZWG)",
        }
        
        field_prompts = [prompts.get(f, f) for f in missing_fields]
        
        if len(field_prompts) == 1:
            return f"Please provide {field_prompts[0]}:"
        elif len(field_prompts) == 2:
            return f"Please provide {field_prompts[0]} and {field_prompts[1]}:"
        else:
            return f"Please provide:\n• " + "\n• ".join(field_prompts)
    
    def save_user_from_session(self, phone: str, session_data: Dict):
        """Save user profile from completed donation session."""
        profile = self.memory.get_profile(phone) or UserProfile(phone=phone)
        
        if 'name' in session_data:
            profile.name = session_data['name']
        if 'region' in session_data:
            profile.congregation = session_data['region']
        if 'email' in session_data:
            profile.email = session_data['email']
        if 'currency' in session_data:
            profile.preferred_currency = session_data['currency']
        if 'payment_method' in session_data:
            profile.preferred_payment_method = session_data['payment_method']
        
        self.memory.save_profile(profile)


# ============================================================================
# WHATSAPP INTERACTIVE MESSAGES
# ============================================================================

class WhatsAppInteractive:
    """
    Generate WhatsApp Cloud API interactive message payloads.
    Supports buttons, lists, and quick replies.
    """
    
    @staticmethod
    def create_button_message(
        recipient: str,
        body_text: str,
        buttons: List[Dict[str, str]],
        header: str = None,
        footer: str = None
    ) -> Dict:
        """
        Create an interactive button message.
        Max 3 buttons, each with id and title.
        """
        interactive = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn.get("id", f"btn_{i}"),
                            "title": btn["title"][:20]  # Max 20 chars
                        }
                    }
                    for i, btn in enumerate(buttons[:3])  # Max 3 buttons
                ]
            }
        }
        
        if header:
            interactive["header"] = {"type": "text", "text": header}
        if footer:
            interactive["footer"] = {"text": footer}
        
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": interactive
        }
    
    @staticmethod
    def create_list_message(
        recipient: str,
        body_text: str,
        button_text: str,
        sections: List[Dict],
        header: str = None,
        footer: str = None
    ) -> Dict:
        """
        Create an interactive list message.
        Great for donation types, payment methods, etc.
        """
        interactive = {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],
                "sections": sections
            }
        }
        
        if header:
            interactive["header"] = {"type": "text", "text": header}
        if footer:
            interactive["footer"] = {"text": footer}
        
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": interactive
        }
    
    @staticmethod
    def create_main_menu(recipient: str, greeting: str) -> Dict:
        """Create the main menu with interactive buttons."""
        return WhatsAppInteractive.create_button_message(
            recipient=recipient,
            body_text=greeting,
            buttons=[
                {"id": "donate", "title": "💰 Donate"},
                {"id": "register", "title": "📝 Register"},
                {"id": "help", "title": "❓ Help"}
            ],
            footer="Tap a button to begin"
        )
    
    @staticmethod
    def create_donation_type_list(recipient: str) -> Dict:
        """Create donation type selection as a list."""
        sections = [{
            "title": "Choose Purpose",
            "rows": [
                {"id": "monthly", "title": "Monthly Contributions", "description": "Regular monthly giving"},
                {"id": "august_conf", "title": "August Conference", "description": "Annual conference support"},
                {"id": "youth_conf", "title": "Youth Conference", "description": "Youth ministry support"},
                {"id": "construction", "title": "Construction", "description": "Building fund"},
                {"id": "pastoral", "title": "Pastoral Support", "description": "Support our pastors"},
                {"id": "other", "title": "Other", "description": "Other purposes"},
            ]
        }]
        
        return WhatsAppInteractive.create_list_message(
            recipient=recipient,
            body_text="What would you like to contribute towards?",
            button_text="Select Purpose",
            sections=sections,
            header="🎯 Donation Purpose"
        )
    
    @staticmethod
    def create_payment_method_buttons(recipient: str) -> Dict:
        """Create payment method selection buttons."""
        return WhatsAppInteractive.create_button_message(
            recipient=recipient,
            body_text="How would you like to pay?",
            buttons=[
                {"id": "ecocash", "title": "📱 EcoCash"},
                {"id": "onemoney", "title": "📱 OneMoney"},
                {"id": "innbucks", "title": "💵 InnBucks"}
            ],
            header="💳 Payment Method"
        )
    
    @staticmethod
    def create_currency_buttons(recipient: str) -> Dict:
        """Create currency selection buttons."""
        return WhatsAppInteractive.create_button_message(
            recipient=recipient,
            body_text="Which currency?",
            buttons=[
                {"id": "usd", "title": "🇺🇸 USD"},
                {"id": "zwg", "title": "🇿🇼 ZWG"}
            ],
            header="💱 Select Currency"
        )
    
    @staticmethod
    def create_confirmation_buttons(recipient: str, summary: str) -> Dict:
        """Create confirmation buttons with summary."""
        return WhatsAppInteractive.create_button_message(
            recipient=recipient,
            body_text=summary,
            buttons=[
                {"id": "confirm", "title": "✅ Confirm"},
                {"id": "edit", "title": "✏️ Edit"},
                {"id": "cancel", "title": "❌ Cancel"}
            ],
            header="📋 Confirm Details"
        )


# ============================================================================
# EXPORTS
# ============================================================================

# Global instances
user_memory = UserMemory()
nlu_engine = NaturalLanguageEngine()
smart_conversation = SmartConversation()
whatsapp_interactive = WhatsAppInteractive()

__all__ = [
    'UserProfile',
    'UserMemory',
    'ParsedIntent',
    'NaturalLanguageEngine',
    'SmartConversation',
    'WhatsAppInteractive',
    'user_memory',
    'nlu_engine',
    'smart_conversation',
    'whatsapp_interactive',
]
