import services.config as config
from datetime import datetime
import json

def cleanup_expired_donation_types():
    try:
        with open(config.CUSTOM_TYPES_FILE, "r") as f:
            custom_types = json.load(f)
        
        # Filter out expired types
        valid_types = []
        now = datetime.now()
        
        for item in custom_types:
            if item["expires"] is None:  # Forever
                valid_types.append(item)
            else:
                expires = datetime.fromisoformat(item["expires"])
                if expires > now:
                    valid_types.append(item)
        
        # Save back if anything was removed
        if len(valid_types) < len(custom_types):
            with open(config.CUSTOM_TYPES_FILE, "w") as f:
                json.dump(valid_types, f)
            
    except Exception as e:
        print(f"Error cleaning up donation types: {e}")