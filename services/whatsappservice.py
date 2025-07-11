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
        button_payload = {
            "header": "Good day!",  # Optional header
            "body": "Select how I may help you today:",  # REQUIRED string (not dict!)
            "footer": "Runde Rural Clinic",  # Optional footer
            "action": {
                "buttons": [  # List of buttons (max 3)
                    {
                        "type": "reply",
                        "reply": {
                            "id": "register_clinic",
                            "title": "Register to Runde Rural Clinic"  # Max 20 chars
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "make_payment",
                            "title": "Make a payment"  # Max 20 chars
                        }
                    }
                ]
            }
        }

        response = whatsapp.send_button(
            button=button_payload,
            recipient_id=phone
        )
        return response
    except Exception as e:
        logger.error(f"❌ Failed to send pygwan menu to {phone}: {e}")
