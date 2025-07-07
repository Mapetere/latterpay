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
from services.sessions import check_session_timeout, cancel_session, initialize_session,load_session,save_session
from services.donationflow import handle_user_message
from services.sessions import monitor_sessions
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad,pad
import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from Crypto.PublicKey import RSA
import base64




def decrypt_payload(encrypted_payload_base64, aes_key, iv):
    encrypted_payload = base64.b64decode(encrypted_payload_base64)
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_data = unpad(cipher_aes.decrypt(encrypted_payload), AES.block_size)
    return decrypted_data.decode("utf-8")


def decrypt_aes_key(encrypted_key_b64, private_key_path, passphrase=None):
    from cryptography.hazmat.primitives.asymmetric import padding
    encrypted_key = base64.b64decode(encrypted_key_b64)

    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=passphrase.encode() if passphrase else None,
        )

    aes_key = private_key.decrypt(
        encrypted_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return aes_key


        



def decrypt_flow_data(encrypted_data_b64, aes_key, iv_b64):
    encrypted_data = base64.b64decode(encrypted_data_b64)
    iv = base64.b64decode(iv_b64)

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()

    padded_plaintext = decryptor.update(encrypted_data) + decryptor.finalize()

    #  Unpad the plaintext
    unpadder = sym_padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

    return plaintext.decode("utf-8")



def re_encrypt_payload(plaintext, aes_key, iv):
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
    encrypted = cipher_aes.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def encrypt_with_aes_key(aes_key, plaintext_json, iv=None):
    from os import urandom

    if iv is None:
        iv = urandom(16)

    # Pad the data first
    padder = sym_padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext_json.encode()) + padder.finalize()

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded_data) + encryptor.finalize()

    return {
        "encrypted_payload": base64.b64encode(encrypted).decode(),
        "initial_vector": base64.b64encode(iv).decode()
    }


def load_encrypted_private_key(file_path="private.pem", passphrase=None):
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=passphrase.encode() if passphrase else None,
            backend=default_backend()
        )
    return private_key


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)


PRIVATE_KEY_FILE = "private.pem"

if not os.path.exists(PRIVATE_KEY_FILE):
    pem_content = os.getenv("PRIVATE_KEY_PEM")
    if pem_content:
        with open(PRIVATE_KEY_FILE, "w") as pem_file:
            pem_file.write(pem_content)
        print(" private.pem file created from environment variable.")
    else:
        print(" PRIVATE_KEY_PEM environment variable not set!")



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
            # Webhook verification
            verify_token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            if verify_token == os.getenv("VERIFY_TOKEN"):
                logger.info("Webhook verified successfully!")
                return challenge, 200
            return "Verification failed", 403

        # POST: main webhook logic
        data = request.get_json(force=True, silent=True)

        if not data:
            logger.error("No valid JSON data received.")
            return jsonify({"status": "error", "message": "No data"}), 400

        # Check for WhatsApp Flow encryption
        enc_key = data.get("encrypted_aes_key")
        enc_data = data.get("encrypted_flow_data")
        iv = data.get("initial_vector")

        if enc_key and enc_data and iv:
            aes_key = decrypt_aes_key(enc_key, "private.pem", os.getenv("PRIVATE_KEY_PASSPHRASE"))
            decrypted_json = decrypt_flow_data(enc_data, aes_key, iv)
            logger.info(f"AES key length: {len(aes_key)}")
            logger.info(f"IV length: {len(iv)}")
            logger.info(f"Encrypted flow data length: {len(enc_data)}")

            logger.info(f"Decrypted flow data: {decrypted_json}")
            parsed = json.loads(decrypted_json)
            action = parsed.get("action")

            if action == "INIT":
                return jsonify({"status": "Flow initialized"}), 200
            elif action == "BACK":
                return jsonify({"status": "User pressed back"}), 200
            elif action == "data_exchange":
                logger.info(f"User data: {parsed.get('data')}")
                return jsonify({"status": "Data exchanged"}), 200

            return jsonify({"status": "Flow handled but action unknown"}), 200

        # Regular message handling
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        msg_data = value.get("messages", [{}])[0] if value.get("messages") else None

        if not msg_data:
            logger.info("No user message detected. Ignored.")
            return "ok"

        msg_id = msg_data.get("id")
        msg_from = msg_data.get("from")

        if is_echo_message(msg_id) or msg_data.get("echo") or message_exists(msg_id) or msg_from in [
            os.getenv("PHONE_NUMBER_ID"), os.getenv("WHATSAPP_BOT_NUMBER")
        ]:
            logger.info("Echo/self message ignored.")
            save_sent_message_id(msg_id)
            return "ok"

        phone = whatsapp.get_mobile(data)
        name = whatsapp.get_name(data)
        msg = whatsapp.get_message(data).strip()

        logger.info(f"Valid message received from {phone}: {msg}")

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
        logger.error(f"Message processing error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    init_db()
    monitor_sessions()
    port = int(os.environ.get("PORT", 8010))
    logger.info(f"Starting server on port {port}")
    latterpay.run(host="0.0.0.0", port=port)
