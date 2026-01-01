"""
LatterPay - WhatsApp Donation & Registration Service
=====================================================
Production-grade WhatsApp bot with end-to-end encryption,
resilience patterns, and comprehensive error handling.

Author: Nyasha Mapetere
Version: 2.0.0 (Upgraded with Advanced Resilience)
"""

from flask import Flask, request, jsonify, g
from datetime import datetime
import os
import json
import sqlite3
from sqlite3 import OperationalError
from paynow import Paynow
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import threading
import uuid
import signal
import atexit
from functools import wraps

# Cryptography imports
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Util.Padding import pad, unpad
from base64 import b64decode, b64encode
from Crypto.PublicKey import RSA
import base64

# Internal imports
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, PAYMENTS_FILE
from services.sessions import (
    check_session_timeout, cancel_session, initialize_session,
    load_session, save_session
)
from services.donationflow import handle_user_message
from services.sessions import monitor_sessions

# Import resilience module (with fallback if not available)
try:
    from services.resilience import (
        rate_limiter, payment_circuit_breaker, whatsapp_circuit_breaker,
        db_pool, request_tracker, input_validator, get_health_status,
        CircuitBreakerOpenError, RateLimitExceededError,
        retry_with_backoff, InputValidator
    )
    RESILIENCE_ENABLED = True
except ImportError:
    RESILIENCE_ENABLED = False
    # Create dummy objects if resilience module not available
    class DummyRateLimiter:
        def is_allowed(self, *args): return True
        def get_retry_after(self, *args): return 0
    class DummyTracker:
        def record_request(self, *args, **kwargs): pass
        def record_rate_limit(self): pass
        def record_circuit_breaker_rejection(self): pass
        def get_metrics(self): return {}
    class DummyValidator:
        def sanitize_message(self, msg): return msg.strip() if msg else ""
    rate_limiter = DummyRateLimiter()
    request_tracker = DummyTracker()
    input_validator = DummyValidator()
    def get_health_status(): return {"status": "healthy"}
    class CircuitBreakerOpenError(Exception): pass
    class RateLimitExceededError(Exception): pass


# ============================================================================
# CONFIGURATION & INITIALIZATION
# ============================================================================

load_dotenv()

# Environment configuration
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO
APP_VERSION = "2.0.0"

# Path configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_PATH = os.path.join(BASE_DIR, "private.pem")
LOG_FILE_PATH = os.path.join(BASE_DIR, "logs", "app.log")

# Ensure logs directory exists
os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)


# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# FLASK APPLICATION
# ============================================================================

latterpay = Flask(__name__)

# Security configuration
latterpay.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex()),
    JSON_SORT_KEYS=False,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max request size
)


# ============================================================================
# META FLOW SCREEN RESPONSES
# ============================================================================

SCREEN_RESPONSES = {
    "PERSONAL_INFO": {"screen": "PERSONAL_INFO", "data": {}},
    "TRAINING": {"screen": "TRAINING", "data": {}},
    "VOLUNTEER": {"screen": "VOLUNTEER", "data": {}},
    "SUMMARY": {"screen": "SUMMARY", "data": {}},
    "TERMS": {"screen": "TERMS", "data": {}},
}


# ============================================================================
# ENCRYPTION HELPERS
# ============================================================================

def decrypt_aes_key(encrypted_key_b64: str, private_key_path: str, passphrase: str) -> bytes:
    """Decrypt RSA-encrypted AES key."""
    try:
        logger.debug("Starting AES key decryption...")
        
        # Clean and fix base64 string
        cleaned_key_b64 = encrypted_key_b64.replace("\\/", "/")
        
        # Fix padding if missing
        missing_padding = len(cleaned_key_b64) % 4
        if missing_padding:
            cleaned_key_b64 += "=" * (4 - missing_padding)
        
        # Decode base64
        encrypted_key_bytes = base64.b64decode(cleaned_key_b64)
        
        # Load private key
        if not os.path.exists(private_key_path):
            raise FileNotFoundError(f"Private key not found: {private_key_path}")
        
        with open(private_key_path, "rb") as key_file:
            private_key = RSA.import_key(key_file.read(), passphrase=passphrase)
        
        # Decrypt AES key using RSA-OAEP
        cipher_rsa = PKCS1_OAEP.new(private_key)
        decrypted_key = cipher_rsa.decrypt(encrypted_key_bytes)
        
        logger.info("AES key successfully decrypted")
        return decrypted_key
        
    except Exception as e:
        logger.error(f"AES key decryption failed: {e}", exc_info=True)
        raise


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def init_db():
    """Initialize database tables."""
    try:
        conn = sqlite3.connect("botdata.db", timeout=10)
        cursor = conn.cursor()
        
        # Sent Messages Table (for echo detection)
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
                phone TEXT UNIQUE,
                email TEXT,
                skill TEXT,
                area TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise


def is_echo_message(msg_id: str) -> bool:
    """Check if message is an echo (already processed)."""
    try:
        conn = sqlite3.connect("botdata.db", timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sent_messages WHERE msg_id = ?", (msg_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Echo check failed: {e}")
        return False


def save_sent_message_id(msg_id: str) -> None:
    """Save message ID to prevent reprocessing."""
    try:
        conn = sqlite3.connect("botdata.db", timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO sent_messages (msg_id) VALUES (?)",
            (msg_id,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save message ID: {e}")


def delete_old_message_ids() -> None:
    """Clean up old message IDs."""
    try:
        conn = sqlite3.connect("botdata.db", timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM sent_messages WHERE sent_at < datetime('now', '-15 minutes')"
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Message ID cleanup failed: {e}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_ignorable_system_payload(data: dict) -> bool:
    """Check if payload is a system event that should be ignored."""
    if not isinstance(data, dict):
        return False
    
    return (
        data.get("type") in ["DEPLOY", "BUILD", "STATUS"]
        or "deployment" in data
        or ("project" in data and "status" in data)
    )


def cleanup_message_ids_daemon():
    """Background daemon for cleaning up old message IDs."""
    def cleaner():
        while True:
            try:
                delete_old_message_ids()
                time.sleep(3600)  # Run every hour
            except Exception as e:
                logger.warning(f"[CLEANUP ERROR] {e}")
                time.sleep(600)
    
    thread = threading.Thread(target=cleaner, daemon=True, name="MessageCleanup")
    thread.start()
    logger.info("Message cleanup daemon started")


# ============================================================================
# ROUTES
# ============================================================================

@latterpay.route("/")
def home():
    """Root endpoint - service status."""
    logger.info("Home endpoint accessed")
    return jsonify({
        "service": "LatterPay WhatsApp Donation Service",
        "version": APP_VERSION,
        "status": "running",
        "timestamp": datetime.now().isoformat()
    })


@latterpay.route("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify(get_health_status())


@latterpay.route("/metrics")
def metrics():
    """Metrics endpoint for observability."""
    return jsonify(request_tracker.get_metrics())


@latterpay.route("/payment-return")
def payment_return():
    """Payment return page after Paynow redirect."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment Processed</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   display: flex; justify-content: center; align-items: center;
                   min-height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
            .card { background: white; padding: 40px; border-radius: 16px; text-align: center;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.3); max-width: 400px; }
            h2 { color: #333; margin-bottom: 16px; }
            p { color: #666; }
            .check { font-size: 64px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="check">✅</div>
            <h2>Payment Attempted</h2>
            <p>You may now return to WhatsApp to check your payment status.</p>
        </div>
    </body>
    </html>
    """, 200, {'Content-Type': 'text/html'}


@latterpay.route("/payment-result", methods=["POST"])
def payment_result():
    """Paynow IPN (Instant Payment Notification) handler."""
    try:
        raw_data = request.data.decode("utf-8")
        logger.info(f"Paynow IPN received: {raw_data[:500]}")
        return "OK"
    except Exception as e:
        logger.error(f"Error handling Paynow IPN: {e}", exc_info=True)
        return "ERROR", 500


@latterpay.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Main WhatsApp webhook handler."""
    try:
        # GET - Webhook verification
        if request.method == "GET":
            verify_token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            
            if verify_token == os.getenv("VERIFY_TOKEN"):
                logger.info("Webhook verified successfully")
                return challenge, 200
            
            logger.warning("Webhook verification failed - token mismatch")
            return "Verification failed", 403

        # POST - Message handling
        if request.method == "POST":
            data = None
            
            # Parse JSON data
            if request.is_json:
                data = request.get_json()
            else:
                try:
                    raw_data = request.data.decode("utf-8")
                    logger.debug(f"Incoming RAW POST data: {raw_data[:500]}")
                    data = json.loads(raw_data)
                except Exception as decode_err:
                    logger.error(f"Failed to decode raw POST data: {decode_err}")
                    return jsonify({"status": "error", "message": "Invalid JSON"}), 400
            
            if not data:
                logger.warning("No JSON data received")
                return jsonify({"status": "error", "message": "No JSON received"}), 400
            
            # Ignore system payloads (Railway deploy notifications, etc.)
            if is_ignorable_system_payload(data):
                logger.debug("Ignoring system-level webhook data")
                return jsonify({"status": "ignored"}), 200
            
            # Handle encrypted Meta Flow messages
            if "encrypted_flow_data" in data and "encrypted_aes_key" in data:
                return handle_encrypted_flow(data)
            
            # Handle standard WhatsApp messages
            if whatsapp.is_message(data):
                return handle_whatsapp_message(data)
            
            # Unknown payload type
            logger.debug("Received unrecognized POST data structure")
            return jsonify({"status": "ignored"}), 200
            
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def handle_encrypted_flow(data: dict):
    """Handle encrypted Meta Flow messages."""
    try:
        encrypted_data_b64 = data.get("encrypted_flow_data")
        encrypted_key_b64 = data.get("encrypted_aes_key")
        iv_b64 = data.get("initial_vector")
        
        if not all([encrypted_data_b64, encrypted_key_b64, iv_b64]):
            return jsonify({"error": "Missing encryption fields"}), 400
        
        logger.debug("Processing encrypted flow data...")
        
        # Decrypt AES key using RSA
        aes_key = decrypt_aes_key(
            encrypted_key_b64,
            PRIVATE_KEY_PATH,
            os.getenv("PRIVATE_KEY_PASSPHRASE")
        )
        
        # Decrypt flow data
        iv = b64decode(iv_b64)
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted_bytes = unpad(cipher.decrypt(b64decode(encrypted_data_b64)), AES.block_size)
        decrypted_data = json.loads(decrypted_bytes.decode("utf-8"))
        
        logger.info(f"Decrypted flow action: {decrypted_data.get('action')}")
        
        # Determine response based on action
        action = decrypted_data.get("action")
        flow_token = decrypted_data.get("flow_token", "UNKNOWN")
        
        if action == "INIT":
            response = SCREEN_RESPONSES["PERSONAL_INFO"]
        elif action == "data_exchange":
            param = decrypted_data.get("data", {}).get("some_param", "VOLUNTEER_OPTION_1")
            response = {
                "screen": "SUCCESS",
                "data": {
                    "extension_message_response": {
                        "params": {
                            "flow_token": flow_token,
                            "some_param_name": param
                        }
                    }
                }
            }
        elif action == "BACK":
            response = SCREEN_RESPONSES.get("SUMMARY", {"screen": "SUMMARY", "data": {}})
        else:
            logger.warning(f"Unknown flow action: {action}")
            response = SCREEN_RESPONSES.get("TERMS", {"screen": "TERMS", "data": {}})
        
        # Encrypt response
        json_payload = json.dumps(response).encode("utf-8")
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        encrypted_response = cipher.encrypt(pad(json_payload, AES.block_size))
        encrypted_b64 = b64encode(encrypted_response).decode("utf-8")
        
        return encrypted_b64, 200, {"Content-Type": "text/plain"}
        
    except Exception as e:
        logger.error(f"Encrypted flow error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def handle_whatsapp_message(data: dict):
    """Handle standard WhatsApp text messages."""
    try:
        # Extract message data
        try:
            changes = data["entry"][0]["changes"][0]["value"]
            messages = changes.get("messages", [])
            if not messages:
                logger.debug("No messages in webhook event")
                return "ok"
            msg_data = messages[0]
        except (IndexError, KeyError) as e:
            logger.error(f"Error extracting message data: {e}")
            return "ok"
        
        if not msg_data:
            return "ok"
        
        msg_id = msg_data.get("id")
        msg_from = msg_data.get("from")
        
        # Skip echo/duplicate messages
        if is_echo_message(msg_id):
            logger.debug(f"Skipping echo message: {msg_id}")
            return "ok"
        
        if msg_data.get("echo"):
            logger.debug("Skipping message with echo=True")
            return "ok"
        
        # Skip messages from bot itself
        if msg_from in [os.getenv("PHONE_NUMBER_ID"), os.getenv("WHATSAPP_BOT_NUMBER")]:
            logger.debug("Skipping self-message")
            return "ok"
        
        # Save message ID to prevent reprocessing
        save_sent_message_id(msg_id)
        
        # Extract message details
        phone = whatsapp.get_mobile(data)
        name = whatsapp.get_name(data)
        msg = whatsapp.get_message(data).strip()
        
        logger.info(f"Message from {phone} ({name}): '{msg[:100]}'")
        
        # Process message
        return process_user_message(phone, name, msg)
        
    except Exception as e:
        logger.error(f"WhatsApp message handling error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def process_user_message(phone: str, name: str, msg: str):
    """Process a validated user message."""
    try:
        # Load session
        session = load_session(phone)
        
        if not session:
            # New user - create session and send welcome
            logger.info(f"Creating new session for {phone}")
            
            whatsapp.send_message(
                "👋 You sent me a message!\n\n"
                "Welcome! What would you like to do?\n\n"
                "1️⃣ Register to Runde Rural Clinic Project\n"
                "2️⃣ Make payment\n\n"
                "Please reply with a number", 
                phone
            )
            
            session = {
                "step": "start",
                "data": {},
                "last_active": datetime.now()
            }
            save_session(phone, session["step"], session["data"])
            
            # Handle first response
            if msg in ["1", "2"]:
                return handle_first_message_choice(phone, msg, session)
            
            return jsonify({"status": "session initialized"}), 200
        
        # Check for timeout
        if check_session_timeout(phone):
            return jsonify({"status": "session timeout"}), 200
        
        # Handle cancel command
        if msg.lower() == "cancel":
            cancel_session(phone)
            return jsonify({"status": "session cancelled"}), 200
        
        # Handle menu choice at start
        if session.get("step") == "start" and msg in ["1", "2"]:
            return handle_first_message_choice(phone, msg, session)
        
        # Update session activity and delegate to flow handler
        session["last_active"] = datetime.now()
        save_session(phone, session["step"], session.get("data", {}))
        
        return handle_user_message(phone, msg, session)
        
    except Exception as e:
        logger.error(f"Message processing error for {phone}: {e}", exc_info=True)
        try:
            whatsapp.send_message(
                "😔 Sorry, something went wrong. Please try again or type 'cancel' to start over.",
                phone
            )
        except:
            pass
        return jsonify({"status": "error"}), 500


def handle_first_message_choice(phone: str, msg: str, session: dict):
    """Handle the initial menu choice (1 for register, 2 for payment)."""
    try:
        if msg == "1":
            # Registration flow
            whatsapp.send_message(
                "📝 *Registration Started!*\n\n"
                "Let's get you registered. What's your *full name*?",
                phone
            )
            session["mode"] = "registration"
            session["step"] = "awaiting_name"
            save_session(phone, session["step"], session.get("data", {}))
            return jsonify({"status": "registration started"}), 200
            
        elif msg == "2":
            # Payment/donation flow
            initialize_session(phone, "User")
            return jsonify({"status": "donation started"}), 200
        
        else:
            whatsapp.send_message(
                "❓ Please type *1* to Register or *2* to Make a Payment.",
                phone
            )
            return jsonify({"status": "awaiting valid option"}), 200
            
    except Exception as e:
        logger.error(f"First message choice error: {e}", exc_info=True)
        return jsonify({"status": "error"}), 500


# ============================================================================
# GRACEFUL SHUTDOWN
# ============================================================================

def graceful_shutdown(signum, frame):
    """Handle graceful shutdown on SIGTERM/SIGINT."""
    logger.info(f"Received shutdown signal ({signum}). Shutting down...")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)


# ============================================================================
# APPLICATION STARTUP
# ============================================================================

def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("  LatterPay WhatsApp Donation Service v" + APP_VERSION)
    logger.info("  Starting up...")
    logger.info("=" * 60)
    
    # Initialize database
    init_db()
    
    # Start background services
    monitor_sessions()
    cleanup_message_ids_daemon()
    
    # Get port from environment
    port = int(os.environ.get("PORT", 8010))
    
    logger.info(f"Server starting on port {port}")
    logger.info(f"Health check: http://localhost:{port}/health")
    logger.info(f"Metrics: http://localhost:{port}/metrics")
    
    # Run server
    latterpay.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)


if __name__ == "__main__":
    main()
