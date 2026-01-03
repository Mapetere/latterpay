"""
Enhanced WhatsApp Service with Interactive Messages
====================================================
Extended WhatsApp service that supports:
- Interactive buttons and lists
- Quick replies
- Template messages
- Rich media
- Voice note transcription (future)

Author: Nyasha Mapetere
Version: 3.0.0
"""

import os
import json
import logging
import requests
from typing import Dict, List, Optional, Union
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class EnhancedWhatsApp:
    """
    Enhanced WhatsApp Cloud API client with interactive message support.
    """
    
    def __init__(self):
        self.token = os.getenv("WHATSAPP_TOKEN", "")
        self.phone_number_id = os.getenv("PHONE_NUMBER_ID", "")
        self.api_version = "v18.0"
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def _send_request(self, payload: Dict) -> Dict:
        """Send a request to WhatsApp API."""
        try:
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Message sent successfully: {result.get('messages', [{}])[0].get('id', 'unknown')}")
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"WhatsApp API error: {e}")
            return {"error": str(e)}
    
    def send_text(self, to: str, text: str) -> Dict:
        """Send a simple text message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text}
        }
        return self._send_request(payload)
    
    # Logo URL - wide horizontal banner for WhatsApp message headers
    LOGO_URL = os.getenv(
        "LATTERPAY_LOGO_URL", 
        "https://latterpay-production.up.railway.app/static/latterpay_header.png"
    )
    
    def send_interactive_buttons(
        self,
        to: str,
        body: str,
        buttons: List[Dict[str, str]],
        header: str = None,
        header_image_url: str = None,
        footer: str = None
    ) -> Dict:
        """
        Send interactive button message.
        
        Args:
            to: Recipient phone number
            body: Main message body
            buttons: List of dicts with 'id' and 'title' keys (max 3)
            header: Optional header text (ignored if header_image_url is set)
            header_image_url: Optional header image URL
            footer: Optional footer text
        """
        interactive = {
            "type": "button",
            "body": {"text": body[:1024]},  # Max 1024 chars
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn.get("id", f"btn_{i}")[:256],
                            "title": btn["title"][:20]  # Max 20 chars
                        }
                    }
                    for i, btn in enumerate(buttons[:3])
                ]
            }
        }
        
        # Image header takes priority over text header
        if header_image_url:
            interactive["header"] = {
                "type": "image",
                "image": {"link": header_image_url}
            }
        elif header:
            interactive["header"] = {"type": "text", "text": header[:60]}  # Max 60 chars
        
        if footer:
            interactive["footer"] = {"text": footer[:60]}
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive
        }
        
        logger.debug(f"Sending interactive buttons to {to}")
        return self._send_request(payload)
    
    def send_interactive_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: List[Dict],
        header: str = None,
        footer: str = None
    ) -> Dict:
        """
        Send interactive list message.
        
        Args:
            to: Recipient phone number  
            body: Main message body
            button_text: Text on the list button
            sections: List of section dicts with 'title' and 'rows'
            header: Optional header text
            footer: Optional footer text
        """
        interactive = {
            "type": "list",
            "body": {"text": body[:1024]},
            "action": {
                "button": button_text[:20],
                "sections": sections[:10]  # Max 10 sections
            }
        }
        
        if header:
            interactive["header"] = {"type": "text", "text": header[:60]}
        if footer:
            interactive["footer"] = {"text": footer[:60]}
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive
        }
        
        logger.debug(f"Sending interactive list to {to}")
        return self._send_request(payload)
    
    # ========================================================================
    # PRE-BUILT INTERACTIVE MESSAGES
    # ========================================================================
    
    def send_main_menu(self, to: str, greeting: str, show_logo: bool = True) -> Dict:
        """Send the main menu with action buttons and optional logo."""
        return self.send_interactive_buttons(
            to=to,
            body=greeting + "\n\nWhat would you like to do?",
            buttons=[
                {"id": "action_donate", "title": "Donate"},
                {"id": "action_register", "title": "Register"},
                {"id": "action_help", "title": "Help"}
            ],
            header_image_url=self.LOGO_URL if show_logo else None,
            header=None if show_logo else "LatterPay",
            footer="Tap a button to continue"
        )
    
    def send_donation_purposes(self, to: str, congregation: str = None) -> Dict:
        """Send donation purpose selection as a list."""
        sections = [{
            "title": "Donation Categories",
            "rows": [
                {
                    "id": "purpose_monthly",
                    "title": "Monthly Contributions",
                    "description": "Regular monthly support"
                },
                {
                    "id": "purpose_august",
                    "title": "August Conference",
                    "description": "Annual conference fund"
                },
                {
                    "id": "purpose_youth",
                    "title": "Youth Conference",
                    "description": "Youth ministry support"
                },
                {
                    "id": "purpose_construction",
                    "title": "Construction",
                    "description": "Building and infrastructure"
                },
                {
                    "id": "purpose_pastoral",
                    "title": "Pastoral Support",
                    "description": "Support our pastors"
                },
                {
                    "id": "purpose_other",
                    "title": "Other",
                    "description": "Specify your own purpose"
                }
            ]
        }]
        
        # Build body with congregation confirmation if provided
        if congregation:
            body = f"Congregation recorded: *{congregation}*\n\nNext step: Select donation purpose"
        else:
            body = "What would you like to contribute towards?\n\nSelect a purpose from the list below:"
        
        return self.send_interactive_list(
            to=to,
            body=body,
            button_text="Choose Purpose",
            sections=sections,
            header="Donation Purpose"
        )
    
    def send_congregation_list(self, to: str, name: str = None) -> Dict:
        """Send province/region selection first."""
        sections = [{
            "title": "Select Your Province",
            "rows": [
                {"id": "province_harare", "title": "Harare Metropolitan"},
                {"id": "province_bulawayo", "title": "Bulawayo Metropolitan"},
                {"id": "province_mashonaland_east", "title": "Mashonaland East"},
                {"id": "province_mashonaland_west", "title": "Mashonaland West"},
                {"id": "province_mashonaland_central", "title": "Mashonaland Central"},
                {"id": "province_midlands", "title": "Midlands"},
                {"id": "province_masvingo", "title": "Masvingo"},
                {"id": "province_manicaland", "title": "Manicaland"},
                {"id": "province_matebeleland_north", "title": "Matabeleland North"},
                {"id": "province_matebeleland_south", "title": "Matabeleland South"},
            ]
        }]
        
        if name:
            body = f"Name recorded: *{name}*\n\nNext step: Select your province"
        else:
            body = "Please select your province:"
        
        return self.send_interactive_list(
            to=to,
            body=body,
            button_text="Choose Province",
            sections=sections,
            header="Select Province"
        )
    
    def send_cities_for_province(self, to: str, province: str) -> Dict:
        """Send cities list for the selected province."""
        province_cities = {
            "province_harare": [
                {"id": "city_harare_central", "title": "Harare Central"},
                {"id": "city_harare_north", "title": "Harare North"},
                {"id": "city_harare_south", "title": "Harare South"},
                {"id": "city_chitungwiza", "title": "Chitungwiza"},
                {"id": "city_epworth", "title": "Epworth"},
                {"id": "city_norton", "title": "Norton"},
                {"id": "city_ruwa", "title": "Ruwa"},
            ],
            "province_bulawayo": [
                {"id": "city_bulawayo_central", "title": "Bulawayo Central"},
                {"id": "city_bulawayo_north", "title": "Bulawayo North"},
                {"id": "city_bulawayo_south", "title": "Bulawayo South"},
                {"id": "city_bulawayo_west", "title": "Bulawayo West"},
            ],
            "province_mashonaland_east": [
                {"id": "city_marondera", "title": "Marondera"},
                {"id": "city_ruwa", "title": "Ruwa"},
                {"id": "city_mutoko", "title": "Mutoko"},
                {"id": "city_mudzi", "title": "Mudzi"},
                {"id": "city_uzumba", "title": "Uzumba"},
            ],
            "province_mashonaland_west": [
                {"id": "city_chinhoyi", "title": "Chinhoyi"},
                {"id": "city_kadoma", "title": "Kadoma"},
                {"id": "city_chegutu", "title": "Chegutu"},
                {"id": "city_karoi", "title": "Karoi"},
                {"id": "city_norton", "title": "Norton"},
            ],
            "province_mashonaland_central": [
                {"id": "city_bindura", "title": "Bindura"},
                {"id": "city_mt_darwin", "title": "Mt Darwin"},
                {"id": "city_shamva", "title": "Shamva"},
                {"id": "city_mvurwi", "title": "Mvurwi"},
                {"id": "city_centenary", "title": "Centenary"},
            ],
            "province_midlands": [
                {"id": "city_gweru", "title": "Gweru"},
                {"id": "city_kwekwe", "title": "Kwekwe"},
                {"id": "city_zvishavane", "title": "Zvishavane"},
                {"id": "city_shurugwi", "title": "Shurugwi"},
                {"id": "city_gokwe", "title": "Gokwe"},
                {"id": "city_redcliff", "title": "Redcliff"},
            ],
            "province_masvingo": [
                {"id": "city_masvingo", "title": "Masvingo"},
                {"id": "city_chiredzi", "title": "Chiredzi"},
                {"id": "city_triangle", "title": "Triangle"},
                {"id": "city_gutu", "title": "Gutu"},
            ],
            "province_manicaland": [
                {"id": "city_mutare", "title": "Mutare"},
                {"id": "city_chipinge", "title": "Chipinge"},
                {"id": "city_rusape", "title": "Rusape"},
                {"id": "city_nyanga", "title": "Nyanga"},
                {"id": "city_chimanimani", "title": "Chimanimani"},
            ],
            "province_matebeleland_north": [
                {"id": "city_victoria_falls", "title": "Victoria Falls"},
                {"id": "city_hwange", "title": "Hwange"},
                {"id": "city_lupane", "title": "Lupane"},
                {"id": "city_binga", "title": "Binga"},
            ],
            "province_matebeleland_south": [
                {"id": "city_gwanda", "title": "Gwanda"},
                {"id": "city_beitbridge", "title": "Beitbridge"},
                {"id": "city_plumtree", "title": "Plumtree"},
                {"id": "city_filabusi", "title": "Filabusi"},
            ],
        }
        
        cities = province_cities.get(province, [{"id": "city_other", "title": "Other"}])
        
        sections = [{
            "title": "Select Your City/Congregation",
            "rows": cities
        }]
        
        return self.send_interactive_list(
            to=to,
            body="Now select your city or congregation:",
            button_text="Choose City",
            sections=sections,
            header="Select City"
        )
    
    def send_payment_methods(self, to: str) -> Dict:
        """Send payment method selection buttons."""
        return self.send_interactive_buttons(
            to=to,
            body="Select your preferred payment method:",
            buttons=[
                {"id": "pay_ecocash", "title": " EcoCash"},
                {"id": "pay_onemoney", "title": " OneMoney"},
                {"id": "pay_innbucks", "title": " InnBucks"}
            ],
            header=" Payment Method"
        )
    
    def send_currency_selection(self, to: str) -> Dict:
        """Send currency selection buttons."""
        return self.send_interactive_buttons(
            to=to,
            body="Which currency would you like to use?",
            buttons=[
                {"id": "currency_usd", "title": " USD"},
                {"id": "currency_zwg", "title": " ZWG"}
            ],
            header=" Select Currency"
        )
    
    def send_confirmation(self, to: str, summary: str) -> Dict:
        """Send confirmation buttons with payment summary."""
        return self.send_interactive_buttons(
            to=to,
            body=summary,
            buttons=[
                {"id": "confirm_yes", "title": " Confirm"},
                {"id": "confirm_edit", "title": "️ Edit"},
                {"id": "confirm_cancel", "title": " Cancel"}
            ],
            header=" Confirm Payment"
        )
    
    def send_quick_donate_offer(self, to: str, profile_summary: str, show_logo: bool = True) -> Dict:
        """Offer quick donate option to returning users with optional logo."""
        return self.send_interactive_buttons(
            to=to,
            body=profile_summary,
            buttons=[
                {"id": "quick_yes", "title": " Quick Donate"},
                {"id": "quick_new", "title": "️ Diff. Congregation"},
                {"id": "quick_help", "title": " Help"}
            ],
            header_image_url=self.LOGO_URL if show_logo else None,
            header=None if show_logo else " Welcome Back!"
        )
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def parse_interactive_response(self, data: Dict) -> Optional[Dict]:
        """
        Parse an interactive button/list response from webhook data.
        
        Returns:
            Dict with 'type' ('button_reply' or 'list_reply') and 'id'/'title'
        """
        try:
            message = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0]
            
            if message.get("type") == "interactive":
                interactive = message.get("interactive", {})
                interactive_type = interactive.get("type")
                
                if interactive_type == "button_reply":
                    return {
                        "type": "button_reply",
                        "id": interactive.get("button_reply", {}).get("id"),
                        "title": interactive.get("button_reply", {}).get("title")
                    }
                elif interactive_type == "list_reply":
                    return {
                        "type": "list_reply",
                        "id": interactive.get("list_reply", {}).get("id"),
                        "title": interactive.get("list_reply", {}).get("title"),
                        "description": interactive.get("list_reply", {}).get("description")
                    }
            
            return None
        except Exception as e:
            logger.error(f"Error parsing interactive response: {e}")
            return None


# Global instance
enhanced_whatsapp = EnhancedWhatsApp()

__all__ = ['EnhancedWhatsApp', 'enhanced_whatsapp']
