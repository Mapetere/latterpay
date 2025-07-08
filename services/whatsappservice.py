import requests
import json
from pathlib import Path
from latterpay import WHATSAPP_API_URL, headers
from services.pygwan_whatsapp import whatsapp

class WhatsAppService:
    @staticmethod
    def send_interactive_buttons(phone_number, template_name, context=None):
        template_path = Path(f"templates/{template_name}.json")
        with open(template_path) as f:
            payload = json.load(f)
        
        payload["to"] = phone_number
        if context:
            for key, value in context.items():
                payload["interactive"]["body"]["text"] = payload["interactive"]["body"]["text"].replace(f"{{{{{key}}}}}", str(value))
        
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
        return response