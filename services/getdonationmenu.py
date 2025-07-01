from datetime import datetime
import json
from services.config import CUSTOM_TYPES_FILE, menu


def get_donation_menu():
    # Load standard options
    # Load and add custom options
    try:
        with open(CUSTOM_TYPES_FILE, "r") as f:
            custom_types = json.load(f)
        
        now = datetime.now()
        for i, item in enumerate(custom_types, start=6):
            if item["expires"] is None or datetime.fromisoformat(item["expires"]) > now:
                menu.append(f"{i}. _*{item['description']}*_")
                
    except Exception as e:
        print(f"Error loading custom types: {e}")
    
    return "\n".join(menu)

def validate_donation_choice(choice, max_options):
    """Validate user's donation type selection"""
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= max_options:
            return True, choice_num
        return False, f"Please select between 1-{max_options}"
    except ValueError:
        return False, "Please enter a valid number"

