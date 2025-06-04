import config
import json
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta


def handle_admin_approval(admin_phone, msg):
    if msg.lower() == "cancel":
        return
    
    if msg.startswith("/approve"):
        try:
            parts = msg.split()
            user_phone = parts[1]
            duration = parts[2]
            
            # Load existing custom types
            with open(config.CUSTOM_TYPES_FILE, "r") as f:
                custom_types = json.load(f)
            
            # Find the pending request for this user
            user_session = config.sessions.get(user_phone, {})
            request_desc = user_session.get("data", {}).get("custom_donation_request")
            
            if not request_desc:
                config.whatsapp.send_message("❌ No pending request found for this user",config.admin_phone)
                return
            
            # Calculate expiration date
            if duration == "forever":
                expires = None
            elif "year" in duration:
                years = int(duration.replace("year", ""))
                expires = (datetime.now() + timedelta(days=years*365)).isoformat()
            else:
                config.whatsapp.send_message("❌ Invalid duration. Use like: 1year, 5years, or forever", config.admin_phone)
                return
            
            # Add to custom types
            new_type = {
                "description": request_desc,
                "added_by": user_phone,
                "approved_by": admin_phone,
                "approved_on": datetime.now().isoformat(),
                "expires": expires
            }
            
            custom_types.append(new_type)
            
            # Save back to file
            with open(config.CUSTOM_TYPES_FILE, "w") as f:
                json.dump(custom_types, f)
            
            # Notify user
            config.whatsapp.send_message(
                f"✅ Your donation type '{request_desc}' has been approved! "
                f"It will be available until {expires or 'forever'}.",
                user_phone
            )
            
            config.whatsapp.send_message("✅ Donation type approved successfully!",config.admin_phone)
            
        except Exception as e:
            config.whatsapp.send_message(f"❌ Error processing approval: {str(e)}", config.admin_phone)


