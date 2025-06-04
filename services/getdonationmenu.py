from datetime import datetime
import json
from services import  config


def get_donation_menu():
    # Load standard options
    # Load and add custom options
    try:
        with open(config.CUSTOM_TYPES_FILE, "r") as f:
            custom_types = json.load(f)
        
        now = datetime.now()
        for i, item in enumerate(custom_types, start=5):
            if item["expires"] is None or datetime.fromisoformat(item["expires"]) > now:
                config.menu.append(f"{i}. _*{item['description']}*_")
                
    except Exception as e:
        print(f"Error loading custom types: {e}")
    
    return "\n".join(config.menu)



