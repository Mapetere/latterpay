from flask import Flask, request
from flask import Flask, request
from datetime import datetime
import requests
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
from services.cleanup import cleanup_expired_donation_types
from services.setup import setup_scheduled_reports

load_dotenv()

# Initialize data files
if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

#Intialize payments file if it doesn't exist
if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)




try:
    app = Flask(__name__)
except Exception as e:
    print(f"[ERROR INIT FLASK] {e}")

@app.route("/")
def home():
    print("[INFO] Home route hit!")
    return "App is alive!"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    try:
        if request.method == "GET":
            if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
                return request.args.get("hub.challenge")
            return "Invalid verify token", 403

        if request.method == "POST":
            print("[DEBUG] Got POST")
            print(request.get_json())

            
            data = request.get_json()
            if not data:
                print("[WARN] No JSON received")
                return "ok"

            # Skip if not a message
            if not whatsapp.is_message(data):
                return "ok"

            phone = whatsapp.get_mobile(data)
            name = whatsapp.get_name(data)
            msg = whatsapp.get_message(data).strip()

            # Admin commands
            if phone == os.getenv("ADMIN_PHONE"):
                return AdminService.handle_admin_command(phone, msg) or "ok"

            if check_session_timeout(phone):
                return "ok"

            if msg.lower() == "cancel":
                cancel_session(phone)
                return "ok"

            if phone not in sessions:
                initialize_session(phone, name)
                return "ok"

            sessions[phone]["last_active"] = datetime.now()
            session = sessions[phone]

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

    except Exception as e:
        print(f"[ERROR IN WEBHOOK] {e}")
        return "fail", 500

    



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🌍 Flask app running on port {port}")
    app.run(host="0.0.0.0", port=port)

