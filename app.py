import os
import sys
import json
import sqlite3
import logging
import base64
import threading
import time
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from Crypto.Cipher import AES as CryptoAES
from Crypto.Util.Padding import pad, unpad
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# Import local modules
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, PAYMENTS_FILE
from services.sessions import (
    check_session_timeout, cancel_session, 
    initialize_session, load_session, save_session, monitor_sessions
)
from services.donationflow import handle_user_message

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
PRIVATE_KEY_FILE = "private.pem"
PRIVATE_KEY_PASSPHRASE = os.getenv("PRIVATE_KEY_PASSPHRASE")

# Initialize private key
if not os.path.exists(PRIVATE_KEY_FILE):
    pem_content = os.getenv("PRIVATE_KEY_PEM")
    if pem_content:
        with open(PRIVATE_KEY_FILE, "w") as pem_file:
            pem_file.write(pem_content)
        logger.info("private.pem file created from environment variable.")
    else:
        logger.error("PRIVATE_KEY_PEM environment variable not set!")
        raise RuntimeError("Missing private key configuration")

# Initialize empty JSON files if they don't exist
for file_path in [CUSTOM_TYPES_FILE, PAYMENTS_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            json.dump([], f)

class Database:
    """Database helper class"""
    @staticmethod
    def init_db():
        """Initialize database tables"""
        with sqlite3.connect("botdata.db", timeout=10) as conn:
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
                    last_active TIMESTAMP,
                    warned INTEGER DEFAULT 0
                )
            """)

            # Volunteers Table
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

    @staticmethod
    def is_echo_message(msg_id):
        """Check if message is an echo"""
        with sqlite3.connect("botdata.db", timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM sent_messages WHERE msg_id = ?", (msg_id,))
            return cursor.fetchone() is not None

    @staticmethod
    def save_sent_message_id(msg_id):
        """Save sent message ID to database"""
        with sqlite3.connect("botdata.db", timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO sent_messages (msg_id) VALUES (?)", (msg_id,))
            conn.commit()

    @staticmethod
    def delete_old_ids():
        """Clean up old message IDs"""
        with sqlite3.connect("botdata.db", timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sent_messages WHERE sent_at < datetime('now', '-15 minutes')")
            conn.commit()

class EncryptionService:
    """Handles all encryption/decryption operations"""
    
    @staticmethod
    def decrypt_aes_key(encrypted_key_b64, private_key_path, passphrase=None):
        """Decrypt AES key using RSA private key"""
        try:
            encrypted_key = base64.b64decode(encrypted_key_b64)
            with open(private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=passphrase.encode() if passphrase else None,
                    backend=default_backend()
                )
            return private_key.decrypt(
                encrypted_key,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
        except Exception as e:
            logger.error(f"AES key decryption failed: {str(e)}")
            raise ValueError("Failed to decrypt AES key") from e

    @staticmethod
    def decrypt_flow_data(encrypted_data_b64, aes_key, iv_b64):
        """Decrypt WhatsApp flow data using AES-CBC"""
        try:
            # Validate and clean inputs
            encrypted_data_b64 = encrypted_data_b64.strip().replace("\n", "").replace(" ", "")
            iv_b64 = iv_b64.strip().replace("\n", "").replace(" ", "")
            
            # Decode base64
            encrypted_data = base64.b64decode(encrypted_data_b64)
            iv = base64.b64decode(iv_b64)

            # Validate lengths
            if len(aes_key) not in [16, 24, 32]:
                raise ValueError(f"Invalid AES key length: {len(aes_key)} bytes (expected 16, 24, or 32)")
                
            if len(iv) != 16:
                raise ValueError(f"Invalid IV length: {len(iv)} bytes (expected 16)")
                
            if len(encrypted_data) % 16 != 0:
                raise ValueError(f"Encrypted data length {len(encrypted_data)} is not a multiple of block size (16)")

            # Decrypt
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(encrypted_data) + decryptor.finalize()

            # Unpad
            unpadder = sym_padding.PKCS7(128).unpadder()
            plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

            return plaintext.decode("utf-8")

        except Exception as e:
            logger.error(f"Flow data decryption failed. Input lengths - Key: {len(aes_key)}, IV: {len(iv)}, Data: {len(encrypted_data)}")
            raise ValueError(f"Decryption failed: {str(e)}") from e

    @staticmethod
    def encrypt_with_aes_key(aes_key, plaintext_json, iv=None):
        """Encrypt data using AES-CBC"""
        from os import urandom
        try:
            if iv is None:
                iv = urandom(16)
                
            padder = sym_padding.PKCS7(128).padder()
            padded_data = padder.update(plaintext_json.encode()) + padder.finalize()
            
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(padded_data) + encryptor.finalize()
            
            return {
                "encrypted_payload": base64.b64encode(encrypted).decode(),
                "initial_vector": base64.b64encode(iv).decode()
            }
        except Exception as e:
            logger.error(f"Encryption failed: {str(e)}")
            raise

def cleanup_message_ids():
    """Background thread to clean up old message IDs"""
    def cleaner():
        while True:
            try:
                Database.delete_old_ids()
                time.sleep(3600)  # Run hourly
            except Exception as e:
                logger.warning(f"[CLEANUP ERROR] {e}")
                time.sleep(600)  # Retry after 10 minutes on error

    threading.Thread(target=cleaner, daemon=True).start()

@app.route("/")
def home():
    """Health check endpoint"""
    logger.info("Health check endpoint accessed")
    return "WhatsApp Donation Service is running"

@app.route("/payment-return")
def payment_return():
    """Payment return page"""
    return "<h2>Payment attempted. You may now return to WhatsApp.</h2>"

@app.route("/payment-result", methods=["POST"])
def payment_result():
    """Handle payment results"""
    try:
        raw_data = request.data.decode("utf-8")
        logger.info("Paynow Result Received: \n" + raw_data)
        return "OK"
    except Exception as e:
        logger.error(f"Error handling Paynow result: {e}")
        return "ERROR", 500

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Main WhatsApp webhook handler"""
    try:
        if request.method == "GET":
            # Webhook verification
            verify_token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            if verify_token == os.getenv("VERIFY_TOKEN"):
                logger.info("Webhook verified successfully!")
                return challenge, 200
            return "Verification failed", 403

        # Handle POST requests
        data = request.get_json(force=True, silent=True) or {}
        logger.debug(f"Received webhook data: {json.dumps(data, indent=2)}")

        # Check for WhatsApp Flow encryption
        enc_key = data.get("encrypted_aes_key")
        enc_data = data.get("encrypted_flow_data")
        iv = data.get("initial_vector")

        if all([enc_key, enc_data, iv]):
            return handle_encrypted_flow(enc_key, enc_data, iv)

        return handle_regular_message(data)

    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_encrypted_flow(enc_key, enc_data, iv):
    """Process encrypted WhatsApp flow data"""
    try:
        aes_key = EncryptionService.decrypt_aes_key(
            enc_key, 
            PRIVATE_KEY_FILE, 
            PRIVATE_KEY_PASSPHRASE
        )
        decrypted_json = EncryptionService.decrypt_flow_data(enc_data, aes_key, iv)
        
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

    except ValueError as ve:
        logger.warning(f"Decryption failed: {ve}")
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Flow processing error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

def handle_regular_message(data):
    """Process regular WhatsApp messages"""
    entry = data.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    msg_data = value.get("messages", [{}])[0] if value.get("messages") else None

    if not msg_data:
        logger.info("No user message detected")
        return "ok"

    msg_id = msg_data.get("id")
    msg_from = msg_data.get("from")

    # Ignore echo messages and messages from ourselves
    if (Database.is_echo_message(msg_id) or msg_data.get("echo") or 
        msg_from in [os.getenv("PHONE_NUMBER_ID"), os.getenv("WHATSAPP_BOT_NUMBER")]):
        logger.info("Ignoring echo/self message")
        Database.save_sent_message_id(msg_id)
        return "ok"

    phone = whatsapp.get_mobile(data)
    name = whatsapp.get_name(data)
    msg = whatsapp.get_message(data).strip()

    logger.info(f"Message from {phone}: {msg}")

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

if __name__ == "__main__":
    # Initialize services
    Database.init_db()
    monitor_sessions()
    cleanup_message_ids()
    
    # Start Flask app
    port = int(os.environ.get("PORT", 8010))
    logger.info(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port)