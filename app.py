from flask import Flask, request, jsonify
from datetime import datetime
import os
import json
import sqlite3
from sqlite3 import OperationalError
from paynow import Paynow
import sys
import time
import logging
from dotenv import load_dotenv
import threading
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, PAYMENTS_FILE
from services.sessions import check_session_timeout, cancel_session, initialize_session,load_session,save_session,update_user_step
from services.donationflow import handle_user_message
from services.registrationflow import RegistrationFlow
from services.whatsappservice import WhatsAppService

from services.sessions import monitor_sessions





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


for file_path in [CUSTOM_TYPES_FILE, PAYMENTS_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            json.dump([], f)

latterpay = Flask(__name__)




def init_db():
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()

    # Sent Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_messages (
            msg_id TEXT PRIMARY KEY,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Known Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS known_users (
            phone TEXT PRIMARY KEY,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Sessions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            phone TEXT PRIMARY KEY,
            step TEXT,
            data TEXT,
            last_active TIMESTAMP
        )
    """)

    # Safely added the  'warned' column if it doesn't exist
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    if "warned" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN warned INTEGER DEFAULT 0")

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
    cursor.execute("DELETE FROM sent_messages WHERE sent_at < datetime('now', '-15 minutes')")
    conn.commit()
    conn.close()

def message_exists(msg_id):
    return is_echo_message(msg_id)


def cleanup_message_ids():
    def cleaner():
        while True:
            try:
                delete_old_ids()
                time.sleep(3600)  # every 10 minutes
            except Exception as e:
                logger.warning(f"[CLEANUP ERROR] {e}")
                time.sleep(600)

    threading.Thread(target=cleaner, daemon=True).start()


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
        logger.info("Paynow Result Received: \n" + raw_data)
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
            if verify_token == os.getenv("VERIFY_TOKEN"):
                logger.info("Webhook verified successfully!")
                return challenge, 200
            return "Verification failed", 403

        elif request.method == "POST":
            data = None

            if request.is_json:
                data = request.get_json()

                try:
                    changes = data["entry"][0]["changes"][0]["value"]
                    msg_data = changes.get("messages", [])[0]  # Might be empty if it's not a user message

                    if not msg_data:
                        return "ok"

                    msg_id = msg_data.get("id")
                    msg_from = msg_data.get("from")

                    # ✨ Echo check using message ID
                    if is_echo_message(msg_id):
                        print("🔁 Detected echo via DB. Ignoring.")
                        return "ok"

                    # Optional: echo fallback checks
                    if msg_data.get("echo"):
                        print("🔁 Detected echo=True. Ignoring.")
                        return "ok"

                    if msg_from == os.getenv("PHONE_NUMBER_ID") or msg_from == os.getenv("WHATSAPP_BOT_NUMBER"):
                        print("🔁 Message from own bot. Ignored.")
                        return "ok"

                    print("✅ Valid message received:", msg_data.get("text", {}).get("body"))
                    # Proceed with your session logic here...

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


            if data.get("type") == "DEPLOY":
                logging.info("Received Railway deployment notification")
                return jsonify({"status": "ignored"}), 200


            if isinstance(data, dict) and data.get('type') == 'DEPLOY':
                logging.info("Received Railway deployment notification")
                return jsonify({"status": "ignored"}), 200

         
            if not isinstance(data, dict):
                logging.warning("Skipping non-dictionary data")
                return jsonify({"status": "ignored"}), 200

            
            if whatsapp.is_message(data):
                logging.info("\n=== HANDLING WHATSAPP MESSAGE ===")
                phone = whatsapp.get_mobile(data)
                name = whatsapp.get_name(data)
                msg = whatsapp.get_message(data).strip()
                logging.info(f"New message from {phone} ({name}): '{msg}'")



            if not session:
                whatsapp.send_message(
                " You sent me a message!\n\n"
                "Welcome! What would you like to do?\n\n"
                "1️⃣ Register to Runde Rural Clinic Project\n"
                "2️⃣ Make payment\n\n"
                "Please reply with a number", phone)
                session = load_session(phone)
                save_session(phone, session["step"], session["data"])
                

                return jsonify({"status": "session initialized"}), 200


            if check_session_timeout(phone):
                return jsonify({"status": "session timeout"}), 200


            if msg.lower() == "cancel":
                cancel_session(phone)
                return jsonify({"status": "session cancelled"}), 200


            session["last_active"] = datetime.now()
            save_session(phone, session["step"], session["data"])


            if msg == "1":
                session["mode"] = "registration"
                session["step"] = "awaiting_name"
                save_session(phone, session["step"], session["data"])
                return jsonify({"status": "registration started"}), 200

            elif msg == "2":
                session["mode"] = "donation"
                session["step"] = "awaiting_amount"
                save_session(phone, session["step"], session["data"])
                return jsonify({"status": "donation started"}), 200
            
            else: 
                if not session.get("mode"):
                    whatsapp.send_message("❓ Please type *1* to Register or *2* to Donate.", phone)
                    return jsonify({"status": "awaiting valid option"}), 200


            # Route to appropriate flow based on current mode
            if session.get("mode") == "registration":
                return RegistrationFlow.start_registration(phone, msg)

            elif session.get("mode") == "donation":
                return whatsapp.send_message("Oops! Donation flow is not in use yet.\n"
                                             "Contact Nyasha on mapeterenyasha@gmail.com for any enquiries.", phone)



    except Exception as e:
        logger.error(f"Message processing error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    init_db()
    monitor_sessions()
    port = int(os.environ.get("PORT", 8010))
    logger.info(f"Starting server on port {port}")
    latterpay.run(host="0.0.0.0", port=port)
