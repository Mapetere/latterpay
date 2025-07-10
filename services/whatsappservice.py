import os
import sys
import json
from pathlib import Path
import requests
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)


load_dotenv()  

class WhatsAppService:


    API_URL = os.getenv("WHATSAPP_API_URL")
    HEADERS = {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_ACCESS_TOKEN')}",
        "Content-Type": "application/json"
    }

    @staticmethod
    def send_interactive_buttons(phone_number, template_name, context=None):
        """Send interactive buttons via WhatsApp API"""
        template_path = Path(f"templates/{template_name}.json")
        
        try:
            with open(template_path) as f:
                payload = json.load(f)
            
            payload["to"] = phone_number
            
            if context:
                for key, value in context.items():
                    if "interactive" in payload and "body" in payload["interactive"]:
                        payload["interactive"]["body"]["text"] = payload["interactive"]["body"]["text"].replace(
                            f"{{{{{key}}}}}", 
                            str(value)
                        )
            
            response = requests.post(
                WhatsAppService.API_URL,
                headers=WhatsAppService.HEADERS,
                json=payload
            )
            
            response.raise_for_status()  # Raise exception for bad status codes
            return response.json()
            
        except FileNotFoundError:
            raise Exception(f"Template file not found: {template_path}")
        except json.JSONDecodeError:
            raise Exception(f"Invalid JSON in template: {template_path}")
        except requests.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
        

    # services/whatsapp_menu.py

# services/whatsapp_menu.py
from services.pygwan_whatsapp import whatsapp  # This should be the WhatsApp instance

# services/whatsapp_menu.py

from services.pygwan_whatsapp import whatsapp

def send_main_menu(phone):
    try:
        logger.info(f"Sending pygwan button menu to {phone}")

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "text",
                    "text": "📍 Main Menu"
                },
                "body": {
                    "text": "Hi there! 👋\nPlease choose an option below:"
                },
                "footer": {
                    "text": "LatterPay Bot"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "register_btn",
                                "title": "📝 Register"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "payment_btn",
                                "title": "💸 Make payment"
                            }
                        }
                    ]
                }
            }
        }

        whatsapp.send_button(payload, phone)
    except Exception as e:
        logger.error(f"❌ Failed to send pygwan menu to {phone}: {e}")
