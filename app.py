from flask import Flask, request
from datetime import datetime
import os
import json
from dotenv import load_dotenv
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, sessions, PAYMENTS_FILE, donation_types as DONATION_TYPES
from services.sessions import (
    check_session_timeout,
    cancel_session,
    initialize_session
)
from services.donationflow import (
    handle_other,
    handle_name_step,
    handle_amount_step,
    handle_donation_type_step,
    handle_region_step,
    handle_note_step  
)
from services.adminservice import AdminService

load_dotenv()

app = Flask(__name__)

# Initialize data files
if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

#Intialize payments file if it doesn't exist
if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)



@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
            return request.args.get("hub.challenge")
        return "Invalid verify token", 403
    
    print("[WEBHOOK] POST triggered")
    data = request.get_json()
    
   

    # Skip if not a message
    if not whatsapp.is_message(data):
        return "ok"

    phone = whatsapp.get_mobile(data)
    name = whatsapp.get_name(data)
    msg = whatsapp.get_message(data).strip()

   
    # Handle admin commands
    if phone == os.getenv("ADMIN_PHONE"):
        return AdminService.handle_admin_command(phone, msg) or "ok"

    # Check session timeout
    if check_session_timeout(phone):
        return "ok"

    # Handle cancellation
    if msg.lower() == "cancel":
        cancel_session(phone)
        return "ok"

    # Initialize new session
    if phone not in sessions:
        initialize_session(phone, name)
        
    
    # Update session activity
    sessions[phone]["last_active"] = datetime.now()
    session = sessions[phone]

    # Route through session steps
    step_handlers = {
        "name": handle_name_step,
        "amount": handle_amount_step,
        "donation_type": handle_donation_type_step,
        "other_donation_details": handle_other,
        "region": handle_region_step,
        "note": handle_note_step
    }

    if session["step"] in step_handlers:
        
        return step_handlers[session["step"]](phone, msg, session)
    
    return "Invalid session step", 400

   

if __name__ == "__main__":
    from services.cleanup import cleanup_expired_donation_types
    from services.setup import setup_scheduled_reports


    cleanup_expired_donation_types()
    setup_scheduled_reports()
    app.run(port=5000, debug=True)
