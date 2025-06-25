from flask import Flask, request, jsonify 
from datetime import datetime
import os
import json
import sqlite3
from sqlite3 import OperationalError
from paynow import Paynow
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
from services.recordpaymentdata import record_payment
from services.setup import send_payment_report_to_finance
from services.donationflow import (
    handle_name_step,
    handle_amount_step,
    handle_donation_type_step,
    handle_region_step,
    handle_note_step,
    handle_confirmation_step,
    handle_editing_fields,
    handle_edit_command,
    handle_user_message,
    handle_payment_method_step,
    handle_payment_number_step,
    handle_awaiting_payment_step,
    ask_for_payment_method

                    
)
from services.adminservice import AdminService

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

if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)

latterpay = Flask(__name__)


def init_db():
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_messages (
        msg_id TEXT PRIMARY KEY,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()


def is_echo_message(msg_id):
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sent_messages WHERE msg_id = ?", (msg_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def save_sent_message_id(msg_id):
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO sent_messages (msg_id) VALUES (?)", (msg_id,))
    conn.commit()
    conn.close()


def delete_old_ids():
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
    DELETE FROM sent_messages WHERE sent_at < datetime('now', '-15 minutes')
    """)
    conn.commit()
    conn.close()



def ask_for_payment_number(phone):
    whatsapp.send_message(
        "📲 *Enter the mobile number you'd like to use for payment.*\n"
        "_Format: 077XXXXXXX or 26377XXXXXXX_",
        phone
    )


@latterpay.route("/")
def home():
    logger.info("Home endpoint accessed")
    return "WhatsApp Donation Service is running"


@latterpay.route("/payment-return")
def payment_return():
    return "<h2>Payment attempted. You may now return to WhatsApp.</h2>"



@latterpay.route("/payment-result", methods=["POST"])
def payment_result():
    try:
        raw_data = request.data.decode("utf-8")
        logger.info("📩 Paynow Result Received: \n" + raw_data)
        # Optionally parse and process here
        return "OK"
    except Exception as e:
        logger.error(f"❌ Error handling Paynow result: {e}")
        return "ERROR", 500



@latterpay.route("/webhook", methods=["GET", "POST"])
def webhook_debug():
    try:
        if request.method == "GET":
            verify_token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            expected_token = os.getenv("VERIFY_TOKEN")

            if verify_token == expected_token:
                logger.info("Webhook verified successfully!")
                return challenge, 200
            logger.error("Webhook verification failed!")
            return "Verification failed", 403

        elif request.method == "POST":
            data = None
            if request.is_json:
                data = request.get_json()

                
                try:
                    entry = data.get("entry", [])
                    if not entry:
                        logger.warning("No 'entry' in payload")
                        return "ok"

                    changes = entry[0].get("changes", [])
                    if not changes:
                        logger.warning("No 'changes' in entry")
                        return "ok"

                    value = changes[0].get("value", {})
                    msg_data = value.get("messages", [])[0] if value.get("messages") else None

                    if not msg_data:
                        logger.info("No user message detected (maybe status or delivery update). Ignored.")
                        return "ok"

                    msg_id = msg_data.get("id")
                    msg_from = msg_data.get("from")

                    if is_echo_message(msg_id):
                        logger.info(" Echo message detected. Ignored.")
                        save_sent_message_id(msg_id)
                        return "ok"

                    if msg_data.get("echo"):
                        logger.info(" Echo=True detected. Ignored.")
                        return "ok"

                    if msg_from in [os.getenv("PHONE_NUMBER_ID"), os.getenv("WHATSAPP_BOT_NUMBER")]:
                        logger.info(" Message from self. Ignored.")
                        return "ok"

                    logger.info("Valid message received: " + msg_data.get("text", {}).get("body", ""))

                    save_sent_message_id(msg_id)

                except (KeyError, IndexError, OperationalError) as e:
                    logging.error(f"Error processing webhook: {e}")
                    return "ok"
            else:
                try:
                    raw_data = request.data.decode("utf-8")
                    logging.info(f"Incoming RAW POST data: {raw_data}")
                    data = json.loads(raw_data)
                except Exception as decode_err:
                    logging.error(f"Failed to decode raw POST data: {decode_err}")
                    return jsonify({"status": "error", "message": "Invalid raw JSON"}), 400

            
            if data is None:
                logger.error("No valid JSON data received.")
                return jsonify({"status": "error", "message": "No data"}), 400

            if whatsapp.is_message(data):
                phone = whatsapp.get_mobile(data)
                name = whatsapp.get_name(data)
                msg = whatsapp.get_message(data).strip()

                if phone == os.getenv("ADMIN_PHONE"):
                    return AdminService.handle_admin_command(phone, msg) or jsonify({"status": "processed"}), 200

                if phone not in sessions:
                    initialize_session(phone, name)
                    return jsonify({"status": "session initialized"}), 200

                if check_session_timeout(phone):
                    return jsonify({"status": "session timeout"}), 200

                if msg.lower() == "cancel":
                    cancel_session(phone)
                    return jsonify({"status": "session cancelled"}), 200

                sessions[phone]["last_active"] = datetime.now()
                session = sessions[phone]
                
                step_handlers = {
                    "name": handle_name_step,
                    "amount": handle_amount_step,
                    "donation_type": handle_donation_type_step,
                    "region": handle_region_step,
                    "note": handle_note_step,
                    "awaiting_confirmation": handle_confirmation_step,
                    "awaiting_user_method": ask_for_payment_method,
                    "editing_fields": handle_editing_fields,
                    "awaiting_edit": handle_edit_command,
                    "payment_method": handle_payment_method_step,
                    "payment_number": handle_payment_number_step,
                    "awaiting_payment": handle_awaiting_payment_step
                }

                step = session.get("step")
                handler = step_handlers.get(step)

                if handler:
                    return handler(phone, msg, session)
                else:
                    # fallback: redirect to donationflow's state handler
                    return handle_user_message(phone, msg, session)

    except Exception as e:
        logger.error(f"Message processing error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500













if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8010))
    logger.info(f"Starting server on port {port}")
    latterpay.run(host="0.0.0.0", port=port)
