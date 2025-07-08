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
from services.sessions import check_session_timeout, cancel_session, initialize_session, load_session, save_session
from services.donationflow import handle_user_message
from services.sessions import monitor_sessions
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Util.Padding import pad, unpad
from base64 import b64decode, b64encode
from Crypto.PublicKey import RSA
import base64


SCREEN_RESPONSES = {
    "PERSONAL_INFO": {
        "screen": "PERSONAL_INFO",
        "data": {}
    },
    "TRAINING": {
        "screen": "TRAINING",
        "data": {}
    },
    "VOLUNTEER": {
        "screen": "VOLUNTEER",
        "data": {}
    },
    "SUMMARY": {
        "screen": "SUMMARY",
        "data": {}
    },
    "TERMS": {
        "screen": "TERMS",
        "data": {}
    },
    "SUCCESS": lambda flow_token, param_value: {
        "screen": "SUCCESS",
        "data": {
            "extension_message_response": {
                "params": {
                    "flow_token": flow_token,
                    "some_param_name": param_value
                }
            }
        }
    }
}


load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

latterpay = Flask(__name__)

# --- ENCRYPTION HELPERS --- #
def decrypt_payload(encrypted_payload_base64, aes_key, iv):
    encrypted_payload = base64.b64decode(encrypted_payload_base64)
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_data = unpad(cipher_aes.decrypt(encrypted_payload), AES.block_size)
    return decrypted_data.decode("utf-8")

def decrypt_aes_key(encrypted_key_b64, private_key_path, passphrase):
    with open(private_key_path, "rb") as key_file:
        private_key = RSA.import_key(key_file.read(), passphrase=passphrase)
        cipher_rsa = PKCS1_OAEP.new(private_key)
        decrypted_key = cipher_rsa.decrypt(base64.b64decode(encrypted_key_b64))
        return decrypted_key

def re_encrypt_payload(plaintext, aes_key, iv):
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
    encrypted = cipher_aes.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")

# --- DATABASE SETUP --- #
def init_db():
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_messages (
            msg_id TEXT PRIMARY KEY,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS known_users (
            phone TEXT PRIMARY KEY,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            phone TEXT PRIMARY KEY,
            step TEXT,
            data TEXT,
            last_active TIMESTAMP,
            warned INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS volunteers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            surname TEXT,
            phone TEXT,
            email TEXT,
            skill TEXT,
            area TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# --- UTILITY FUNCTIONS --- #
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

def cleanup_message_ids():
    def cleaner():
        while True:
            try:
                delete_old_ids()
                time.sleep(3600)
            except Exception as e:
                logger.warning(f"[CLEANUP ERROR] {e}")
                time.sleep(600)
    threading.Thread(target=cleaner, daemon=True).start()

# --- ROUTES --- #
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
                return challenge, 200
            return "Verification failed", 403

        if request.method == "POST":
            data = request.get_json(force=True)
            if not data:
                logger.warning("No JSON data received for processing.")
                return jsonify({"status": "error", "message": "No valid JSON received"}), 400

            # Try encrypted AES logic
            try:
                aes_key_b64 = data.get("aes_key")
                if aes_key_b64:
                    aes_key = decrypt_aes_key(
                        aes_key_b64,
                        "private.pem",
                        os.getenv("PRIVATE_KEY_PASSPHRASE")
                    )

                    # Assuming payload is in 'payload' field and is encrypted
                    encrypted_payload_b64 = data.get("payload")
                    if not encrypted_payload_b64:
                        return jsonify({"error": "Missing encrypted payload"}), 400

                    encrypted_payload = b64decode(encrypted_payload_b64)
                    cipher = AES.new(aes_key, AES.MODE_ECB)  # Use CBC if Meta docs require it
                    decrypted_bytes = unpad(cipher.decrypt(encrypted_payload), AES.block_size)
                    decrypted_data = json.loads(decrypted_bytes.decode('utf-8'))

                    action = decrypted_data.get("action")
                    flow_token = decrypted_data.get("flow_token", "UNKNOWN")

                    if action == "INIT":
                        response = SCREEN_RESPONSES["PERSONAL_INFO"]
                    elif action == "data_exchange":
                        param = decrypted_data.get("data", {}).get("some_param", "VOLUNTEER_OPTION_1")
                        response = SCREEN_RESPONSES["SUCCESS"](flow_token, param)
                    elif action == "BACK":
                        response = SCREEN_RESPONSES.get("SUMMARY", {"screen": "SUMMARY", "data": {}})
                    else:
                        logger.warning(f"Unknown action received: {action}")
                        response = SCREEN_RESPONSES.get("TERMS")

                    json_payload = json.dumps(response).encode('utf-8')
                    padded_payload = pad(json_payload, AES.block_size)
                    encrypted_response = cipher.encrypt(padded_payload)
                    encrypted_b64 = b64encode(encrypted_response).decode('utf-8')

                    return encrypted_b64, 200, {"Content-Type": "text/plain"}

            except Exception as e:
                logger.error(f"❌ Error handling encrypted webhook: {e}", exc_info=True)
                # Proceed to fallback if AES decryption fails

            # --- Fallback to normal (non-encrypted) WhatsApp webhook --- #
            try:
                entry = data.get("entry", [{}])[0]
                changes = entry.get("changes", [{}])[0]
                value = changes.get("value", {})
                msg_data = value.get("messages", [{}])[0] if value.get("messages") else None

                if not msg_data:
                    return "ok"

                msg_id = msg_data.get("id")
                msg_from = msg_data.get("from")

                if is_echo_message(msg_id) or msg_data.get("echo") or msg_from in [
                    os.getenv("PHONE_NUMBER_ID"), os.getenv("WHATSAPP_BOT_NUMBER")
                ]:
                    save_sent_message_id(msg_id)
                    return "ok"

                phone = whatsapp.get_mobile(data)
                name = whatsapp.get_name(data)
                msg = whatsapp.get_message(data).strip()

                logger.info(f"Valid message from {phone}: {msg}")

                session = load_session(phone)
                if not session:
                    initialize_session(phone, name)
                    return jsonify({"status": "session initialized"}), 200

                if check_session_timeout(phone):
                    return jsonify({"status": "session timeout"}), 200

                if msg.lower() == "cancel":
                    cancel_session(phone)
                    return jsonify({"status": "session cancelled"}), 200

                session["last_active"] = datetime.now()
                save_session(phone, session["step"], session["data"])
                return handle_user_message(phone, msg, session)

            except Exception as e:
                logger.error(f"❌ Error handling fallback webhook: {e}", exc_info=True)
                return jsonify({"status": "error", "message": str(e)}), 500

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    init_db()
    monitor_sessions()
    cleanup_message_ids()
    port = int(os.environ.get("PORT", 8010))
    logger.info(f"Starting server on port {port}")
    latterpay.run(host="0.0.0.0", port=port)
