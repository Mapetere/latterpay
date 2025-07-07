import os
import json
import base64
import logging
import sqlite3
import threading
import time
from datetime import datetime
from flask import Flask, request, jsonify
from Crypto.Cipher import AES as CryptoAES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Flask app
app = Flask(__name__)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('webhook.log')
    ]
)
logger = logging.getLogger(__name__)

# DB setup
DB_NAME = "botdata.db"
def init_db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_messages (
            msg_id TEXT PRIMARY KEY,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    conn.commit()
    conn.close()

# RSA + AES logic
PRIVATE_KEY_FILE = os.getenv('PRIVATE_KEY_FILE', 'private.pem')
PRIVATE_KEY_PASSPHRASE = os.getenv('PRIVATE_KEY_PASSPHRASE')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')

def load_private_key():
    with open(PRIVATE_KEY_FILE, "rb") as key_file:
        return serialization.load_pem_private_key(
            key_file.read(),
            password=PRIVATE_KEY_PASSPHRASE.encode() if PRIVATE_KEY_PASSPHRASE else None,
            backend=default_backend()
        )

def decrypt_aes_key(encrypted_key_b64):
    encrypted_key = base64.b64decode(encrypted_key_b64)
    private_key = load_private_key()
    return private_key.decrypt(
        encrypted_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

def decrypt_flow_data(encrypted_data_b64, aes_key, iv_b64):
    encrypted_data = base64.b64decode(encrypted_data_b64)
    iv = base64.b64decode(iv_b64)
    cipher = CryptoAES.new(aes_key, CryptoAES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(encrypted_data), CryptoAES.block_size)
    return decrypted.decode("utf-8")

# Sessions
sessions = {}

def init_session(phone, name):
    sessions[phone] = {"step": "start", "data": {}, "last_active": datetime.now(), "name": name}

def save_session(phone, session):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO sessions (phone, step, data, last_active, warned)
        VALUES (?, ?, ?, ?, ?)
    """, (phone, session['step'], json.dumps(session['data']), session['last_active'], 0))
    conn.commit()
    conn.close()

# Message filter
seen_messages = set()

def is_duplicate(msg_id):
    return msg_id in seen_messages

def mark_message_seen(msg_id):
    seen_messages.add(msg_id)

def cleanup_seen():
    while True:
        seen_messages.clear()
        time.sleep(600)

threading.Thread(target=cleanup_seen, daemon=True).start()

@app.route('/')
def home():
    return "Donation webhook running"

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == VERIFY_TOKEN:
            return challenge or "", 200
        return "Forbidden", 403

    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "message": "Empty request"}), 400

        enc_key = data.get("encrypted_aes_key")
        enc_data = data.get("encrypted_flow_data")
        iv = data.get("initial_vector")

        if enc_key and enc_data and iv:
            aes_key = decrypt_aes_key(enc_key)
            decrypted = decrypt_flow_data(enc_data, aes_key, iv)
            parsed = json.loads(decrypted)

            # Mock donation flow
            action = parsed.get("action")
            if action == "INIT":
                return jsonify({"status": "Flow started"})
            elif action == "data_exchange":
                donation = parsed.get("data", {}).get("donation_amount")
                return jsonify({"status": "Thank you for your donation", "amount": donation})
            else:
                return jsonify({"status": "Unknown action"})

        # Basic fallback for messages
        msg = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0]
        msg_id = msg.get("id")
        phone = msg.get("from")

        if not msg_id or not phone or is_duplicate(msg_id):
            return "ok"
        mark_message_seen(msg_id)

        text = msg.get("text", {}).get("body", "").strip()
        logger.info(f"Msg from {phone}: {text}")

        # Initialize session
        if phone not in sessions:
            init_session(phone, "User")

        session = sessions[phone]
        session["last_active"] = datetime.now()
        save_session(phone, session)

        # Simple donation logic
        if text.lower() == "donate":
            return jsonify({"text": "Please enter donation amount"})
        elif text.isdigit():
            return jsonify({"text": f"Thanks for donating ${text}"})

        return jsonify({"text": "Send 'donate' to start"})

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    init_db()
    port = int(os.getenv("PORT", 8010))
    logger.info(f"Running donation webhook on port {port}")
    app.run(host='0.0.0.0', port=port)
