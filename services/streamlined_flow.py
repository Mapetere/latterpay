"""
Streamlined Flow Handler for LatterPay v3.0
============================================
A modern, streamlined conversation handler that:
- Reduces steps from 7+ to 3-4 for donations
- Remembers returning users
- Supports natural language input
- Uses interactive buttons where possible
- Provides personalized experiences

Author: Nyasha Praise Mapetere
Version: 3.0.0
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Tuple, Any

from services.smart_conversation import (
    smart_conversation, 
    user_memory, 
    nlu_engine,
    UserProfile
)
from services.enhanced_whatsapp import enhanced_whatsapp
from services.pygwan_whatsapp import whatsapp
from services.sessions import (
    load_session, save_session, delete_session,
    initialize_session, cancel_session
)
from services.config import donation_config, admin_config

logger = logging.getLogger(__name__)

# AI-powered NLU (uses OpenAI with regex fallback)
try:
    from services.ai_nlu import smart_extract, to_session_entities, OPENAI_ENABLED
    AI_NLU_AVAILABLE = True
    logger.info(f"AI NLU loaded. OpenAI enabled: {OPENAI_ENABLED}")
except ImportError:
    AI_NLU_AVAILABLE = False
    OPENAI_ENABLED = False
    logger.warning("AI NLU not available, using regex only")


# ============================================================================
# STREAMLINED STATE MACHINE
# ============================================================================

class StreamlinedFlow:
    """
    A streamlined conversation flow that minimizes user effort.
    
    Flow for RETURNING users (3 steps):
    1. Greeting + Quick Donate offer
    2. Amount + Purpose (combined or pre-filled)
    3. Confirm + Pay
    
    Flow for NEW users (4-5 steps):
    1. Greeting + Menu
    2. Name + Congregation (combined)
    3. Amount + Purpose
    4. Currency + Payment Method (can be combined)
    5. Confirm + Pay
    """
    
    # Donation purpose mapping from button IDs
    PURPOSE_MAP = {
        "purpose_monthly": "Monthly Contributions",
        "purpose_august": "August Conference",
        "purpose_youth": "Youth Conference",
        "purpose_construction": "Construction Contribution",
        "purpose_pastoral": "Pastoral Support",
        "purpose_other": "Other",
        # Also support old style numbers
        "1": "Monthly Contributions",
        "2": "August Conference",
        "3": "Youth Conference",
        "4": "Construction Contribution",
        "5": "Pastoral Support",
        "6": "Other",
    }
    
    # Payment method mapping
    PAYMENT_MAP = {
        "pay_ecocash": "EcoCash",
        "pay_onemoney": "OneMoney",
        "pay_innbucks": "InnBucks",
        "ecocash": "EcoCash",
        "onemoney": "OneMoney",
        "innbucks": "InnBucks",
        "1": "EcoCash",
        "2": "OneMoney",
        "3": "InnBucks",
    }
    
    # Currency mapping
    CURRENCY_MAP = {
        "currency_usd": "USD",
        "currency_zwg": "ZWG",
        "usd": "USD",
        "zwg": "ZWG",
        "1": "USD",
        "2": "ZWG",
    }
    
    # City/Congregation mapping from button IDs
    CITY_MAP = {
        "city_harare_central": "Harare Central",
        "city_harare_north": "Harare North",
        "city_harare_south": "Harare South",
        "city_chitungwiza": "Chitungwiza",
        "city_epworth": "Epworth",
        "city_norton": "Norton",
        "city_ruwa": "Ruwa",
        "city_bulawayo_central": "Bulawayo Central",
        "city_bulawayo_north": "Bulawayo North",
        "city_bulawayo_south": "Bulawayo South",
        "city_mutare": "Mutare",
        "city_gweru": "Gweru",
        "city_kwekwe": "Kwekwe",
        "city_masvingo": "Masvingo",
        "city_chinhoyi": "Chinhoyi",
        "city_marondera": "Marondera",
        "city_kadoma": "Kadoma",
        "city_bindura": "Bindura",
        "city_victoria_falls": "Victoria Falls",
    }
    
    # Zimbabwe cities/congregations for auto-detection
    ZIMBABWE_CITIES = [
        "harare", "bulawayo", "chitungwiza", "mutare", "gweru", "kwekwe",
        "kadoma", "masvingo", "chinhoyi", "marondera", "norton", "ruwa",
        "chegutu", "bindura", "beitbridge", "hwange", "victoria falls",
        "kariba", "zvishavane", "redcliff", "chiredzi", "chipinge", "rusape",
        "nyanga", "shurugwi", "gokwe", "karoi", "banket", "mhangura",
        "mvurwi", "shamva", "mt darwin", "centenary", "guruve", "muzarabani",
        "glendale", "epworth", "highfield", "mbare", "avondale", "borrowdale",
        "glen lorne", "marlborough", "waterfalls", "kuwadzana", "budiriro",
        "dzivarasekwa", "mufakose", "glen norah", "southerton", "graniteside",
        "belvedere", "arcadia", "greendale", "hatfield", "hillside", "mabelreign",
        "mt pleasant", "vainona", "bluffhill", "ashdown park", "westgate",
        # Common congregation/area names
        "central", "north", "south", "east", "west", "cbd", "town", "township"
    ]
    
    def __init__(self):
        self.conversation = smart_conversation
        self.memory = user_memory
        self.nlu = nlu_engine
    
    def _detect_city(self, text: str) -> Optional[str]:
        """Detect Zimbabwe city/congregation name from text."""
        text_lower = text.lower()
        for city in self.ZIMBABWE_CITIES:
            if city in text_lower:
                return city.title()
        return None
    
    def _detect_name(self, text: str) -> Optional[str]:
        """Try to detect a person's name from natural text."""
        import re
        text_lower = text.lower()
        
        # Patterns like "I'm X", "Im X", "My name is X", "I am X"
        patterns = [
            r"i[']?m\s+([a-z]+(?:\s+[a-z]+)?)",  # I'm John or Im John Moyo
            r"my\s+name\s+is\s+([a-z]+(?:\s+[a-z]+)?)",  # My name is John
            r"i\s+am\s+([a-z]+(?:\s+[a-z]+)?)",  # I am John
            r"^([a-z]+(?:\s+[a-z]+)?)\s*,",  # John Moyo, Harare
            r"^([a-z]+(?:\s+[a-z]+)?)\s+from",  # John Moyo from Harare
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                name = match.group(1).strip()
                # Filter out common non-name words
                skip_words = ['donate', 'donating', 'pay', 'paying', 'want', 'would', 'like', 'to', 'for']
                if name.split()[0] not in skip_words:
                    return name.title()
        
        return None
    
    def handle_message(self, phone: str, message: str, raw_data: Dict = None) -> str:
        """
        Main entry point for handling any user message.
        
        Args:
            phone: User's phone number
            message: The message text
            raw_data: Raw webhook data (for interactive responses)
            
        Returns:
            Status string
        """
        # Check for interactive response first
        interactive_response = None
        if raw_data:
            interactive_response = enhanced_whatsapp.parse_interactive_response(raw_data)
            if interactive_response:
                message = interactive_response.get("id", message)
                logger.info(f"Interactive response from {phone}: {interactive_response}")
        
        # Load or create session
        session = load_session(phone) or {"step": "start", "data": {}}
        step = session.get("step", "start")
        
        logger.info(f"[{phone}] Step: {step}, Message: {message[:50]}...")
        
        # Global commands
        msg_lower = message.lower().strip()
        if msg_lower in ["cancel", "quit", "exit", "stop"]:
            return self._handle_cancel(phone)
        if msg_lower in ["help", "?", "action_help", "quick_help"]:
            return self._send_help(phone)
        if msg_lower in ["check", "status", "check_again"]:
            return self._handle_check_status(phone, session)
        if msg_lower in ["menu", "start_over"]:
            # Reset session and show smart menu
            delete_session(phone)
            session = {"step": "start", "data": {}}
            return self._handle_start(phone, message, session)
        if msg_lower == "retry_payment":
            # Retry payment - go back to phone number step
            if session.get("data", {}).get("payment_method"):
                session["step"] = "awaiting_phone_number"
                session["poll_url"] = None  # Clear old poll_url
                save_session(phone, session["step"], session["data"])
                method = session["data"].get("payment_method", "EcoCash")
                whatsapp.send_message(
                    f"Let's try again!\n\nEnter your *{method}* number:\n_Format: 0771234567_",
                    phone
                )
                return "retry_payment"
            else:
                delete_session(phone)
                return self._handle_start(phone, message, {"step": "start", "data": {}})
        
        # Route to appropriate handler
        handler_map = {
            "start": self._handle_start,
            "awaiting_action": self._handle_action_selection,
            "collect_info": self._handle_collect_info,
            "awaiting_name": self._handle_name_input,
            "awaiting_province": self._handle_province_selection,
            "awaiting_congregation": self._handle_congregation_selection,
            "awaiting_purpose": self._handle_purpose_selection,
            "awaiting_amount": self._handle_amount_input,
            "confirm_split_amount": self._handle_split_amount_confirmation,
            "awaiting_currency": self._handle_currency_selection,
            "awaiting_confirmation": self._handle_confirmation,
            "awaiting_payment_method": self._handle_payment_method,
            "awaiting_phone_number": self._handle_phone_number,
            # Registration flow
            "reg_awaiting_info": self._handle_registration_info,
        }
        
        handler = handler_map.get(step, self._handle_unknown)
        return handler(phone, message, session)
    
    # ========================================================================
    # START & GREETING
    # ========================================================================
    
    def _handle_start(self, phone: str, message: str, session: Dict) -> str:
        """Handle initial interaction or returning to start."""
        # Get personalized greeting
        greeting, profile = self.conversation.get_personalized_greeting(phone)
        
        if profile and profile.name and profile.congregation:
            # Returning user with saved info - offer quick donate
            summary = (
                f"{greeting}\n\n"
                f" *Your saved details:*\n"
                f"• Name: {profile.name}\n"
                f"• Congregation: {profile.congregation}\n"
                f"• Preferred: {profile.preferred_payment_method} ({profile.preferred_currency})"
            )
            
            # Pre-fill session with saved data
            session["data"] = {
                "name": profile.name,
                "region": profile.congregation,
                "currency": profile.preferred_currency,
                "payment_method": profile.preferred_payment_method,
            }
            session["step"] = "awaiting_action"
            session["is_returning"] = True
            save_session(phone, session["step"], session["data"])
            
            # Returning users - no logo
            enhanced_whatsapp.send_quick_donate_offer(phone, summary, show_logo=False)
        else:
            # New user - send main menu with logo
            session["step"] = "awaiting_action"
            session["is_returning"] = False
            save_session(phone, session["step"], session["data"])
            
            enhanced_whatsapp.send_main_menu(phone, greeting, show_logo=True)
        
        return "greeting_sent"
    
    def _handle_action_selection(self, phone: str, message: str, session: Dict) -> str:
        """Handle main menu action selection."""
        msg = message.lower().strip()
        
        # Check if user is returning (has saved data in session)
        has_saved_data = session.get("data", {}).get("name") and session.get("data", {}).get("region")
        
        # Quick donate for returning users
        if msg in ["quick_yes", "quick", "action_donate", "donate"]:
            if has_saved_data:
                # Returning user with saved data - skip straight to purpose!
                session["step"] = "awaiting_purpose"
                save_session(phone, session["step"], session["data"])
                
                name = session["data"].get("name", "")
                whatsapp.send_message(
                    f"Great, *{name}*! Let's continue with your saved details. ",
                    phone
                )
                enhanced_whatsapp.send_donation_purposes(phone)
                return "purpose_prompt_sent"
            else:
                # Need to collect info first - ask for name
                session["step"] = "awaiting_name"
                save_session(phone, session["step"], session["data"])
                whatsapp.send_message(
                    "Let's get started!\n\n"
                    "Please enter your *full name*:\n\n"
                    "_Example: John Moyo_",
                    phone
                )
                return "name_prompt_sent"
        
        elif msg in ["quick_new", "new"]:
            # User wants to donate from a DIFFERENT congregation
            # Keep name but ask for new congregation
            saved_name = session.get("data", {}).get("name", "")
            session["data"] = {"name": saved_name} if saved_name else {}
            
            if saved_name:
                # Has name, just need congregation
                session["step"] = "awaiting_congregation"
                save_session(phone, session["step"], session["data"])
                whatsapp.send_message(
                    f"No problem, *{saved_name}*!\n\n"
                    "Please select your congregation:",
                    phone
                )
                enhanced_whatsapp.send_congregation_list(phone)
            else:
                # Need both name and congregation
                session["step"] = "awaiting_name"
                save_session(phone, session["step"], session["data"])
                whatsapp.send_message(
                    "Let's start fresh!\n\n"
                    "Please enter your *full name*:\n\n"
                    "_Example: John Moyo_",
                    phone
                )
            return "collect_info_prompt"
        
        elif msg in ["action_register", "register", "2"]:
            session["step"] = "reg_awaiting_info"
            save_session(phone, session["step"], session["data"])
            whatsapp.send_message(
                " *Registration*\n\n"
                "Please provide the following in one message:\n"
                "• Your full name\n"
                "• Your congregation/area\n"
                "• Your email\n"
                "• Your skill (e.g., Medical, IT, Teaching)\n\n"
                "_Example: John Moyo, Harare, john@email.com, IT Support_",
                phone
            )
            return "registration_prompt"
        
        elif msg in ["action_help", "help", "3", "?"]:
            return self._send_help(phone)
        
        else:
            # Try AI NLU first, fall back to regex
            if AI_NLU_AVAILABLE:
                extraction = smart_extract(message)
                entities = to_session_entities(extraction)
                intent = extraction.intent
            else:
                parsed = self.nlu.parse(message)
                entities = parsed.entities
                intent = parsed.intent
            
            if intent == "donate" or entities.get("amount") or entities.get("donation_type"):
                # They mentioned donating or an amount
                session["data"].update(entities)
                
                # Check what we have and what we need
                has_name = session["data"].get("name")
                has_region = session["data"].get("region")
                has_amount = session["data"].get("amount")
                has_purpose = session["data"].get("donation_type")
                
                if has_name and has_region:
                    # User already known - use smart routing
                    if has_amount and has_purpose:
                        # Everything extracted! Skip to currency
                        session["step"] = "awaiting_currency"
                        save_session(phone, session["step"], session["data"])
                        whatsapp.send_message(
                            f"Got it! *{has_purpose}* - *{has_amount}*",
                            phone
                        )
                        enhanced_whatsapp.send_currency_selection(phone)
                        return "currency_prompt"
                    elif has_purpose:
                        # Have purpose, need amount
                        session["step"] = "awaiting_amount"
                        save_session(phone, session["step"], session["data"])
                        whatsapp.send_message(
                            f"*{has_purpose}* - got it!\n\n"
                            "How much would you like to donate?\n"
                            "_Maximum: Both ZWG and USD is 480_",
                            phone
                        )
                        return "amount_prompt"
                    elif has_amount:
                        # Have amount, need purpose
                        session["step"] = "awaiting_purpose"
                        save_session(phone, session["step"], session["data"])
                        whatsapp.send_message(f"Amount: *{has_amount}* - got it!", phone)
                        enhanced_whatsapp.send_donation_purposes(phone)
                        return "purpose_prompt"
                    else:
                        # Need both
                        session["step"] = "awaiting_purpose"
                        save_session(phone, session["step"], session["data"])
                        enhanced_whatsapp.send_donation_purposes(phone)
                        return "purpose_prompt"
                else:
                    # Need name/congregation - go to collect_info
                    session["step"] = "collect_info"
                    save_session(phone, session["step"], session["data"])
                    
                    # Build acknowledgment of what we extracted
                    ack_parts = []
                    if has_amount:
                        ack_parts.append(f"Amount: *{has_amount}*")
                    if has_purpose:
                        ack_parts.append(f"Purpose: *{has_purpose}*")
                    
                    ack_text = ", ".join(ack_parts) if ack_parts else ""
                    
                    whatsapp.send_message(
                        f"I understand you'd like to donate!\n"
                        f"{ack_text}\n\n"
                        f"Please tell me your *name* and *congregation*:\n"
                        f"_Example: John Moyo, Harare Central_",
                        phone
                    )
                    return "collect_info_needed"
            
            # Didn't understand - show menu again
            enhanced_whatsapp.send_main_menu(phone, "I didn't quite catch that. Please select an option:")
            return "menu_resent"
    
    # ========================================================================
    # DONATION FLOW
    # ========================================================================
    
    def _handle_name_input(self, phone: str, message: str, session: Dict) -> str:
        """Handle name input from user."""
        import re
        name = message.strip()
        
        # Basic validation - name should have at least 2 characters
        if len(name) < 2:
            whatsapp.send_message(
                "Please enter a valid name (at least 2 characters).",
                phone
            )
            return "invalid_name"
        
        # Reject special characters - only allow letters, spaces, hyphens, apostrophes
        if not re.match(r"^[A-Za-z\s\-']+$", name):
            whatsapp.send_message(
                "Name contains invalid characters.\n\n"
                "Please use only letters, spaces, and hyphens.\n"
                "_Example: John Moyo_",
                phone
            )
            return "invalid_name"
        
        # Skip common commands
        if name.lower() in ['cancel', 'menu', 'help', 'donate']:
            if name.lower() == 'cancel':
                return self._handle_cancel(phone)
            elif name.lower() == 'menu':
                delete_session(phone)
                return self._handle_start(phone, message, {"step": "start", "data": {}})
            elif name.lower() == 'help':
                return self._send_help(phone)
        
        # Save name
        session["data"]["name"] = name.title()
        session["step"] = "awaiting_province"
        save_session(phone, session["step"], session["data"])
        
        # Send province list (the list includes the name confirmation)
        enhanced_whatsapp.send_congregation_list(phone, name.title())
        return "province_prompt_sent"
    
    def _handle_province_selection(self, phone: str, message: str, session: Dict) -> str:
        """Handle province selection, then show cities for that province."""
        msg = message.strip()
        
        # Map province titles to IDs
        province_map = {
            "harare metropolitan": "province_harare",
            "bulawayo metropolitan": "province_bulawayo",
            "mashonaland east": "province_mashonaland_east",
            "mashonaland west": "province_mashonaland_west",
            "mashonaland central": "province_mashonaland_central",
            "midlands": "province_midlands",
            "masvingo": "province_masvingo",
            "manicaland": "province_manicaland",
            "matabeleland north": "province_matebeleland_north",
            "matabeleland south": "province_matebeleland_south",
        }
        
        # Check if it's a province button selection (ID)
        if msg.startswith("province_"):
            province_id = msg
        else:
            # User selected by title - map to ID
            province_id = province_map.get(msg.lower(), "province_harare")
        
        session["data"]["province"] = province_id
        session["step"] = "awaiting_congregation"
        save_session(phone, session["step"], session["data"])
        
        # Send cities for this province
        enhanced_whatsapp.send_cities_for_province(phone, province_id)
        return "city_prompt_sent"
    
    def _handle_congregation_selection(self, phone: str, message: str, session: Dict) -> str:
        """Handle city/congregation selection from list."""
        msg = message.strip()
        
        # Province name to readable format map
        province_names = {
            "province_harare": "Harare",
            "province_bulawayo": "Bulawayo", 
            "province_mashonaland_east": "Mashonaland East",
            "province_mashonaland_west": "Mashonaland West",
            "province_mashonaland_central": "Mashonaland Central",
            "province_midlands": "Midlands",
            "province_masvingo": "Masvingo",
            "province_manicaland": "Manicaland",
            "province_matebeleland_north": "Matabeleland North",
            "province_matebeleland_south": "Matabeleland South",
        }
        
        # If user selected a province name again (city list might have failed), 
        # just use the province as congregation
        if msg.lower() in ["midlands", "harare metropolitan", "bulawayo metropolitan", 
                           "mashonaland east", "mashonaland west", "mashonaland central",
                           "masvingo", "manicaland", "matabeleland north", "matabeleland south"]:
            congregation = msg.title()
        # Check if it's a city button selection
        elif msg in self.CITY_MAP:
            congregation = self.CITY_MAP[msg]
        elif msg.startswith("city_"):
            # Extract city name from ID
            congregation = msg.replace("city_", "").replace("_", " ").title()
        elif msg.startswith("province_"):
            # Province ID was passed - convert to readable name
            congregation = province_names.get(msg, msg.replace("province_", "").replace("_", " ").title())
        else:
            # User typed the city/congregation name
            congregation = msg.title()
        
        session["data"]["region"] = congregation
        
        # Now proceed to purpose selection - single message
        session["step"] = "awaiting_purpose"
        save_session(phone, session["step"], session["data"])
        
        # Send purpose list with congregation confirmation
        enhanced_whatsapp.send_donation_purposes(phone, congregation)
        return "purpose_prompt_sent"
    
    def _handle_collect_info(self, phone: str, message: str, session: Dict) -> str:
        """Handle combined name + congregation collection with AI NLU support."""
        # First, try AI NLU to see if user is giving us donation info instead of name
        if AI_NLU_AVAILABLE:
            extraction = smart_extract(message)
            entities = to_session_entities(extraction)
        else:
            parsed = self.nlu.parse(message)
            entities = parsed.entities
        
        # Auto-detect city/congregation from message
        detected_city = self._detect_city(message)
        if detected_city:
            session["data"]["region"] = detected_city
            logger.info(f"Auto-detected city: {detected_city}")
        
        # Auto-detect name from patterns like "Im X", "I'm X"
        detected_name = self._detect_name(message)
        if detected_name and "name" not in session.get("data", {}):
            session["data"]["name"] = detected_name
            logger.info(f"Auto-detected name: {detected_name}")
        
        # Check if they gave us an amount or purpose instead of name/congregation
        if entities.get("amount") or entities.get("donation_type"):
            # User said something like "donate 50 for conference"
            # Extract what we can and merge into session
            if entities.get("amount"):
                session["data"]["amount"] = entities["amount"]
            if entities.get("donation_type"):
                session["data"]["donation_type"] = entities["donation_type"]
            if entities.get("currency"):
                session["data"]["currency"] = entities["currency"]
            # AI can also extract name and congregation!
            if entities.get("name"):
                session["data"]["name"] = entities["name"]
            if entities.get("region"):
                session["data"]["region"] = entities["region"]
            
            # Check what's still missing
            has_name = session.get("data", {}).get("name")
            has_region = session.get("data", {}).get("region")
            has_amount = session.get("data", {}).get("amount")
            has_purpose = session.get("data", {}).get("donation_type")
            
            if has_name and has_region:
                # User already known, got amount/purpose - skip to currency or confirm
                if has_amount and has_purpose:
                    if "currency" not in session["data"]:
                        session["step"] = "awaiting_currency"
                        save_session(phone, session["step"], session["data"])
                        enhanced_whatsapp.send_currency_selection(phone)
                        return "currency_prompt"
                    else:
                        return self._send_confirmation(phone, session)
                elif has_amount:
                    session["step"] = "awaiting_purpose"
                    save_session(phone, session["step"], session["data"])
                    enhanced_whatsapp.send_donation_purposes(phone)
                    return "purpose_prompt"
            else:
                # Still need name/congregation
                save_session(phone, session["step"], session["data"])
                whatsapp.send_message(
                    f"Got it! Amount: *{session['data'].get('amount', '?')}*\n\n"
                    "Now please tell me your *name* and *congregation*:\n"
                    "_Example: John Moyo, Harare Central_",
                    phone
                )
                return "still_need_info"
        
        # Check if we already have name (returning user changing congregation)
        existing_name = session.get("data", {}).get("name")
        
        # Parse the input as "Name, Congregation"
        parts = [p.strip() for p in message.replace(" and ", ", ").split(",") if p.strip()]
        
        if existing_name and len(parts) >= 1:
            # User is just providing new congregation
            session["data"]["region"] = self._normalize_congregation(parts[0])
            
            whatsapp.send_message(
                f"Got it! Donating from *{session['data']['region']}* today. ",
                phone
            )
            
            # Check what we already have and skip accordingly
            return self._proceed_after_info_collected(phone, session)
        
        elif len(parts) >= 2:
            session["data"]["name"] = parts[0].title()
            session["data"]["region"] = self._normalize_congregation(parts[1])
            
            whatsapp.send_message(
                f"Thanks, *{session['data']['name']}* from *{session['data']['region']}*! ",
                phone
            )
            
            # Check what we already have and skip accordingly
            return self._proceed_after_info_collected(phone, session)
        
        elif len(parts) == 1:
            # Check if this looks like a real name (not a command or number)
            text = parts[0].lower()
            if any(word in text for word in ['donate', 'pay', 'give', 'help', 'menu', 'cancel']):
                # This is a command, not a name
                whatsapp.send_message(
                    "I need your details first!\n\n"
                    "Please provide your *name* and *congregation*:\n"
                    "_Example: John Moyo, Harare Central_",
                    phone
                )
                return "collect_info_retry"
            
            # Assume it's the name
            session["data"]["name"] = parts[0].title()
            save_session(phone, session["step"], session["data"])
            whatsapp.send_message(
                f"Thanks, *{session['data']['name']}*!\n\n"
                "Now please tell me your *congregation* or area:",
                phone
            )
            return "awaiting_congregation"
        
        else:
            whatsapp.send_message(
                "Please provide your *name* and *congregation*:\n"
                "_Example: John Moyo, Harare Central_",
                phone
            )
            return "collect_info_retry"
    
    def _proceed_after_info_collected(self, phone: str, session: Dict) -> str:
        """Determine next step after name/congregation collected, skipping steps if data exists."""
        has_purpose = session.get("data", {}).get("donation_type")
        has_amount = session.get("data", {}).get("amount")
        has_currency = session.get("data", {}).get("currency")
        
        if has_purpose and has_amount:
            # Both exist - skip to currency or confirmation
            if has_currency:
                return self._send_confirmation(phone, session)
            else:
                session["step"] = "awaiting_currency"
                save_session(phone, session["step"], session["data"])
                enhanced_whatsapp.send_currency_selection(phone)
                return "currency_prompt"
        
        elif has_purpose:
            # Have purpose but need amount
            session["step"] = "awaiting_amount"
            save_session(phone, session["step"], session["data"])
            whatsapp.send_message(
                f"*{has_purpose}* - got it! \n\n"
                " How much would you like to donate?\n\n"
                "Just type the amount (e.g., *50* or *100*)\n"
                "_Maximum: Both ZWG and USD is 480_",
                phone
            )
            return "amount_prompt"
        
        elif has_amount:
            # Have amount but need purpose
            session["step"] = "awaiting_purpose"
            save_session(phone, session["step"], session["data"])
            whatsapp.send_message(
                f"Amount: *{has_amount}* - got it! ",
                phone
            )
            enhanced_whatsapp.send_donation_purposes(phone)
            return "purpose_prompt"
        
        else:
            # Need both - go to purpose first
            session["step"] = "awaiting_purpose"
            save_session(phone, session["step"], session["data"])
            enhanced_whatsapp.send_donation_purposes(phone)
            return "purpose_prompt"
    
    def _handle_purpose_selection(self, phone: str, message: str, session: Dict) -> str:
        """Handle donation purpose selection."""
        msg = message.lower().strip()
        
        # Check if it's a valid purpose selection
        purpose = self.PURPOSE_MAP.get(msg)
        
        if not purpose:
            # Try NLU
            parsed = self.nlu.parse(message)
            purpose = parsed.entities.get("donation_type")
        
        if purpose:
            session["data"]["donation_type"] = purpose
            session["step"] = "awaiting_amount"
            save_session(phone, session["step"], session["data"])
            
            whatsapp.send_message(
                f"*{purpose}* selected\n\n"
                f"Enter your donation amount:\n"
                f"_Example: 50 or 100 (max 480)_",
                phone
            )
            return "amount_prompt_sent"
        
        # Invalid selection - show the list again
        enhanced_whatsapp.send_donation_purposes(phone)
        return "purpose_retry"
    
    def _handle_amount_input(self, phone: str, message: str, session: Dict) -> str:
        """Handle donation amount input."""
        # Extract amount from message
        parsed = self.nlu.parse(message)
        amount = parsed.entities.get("amount")
        
        if not amount:
            # Try direct conversion
            try:
                amount = float(message.strip().replace(",", "."))
            except ValueError:
                whatsapp.send_message(
                    " Please enter a valid amount (just the number):\n"
                    "_Example: 50 or 100.00_",
                    phone
                )
                return "amount_retry"
        
        # Validate amount
        if amount <= 0:
            whatsapp.send_message(
                " Amount must be greater than zero.\n"
                "Please enter a valid amount:",
                phone
            )
            return "amount_invalid"
        
        MAX_PER_TRANSACTION = 480
        
        if amount > MAX_PER_TRANSACTION:
            # Calculate how many transactions needed
            num_transactions = int(amount // MAX_PER_TRANSACTION)
            remainder = amount % MAX_PER_TRANSACTION
            if remainder > 0:
                num_transactions += 1
            
            # Build helpful message
            transactions_breakdown = []
            remaining = amount
            tx_num = 1
            while remaining > 0:
                tx_amount = min(remaining, MAX_PER_TRANSACTION)
                transactions_breakdown.append(f"• Transaction {tx_num}: *{tx_amount:.2f}*")
                remaining -= tx_amount
                tx_num += 1
            
            breakdown_text = "\n".join(transactions_breakdown)
            
            whatsapp.send_message(
                f" *Large Donation Detected!*\n\n"
                f"Your total: *{amount:.2f}*\n"
                f"Maximum per transaction: *{MAX_PER_TRANSACTION}*\n\n"
                f"You'll need *{num_transactions} transactions*:\n"
                f"{breakdown_text}\n\n"
                f"Let's start with the first *{MAX_PER_TRANSACTION:.2f}*.\n"
                f"_You can repeat the process for the remaining amount._\n\n"
                f"Reply *yes* to continue or enter a different amount:",
                phone
            )
            
            # Store the full amount and first transaction amount
            session["data"]["full_amount"] = amount
            session["data"]["pending_amount"] = amount - MAX_PER_TRANSACTION
            session["data"]["amount"] = MAX_PER_TRANSACTION
            session["step"] = "confirm_split_amount"
            save_session(phone, session["step"], session["data"])
            return "split_amount_offered"
        
        session["data"]["amount"] = amount
        
        # Check if we already have currency preference
        if "currency" not in session["data"] or not session.get("is_returning"):
            session["step"] = "awaiting_currency"
            save_session(phone, session["step"], session["data"])
            enhanced_whatsapp.send_currency_selection(phone)
            return "currency_prompt_sent"
        else:
            # Skip to confirmation
            return self._send_confirmation(phone, session)
    
    def _handle_split_amount_confirmation(self, phone: str, message: str, session: Dict) -> str:
        """Handle confirmation of split amount for large donations."""
        msg = message.lower().strip()
        
        if msg in ["yes", "y", "ok", "continue", "proceed"]:
            # Continue with the first 480
            if "currency" not in session["data"]:
                session["step"] = "awaiting_currency"
                save_session(phone, session["step"], session["data"])
                enhanced_whatsapp.send_currency_selection(phone)
                return "currency_prompt_sent"
            else:
                return self._send_confirmation(phone, session)
        else:
            # Try to parse as a new amount
            try:
                new_amount = float(msg.replace(",", "."))
                if new_amount > 0:
                    session["step"] = "awaiting_amount"
                    save_session(phone, session["step"], session["data"])
                    return self._handle_amount_input(phone, msg, session)
            except ValueError:
                pass
            
            whatsapp.send_message(
                "Please reply *yes* to continue with 480, or enter a different amount:",
                phone
            )
            return "split_amount_retry"
    
    def _handle_currency_selection(self, phone: str, message: str, session: Dict) -> str:
        """Handle currency selection."""
        msg = message.lower().strip()
        currency = self.CURRENCY_MAP.get(msg)
        
        if currency:
            session["data"]["currency"] = currency
            return self._send_confirmation(phone, session)
        
        enhanced_whatsapp.send_currency_selection(phone)
        return "currency_retry"
    
    def _send_confirmation(self, phone: str, session: Dict) -> str:
        """Generate and send payment confirmation."""
        data = session["data"]
        currency = data.get("currency", "ZWG")
        amount = data.get('amount', 0)
        
        # Format as USD$20.00 or ZWG$20.00
        amount_display = f"{currency}${amount:.2f}"
        
        summary = (
            f" *Payment Summary*\n"
            f"\n\n"
            f" *Name:* {data.get('name', 'N/A')}\n"
            f" *Congregation:* {data.get('region', 'N/A')}\n"
            f" *Purpose:* {data.get('donation_type', 'N/A')}\n"
            f" *Amount:* {amount_display}\n\n"
            f"\n\n"
            f"Tap  to proceed to payment"
        )
        
        session["step"] = "awaiting_confirmation"
        save_session(phone, session["step"], session["data"])
        
        enhanced_whatsapp.send_confirmation(phone, summary)
        return "confirmation_sent"
    
    def _handle_confirmation(self, phone: str, message: str, session: Dict) -> str:
        """Handle confirmation response."""
        msg = message.lower().strip()
        
        if msg in ["confirm_yes", "confirm", "yes", "y", "1"]:
            # Proceed to payment method
            session["step"] = "awaiting_payment_method"
            save_session(phone, session["step"], session["data"])
            enhanced_whatsapp.send_payment_methods(phone)
            return "payment_method_prompt"
        
        elif msg in ["confirm_edit", "edit", "e", "2"]:
            # Go back to start of donation flow
            session["step"] = "collect_info"
            session["data"] = {}
            save_session(phone, session["step"], session["data"])
            whatsapp.send_message(
                "Let's update your details. \n\n"
                "Please provide your *name* and *congregation*:\n"
                "_Example: John Moyo, Harare Central_",
                phone
            )
            return "edit_restart"
        
        elif msg in ["confirm_cancel", "cancel", "no", "n", "3"]:
            return self._handle_cancel(phone)
        
        # Didn't understand
        return self._send_confirmation(phone, session)
    
    def _handle_payment_method(self, phone: str, message: str, session: Dict) -> str:
        """Handle payment method selection."""
        msg = message.lower().strip()
        method = self.PAYMENT_MAP.get(msg)
        
        if method:
            session["data"]["payment_method"] = method
            session["step"] = "awaiting_phone_number"
            save_session(phone, session["step"], session["data"])
            
            whatsapp.send_message(
                f"*{method}* selected \n\n"
                f" Please enter your *{method} number*:\n\n"
                f"_Format: 0771234567 or 263771234567_",
                phone
            )
            return "phone_prompt"
        
        enhanced_whatsapp.send_payment_methods(phone)
        return "payment_method_retry"
    
    def _handle_phone_number(self, phone: str, message: str, session: Dict) -> str:
        """Handle payment phone number and initiate payment."""
        # This delegates to the existing payment processing in donationflow
        # We'll save the formatted number and let the existing handler take over
        
        raw = message.strip()
        
        if raw.startswith("0") and len(raw) == 10:
            formatted = "263" + raw[1:]
        elif raw.startswith("263") and len(raw) == 12:
            formatted = raw
        else:
            whatsapp.send_message(
                " Invalid number format.\n"
                "Use *0771234567* or *263771234567*:",
                phone
            )
            return "phone_retry"
        
        session["data"]["payment_phone"] = formatted
        
        # Save user profile for future quick donations (this is OK - just saves name/congregation)
        self.conversation.save_user_from_session(phone, session["data"])
        
        # NOTE: Do NOT update donation stats here!
        # Stats should ONLY be updated after Paynow confirms payment as "paid"
        # The background polling in donationflow.py handles this correctly
        
        # Hand off to payment processor
        # For now, send confirmation and set step for existing handler
        session["step"] = "payment_number"
        session["data"]["phone"] = formatted
        save_session(phone, session["step"], session["data"])
        
        # Import and call the existing payment handler
        try:
            from services.donationflow import handle_payment_number_step
            return handle_payment_number_step(phone, formatted, session)
        except Exception as e:
            logger.error(f"Payment initiation error: {e}")
            whatsapp.send_message(
                " There was an error initiating your payment.\n"
                "Please try again or contact support.",
                phone
            )
            return "payment_error"
    
    # ========================================================================
    # REGISTRATION FLOW
    # ========================================================================
    
    def _handle_registration_info(self, phone: str, message: str, session: Dict) -> str:
        """Handle combined registration info."""
        # Parse "name, congregation, email, skill" format
        parts = [p.strip() for p in message.replace(" and ", ", ").split(",") if p.strip()]
        
        if len(parts) >= 4:
            session["data"]["name"] = parts[0].title()
            session["data"]["region"] = self._normalize_congregation(parts[1])
            session["data"]["email"] = parts[2].lower()
            session["data"]["skill"] = parts[3].title()
            
            # Save registration
            try:
                import sqlite3
                conn = sqlite3.connect("botdata.db", timeout=10)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO volunteers 
                    (name, phone, email, skill, area, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    session["data"]["name"],
                    phone,
                    session["data"]["email"],
                    session["data"]["skill"],
                    session["data"]["region"],
                    datetime.now().isoformat()
                ))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Registration save error: {e}")
            
            # Also save to user profile
            profile = self.memory.get_profile(phone) or UserProfile(phone=phone)
            profile.name = session["data"]["name"]
            profile.congregation = session["data"]["region"]
            profile.email = session["data"]["email"]
            self.memory.save_profile(profile)
            
            # Clear session
            delete_session(phone)
            
            whatsapp.send_message(
                f" *Registration Complete!*\n\n"
                f"Welcome, *{session['data']['name']}*!\n\n"
                f" *Your Details:*\n"
                f"• Congregation: {session['data']['region']}\n"
                f"• Email: {session['data']['email']}\n"
                f"• Skill: {session['data']['skill']}\n\n"
                f"Thank you for volunteering! We'll be in touch. \n\n"
                f"_Type *menu* to donate or get help._",
                phone
            )
            return "registration_complete"
        
        else:
            whatsapp.send_message(
                "Please provide all details in one message:\n"
                "• Name, Congregation, Email, Skill\n\n"
                "_Example: John Moyo, Harare, john@email.com, IT Support_",
                phone
            )
            return "registration_retry"
    
    # ========================================================================
    # UTILITIES
    # ========================================================================
    
    def _normalize_congregation(self, name: str) -> str:
        """Normalize congregation name."""
        if not name:
            return name
        
        normalized = name.strip().title()
        
        # Remove common suffixes
        suffixes = [" Congregation", " Church", " Assembly", " Chapel", " Parish"]
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        
        return normalized
    
    def _handle_cancel(self, phone: str) -> str:
        """Handle cancellation."""
        delete_session(phone)
        whatsapp.send_message(
            " *Cancelled*\n\n"
            "No worries! Type *menu* whenever you're ready to start again.\n\n"
            "Have a blessed day! ",
            phone
        )
        return "cancelled"
    
    def _send_help(self, phone: str) -> str:
        """Send help message."""
        whatsapp.send_message(
            " *LatterPay Help*\n"
            "\n\n"
            "*Quick Commands:*\n"
            "• *menu* - Show main menu\n"
            "• *donate* - Start a donation\n"
            "• *check* - Check payment status\n"
            "• *register* - Register as volunteer\n"
            "• *cancel* - Cancel current action\n"
            "• *help* - Show this help\n\n"
            "*Quick Donate:*\n"
            "You can also say things like:\n"
            "_\"donate 50 for conference\"_\n"
            "_\"100 monthly contribution\"_\n\n"
            "*Need Support?*\n"
            "Contact: nyashamapetere@gmail.com\n\n",
            phone
        )
        return "help_sent"
    
    def _handle_check_status(self, phone: str, session: Dict) -> str:
        """Handle payment status check."""
        # Check both places where poll_url might be stored
        poll_url = session.get("poll_url") or session.get("data", {}).get("poll_url")
        data = session.get("data", {})
        
        if poll_url:
            # There's a pending payment - check its status
            try:
                from services.config import paynow_config
                from paynow import Paynow
                
                currency = data.get("currency", "ZWG")
                int_id, int_key = paynow_config.get_integration(currency)
                paynow_client = Paynow(int_id, int_key, paynow_config.return_url, paynow_config.result_url)
                
                status_obj = paynow_client.check_transaction_status(poll_url)
                status = status_obj.status.lower() if status_obj else "unknown"
                
                if status == "paid":
                    whatsapp.send_message(
                        "Payment confirmed!\n\n"
                        f"Amount: {data.get('currency', 'ZWG')}${float(data.get('amount', 0)):.2f}\n"
                        f"Purpose: {data.get('donation_type', 'Donation')}\n\n"
                        "Thank you for your contribution!",
                        phone
                    )
                    delete_session(phone)
                    return "payment_confirmed"
                    
                elif status in ["sent", "pending", "awaiting delivery"]:
                    enhanced_whatsapp.send_interactive_buttons(
                        to=phone,
                        body="Payment is still pending.\n\nPlease approve the payment on your phone.",
                        buttons=[
                            {"id": "check_again", "title": "Check Again"},
                            {"id": "retry_payment", "title": "Retry Payment"},
                            {"id": "start_over", "title": "Start Over"}
                        ],
                        header="Payment Pending"
                    )
                    return "payment_pending"
                    
                elif status in ["cancelled", "failed"]:
                    enhanced_whatsapp.send_interactive_buttons(
                        to=phone,
                        body=f"Payment {status}.\n\nWould you like to try again?",
                        buttons=[
                            {"id": "retry_payment", "title": "Retry Payment"},
                            {"id": "start_over", "title": "Start Over"}
                        ],
                        header="Payment Failed"
                    )
                    return "payment_failed"
                else:
                    whatsapp.send_message(
                        f"Payment status: {status}\n\n"
                        "Type *check* again or *menu* to start over.",
                        phone
                    )
                    return "payment_status_unknown"
                    
            except Exception as e:
                logger.error(f"Failed to check payment status: {e}")
                enhanced_whatsapp.send_interactive_buttons(
                    to=phone,
                    body="Could not check payment status.\n\nWhat would you like to do?",
                    buttons=[
                        {"id": "check_again", "title": "Try Again"},
                        {"id": "start_over", "title": "Start Over"}
                    ],
                    header="Error"
                )
                return "status_check_failed"
        else:
            # No pending payment
            enhanced_whatsapp.send_interactive_buttons(
                to=phone,
                body="No pending payments found.",
                buttons=[
                    {"id": "action_donate", "title": "Make Donation"},
                    {"id": "action_help", "title": "Help"}
                ],
                header="No Payments"
            )
            return "no_pending_payment"
    
    def _handle_unknown(self, phone: str, message: str, session: Dict) -> str:
        """Handle unknown state."""
        logger.warning(f"Unknown state for {phone}: {session.get('step')}")
        session["step"] = "start"
        save_session(phone, "start", {})
        return self._handle_start(phone, message, session)


# Global instance
streamlined_flow = StreamlinedFlow()

__all__ = ['StreamlinedFlow', 'streamlined_flow']
