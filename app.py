from flask import Flask, request
from datetime import datetime
import requests
import os
import json
import sys
import logging
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

# Initialize logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)

load_dotenv()

# Initialize data files
if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)

app = Flask(__name__)

@app.route("/")
def home():
    logging.info("Home route hit!")
    return "App is alive!"

@app.route("/debug")
def debug():
    return f"Token: {os.getenv('VERIFY_TOKEN')}"

@app.route("/test-log")
def test_log():
    print("This is a test print message", flush=True)
    logging.info("This is a test log message via logging")
    return "Check your logs for test messages"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    logging.info(f"{request.method} request received at /webhook")
    
    try:
        if request.method == "GET": 
            logging.debug(f"GET request headers: {request.headers}")
            verify_token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            expected_token = os.getenv("VERIFY_TOKEN")
            
            logging.debug(f"Verify token from WhatsApp: {verify_token}")
            logging.debug(f"Expected token from ENV: {expected_token}")
            
            if verify_token == expected_token:
                logging.info("Verify token match successful")
                return challenge, 200
            else:
                logging.warning("Verify token mismatch")
                return "Invalid verify token", 403

        elif request.method == "POST":
            logging.debug(f"POST request headers: {request.headers}")
            logging.debug(f"Raw POST data: {request.data}")
            
            # Verify WhatsApp signature if implemented
            if hasattr(whatsapp, 'verify_signature'):
                signature = request.headers.get('X-Hub-Signature-256', '')
                if not whatsapp.verify_signature(request.data, signature):
                    logging.error("Invalid signature - possible unauthorized request")
                    return "Invalid signature", 401
            
            data = request.get_json()
            logging.info(f"Incoming webhook POST data: {data}")
            
            if not data:
                logging.warning("No JSON data received or failed to parse")
                return "ok", 200

            # Skip if not a message
            if not whatsapp.is_message(data):
                logging.debug("Not a message, skipping")
                return "ok", 200

            phone = whatsapp.get_mobile(data)
            name = whatsapp.get_name(data)
            msg = whatsapp.get_message(data).strip()
            logging.info(f"Processing message from {phone} ({name}): {msg}")

            # Admin commands
            if phone == os.getenv("ADMIN_PHONE"):
                logging.info("Admin message detected")
                return AdminService.handle_admin_command(phone, msg) or "ok"

            if check_session_timeout(phone):
                logging.info(f"Session timeout for {phone}")
                return "ok", 200

            if msg.lower() == "cancel":
                logging.info(f"Cancelling session for {phone}")
                cancel_session(phone)
                return "ok", 200

            if phone not in sessions:
                logging.info(f"Initializing new session for {phone}")
                initialize_session(phone, name)
                return "ok", 200

            sessions[phone]["last_active"] = datetime.now()
            session = sessions[phone]
            logging.debug(f"Current session for {phone}: {session}")

            step_handlers = {
                "name": handle_name_step,
                "amount": handle_amount_step,
                "donation_type": handle_donation_type_step,
                "other_donation_details": handle_other,
                "region": handle_region_step,
                "note": handle_note_step
            }

            if session["step"] in step_handlers:
                logging.info(f"Handling step '{session['step']}' for {phone}")
                return step_handlers[session["step"]](phone, msg, session)

            logging.error(f"Invalid session step for {phone}: {session['step']}")
            return "Invalid session step", 400

    except Exception as e:
        logging.error(f"Error in webhook: {str(e)}", exc_info=True)
        return "fail", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"🌍 Flask app running on port {port}")
    app.run(host="0.0.0.0", port=port)