from flask import Flask, request, jsonify
from datetime import datetime
import os
import json
import sys
import logging
from dotenv import load_dotenv
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, sessions, PAYMENTS_FILE
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

# Initialize logging
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
    logger.info("Home endpoint accessed")
    return "WhatsApp Donation Service is running"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    print("\n=== NEW REQUEST ===")
    print("Method:", request.method)
    print("Headers:", dict(request.headers))
    print("Args:", dict(request.args))
    
    if request.method == "POST":
        print("Raw body:", request.data)
        try:
            data = request.get_json()
            print("Parsed JSON:", data)
        except Exception as e:
            print("JSON parse error:", e)
    
    return jsonify({"status": "received"}), 200

def process_whatsapp_message(data):
    """Handle incoming WhatsApp messages"""
    try:
        phone = whatsapp.get_mobile(data)
        name = whatsapp.get_name(data)
        msg = whatsapp.get_message(data).strip()
        
        logger.info(f"New message from {phone} ({name}): {msg}")

        # Admin commands
        if phone == os.getenv("ADMIN_PHONE"):
            logger.info("Processing admin command")
            return AdminService.handle_admin_command(phone, msg) or jsonify({"status": "processed"}), 200

        # Session management
        if check_session_timeout(phone):
            logger.info(f"Session timeout for {phone}")
            return jsonify({"status": "session timeout"}), 200

        if msg.lower() == "cancel":
            logger.info(f"Cancelling session for {phone}")
            cancel_session(phone)
            return jsonify({"status": "session cancelled"}), 200

        if phone not in sessions:
            logger.info(f"Initializing new session for {phone}")
            initialize_session(phone, name)
            return jsonify({"status": "new session started"}), 200

        # Update session and process message
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
            logger.info(f"Processing step '{session['step']}' for {phone}")
            return step_handlers[session["step"]](phone, msg, session)

        logger.error(f"Invalid session step for {phone}: {session['step']}")
        return jsonify({"status": "error", "message": "Invalid session step"}), 400

    except Exception as e:
        logger.error(f"Message processing error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port,threaded=True,request_timeout=60)