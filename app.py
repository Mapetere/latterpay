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
from services.sessions import check_session_timeout, cancel_session, initialize_session,load_session,save_session,update_user_step
from services.donationflow import handle_user_message
from services.registrationflow import RegistrationFlow,handle_first_message
from services.whatsappservice import WhatsAppService

from services.sessions import monitor_sessions
from services.resilience import (
    rate_limiter, payment_circuit_breaker, whatsapp_circuit_breaker,
    db_pool, request_tracker, input_validator, get_health_status,
    CircuitBreakerOpenError, RateLimitExceededError,
    retry_with_backoff, InputValidator
)


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
# ADVANCED LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure production-grade logging with rotation and formatting."""
    
    # Create custom formatter with request ID
    class RequestFormatter(logging.Formatter):
        def format(self, record):
            # Add request ID if available
            record.request_id = getattr(g, 'request_id', 'N/A') if hasattr(g, 'request_id') else 'N/A'
            return super().format(record)
    
    formatter = RequestFormatter(
        '%(asctime)s | %(levelname)-8s | [%(request_id)s] | %(name)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)
    
    # Rotating file handler (10MB per file, keep 5 backups)
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    return logging.getLogger(__name__)


logger = setup_logging()


# ============================================================================
# FLASK APPLICATION FACTORY
# ============================================================================

def create_app():
    """Application factory with production configuration."""
    app = Flask(__name__)
    
    # Security configuration
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex()),
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max request size
    )
    
    # Register middleware and handlers
    register_middleware(app)
    register_error_handlers(app)
    register_routes(app)
    
    return app


# ============================================================================
# MIDDLEWARE & REQUEST LIFECYCLE
# ============================================================================

def register_middleware(app):
    """Register request/response middleware."""
    
    @app.before_request
    def before_request():
        """Execute before each request."""
        # Generate unique request ID for tracing
        g.request_id = str(uuid.uuid4())[:8]
        g.request_start_time = time.time()
        
        # Log incoming request
        logger.debug(f"Incoming {request.method} {request.path}")
        
        # Rate limiting check (skip for health endpoint)
        if request.path != '/health':
            # Get identifier (IP or phone if available)
            identifier = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
            
            if not rate_limiter.is_allowed(identifier):
                request_tracker.record_rate_limit()
                retry_after = rate_limiter.get_retry_after(identifier)
                logger.warning(f"Rate limit exceeded for {identifier}")
                return jsonify({
                    "status": "error",
                    "message": "Too many requests. Please slow down.",
                    "retry_after": int(retry_after) + 1
                }), 429
    
    @app.after_request
    def after_request(response):
        """Execute after each request."""
        # Calculate request duration
        duration_ms = (time.time() - g.request_start_time) * 1000
        
        # Record metrics
        success = response.status_code < 400
        error_type = None if success else f"HTTP_{response.status_code}"
        request_tracker.record_request(request.path, duration_ms, success, error_type)
        
        # Add response headers
        response.headers['X-Request-ID'] = g.request_id
        response.headers['X-Response-Time'] = f"{duration_ms:.2f}ms"
        response.headers['X-App-Version'] = APP_VERSION
        
        # Log response
        logger.debug(f"Response: {response.status_code} in {duration_ms:.2f}ms")
        
        return response


# ============================================================================
# ERROR HANDLERS
# ============================================================================

def register_error_handlers(app):
    """Register global error handlers."""
    
    @app.errorhandler(CircuitBreakerOpenError)
    def handle_circuit_breaker(error):
        request_tracker.record_circuit_breaker_rejection()
        logger.warning(f"Circuit breaker rejection: {error}")
        return jsonify({
            "status": "error",
            "message": "Service temporarily unavailable. Please try again later.",
            "code": "SERVICE_UNAVAILABLE"
        }), 503
    
    @app.errorhandler(RateLimitExceededError)
    def handle_rate_limit(error):
        request_tracker.record_rate_limit()
        return jsonify({
            "status": "error",
            "message": str(error),
            "retry_after": int(error.retry_after) + 1
        }), 429
    
    @app.errorhandler(400)
    def handle_bad_request(error):
        return jsonify({
            "status": "error",
            "message": "Bad request. Please check your input.",
            "code": "BAD_REQUEST"
        }), 400
    
    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({
            "status": "error",
            "message": "Resource not found.",
            "code": "NOT_FOUND"
        }), 404
    
    @app.errorhandler(500)
    def handle_internal_error(error):
        logger.error(f"Internal server error: {error}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "An internal error occurred. Our team has been notified.",
            "code": "INTERNAL_ERROR"
        }), 500
    
    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        logger.error(f"Unexpected error: {error}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "An unexpected error occurred.",
            "code": "UNEXPECTED_ERROR"
        }), 500


# ============================================================================
# META FLOW SCREEN RESPONSES
# ============================================================================

SCREEN_RESPONSES = {
    "PERSONAL_INFO": {"screen": "PERSONAL_INFO", "data": {}},
    "TRAINING": {"screen": "TRAINING", "data": {}},
    "VOLUNTEER": {"screen": "VOLUNTEER", "data": {}},
    "SUMMARY": {"screen": "SUMMARY", "data": {}},
    "TERMS": {"screen": "TERMS", "data": {}},
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


# ============================================================================
# ENCRYPTION HELPERS (with retry and circuit breaker)
# ============================================================================

def decrypt_payload(encrypted_payload_base64: str, aes_key: bytes, iv: bytes) -> str:
    """Decrypt AES-encrypted payload with error handling."""
    try:
        encrypted_payload = base64.b64decode(encrypted_payload_base64)
        cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted_data = unpad(cipher_aes.decrypt(encrypted_payload), AES.block_size)
        return decrypted_data.decode("utf-8")
    except Exception as e:
        logger.error(f"Payload decryption failed: {e}")
        raise ValueError("Failed to decrypt payload") from e


def decrypt_aes_key(encrypted_key_b64: str, private_key_path: str, passphrase: str) -> bytes:
    """
    Decrypt RSA-encrypted AES key with comprehensive error handling.
    """
    try:
        logger.debug("Starting AES key decryption...")
        
        # Clean and fix base64 string
        cleaned_key_b64 = encrypted_key_b64.replace("\\/", "/")
        
        # Fix padding if missing
        missing_padding = len(cleaned_key_b64) % 4
        if missing_padding:
            logger.debug(f"Fixing base64 padding (missing {4 - missing_padding} chars)")
            cleaned_key_b64 += "=" * (4 - missing_padding)
        
        # Decode base64
        encrypted_key_bytes = base64.b64decode(cleaned_key_b64)
        logger.debug(f"Encrypted key size: {len(encrypted_key_bytes)} bytes")
        
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
        
    except base64.binascii.Error as e:
        logger.error("Base64 decoding failed", exc_info=True)
        raise ValueError("Invalid encrypted key format") from e
    except ValueError as e:
        logger.error("RSA decryption failed", exc_info=True)
        raise ValueError("Decryption failed - invalid key or ciphertext") from e
    except Exception as e:
        logger.error("Unexpected decryption error", exc_info=True)
        raise


def re_encrypt_payload(plaintext: str, aes_key: bytes, iv: bytes) -> str:
    """Re-encrypt response payload."""
    try:
        cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
        encrypted = cipher_aes.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
        return base64.b64encode(encrypted).decode("utf-8")
    except Exception as e:
        logger.error(f"Payload encryption failed: {e}")
        raise ValueError("Failed to encrypt payload") from e


# ============================================================================
# DATABASE OPERATIONS (with connection pooling)
# ============================================================================

def init_db():
    """Initialize database tables with error handling."""
    try:
        with db_pool.get_connection() as conn:
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
            
            # Payment Audit Log Table (NEW - for tracking)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payment_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT UNIQUE,
                    phone TEXT,
                    amount REAL,
                    currency TEXT,
                    payment_method TEXT,
                    status TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_phone ON payment_audit_log(phone)")
            
            conn.commit()
            logger.info("Database initialized successfully")
            
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise



    cursor.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    if "warned" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN warned INTEGER DEFAULT 0")


def save_sent_message_id(msg_id: str) -> None:
    """Save message ID to prevent reprocessing."""
    try:
        with db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO sent_messages (msg_id) VALUES (?)",
                (msg_id,)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to save message ID: {e}")


def delete_old_message_ids() -> None:
    """Clean up old message IDs."""
    try:
        with db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sent_messages WHERE sent_at < datetime('now', '-15 minutes')"
            )
            conn.commit()
            logger.debug("Old message IDs cleaned up")
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
        or data.get("object") == "whatsapp_business_account" and not data.get("entry")
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
# ROUTE DEFINITIONS
# ============================================================================

def register_routes(app):
    """Register all application routes."""
    
    @app.route("/")
    def home():
        """Root endpoint - service status."""
        logger.info("Home endpoint accessed")
        return jsonify({
            "service": "LatterPay WhatsApp Donation Service",
            "version": APP_VERSION,
            "status": "running",
            "timestamp": datetime.now().isoformat()
        })
    
    @app.route("/health")
    def health_check():
        """Health check endpoint for monitoring."""
        return jsonify(get_health_status())
    
    @app.route("/metrics")
    def metrics():
        """Metrics endpoint for observability."""
        return jsonify(request_tracker.get_metrics())
    
    @app.route("/payment-return")
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
    
    @app.route("/payment-result", methods=["POST"])
    def payment_result():
        """Paynow IPN (Instant Payment Notification) handler."""
        try:
            raw_data = request.data.decode("utf-8")
            logger.info(f"Paynow IPN received: {raw_data[:500]}")
            
            # Parse and log payment result
            # TODO: Update payment status in audit log
            
            return "OK"
        except Exception as e:
            logger.error(f"Error handling Paynow IPN: {e}", exc_info=True)
            return "ERROR", 500
    
    @app.route("/webhook", methods=["GET", "POST"])
    def webhook():
        """Main WhatsApp webhook handler."""
        try:
            # GET - Webhook verification
            if request.method == "GET":
                return handle_webhook_verification()
            
            # POST - Message handling
            return handle_webhook_message()
            
        except CircuitBreakerOpenError as e:
            raise  # Let error handler deal with it
        except Exception as e:
            logger.error(f"Webhook error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": "Webhook processing failed"
            }), 500


def handle_webhook_verification():
    """Handle WhatsApp webhook verification challenge."""
    verify_token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if verify_token == os.getenv("VERIFY_TOKEN"):
        logger.info("Webhook verified successfully")
        return challenge, 200
    
    logger.warning(f"Webhook verification failed. Token mismatch.")
    return "Verification failed", 403


def handle_webhook_message():
    """Handle incoming WhatsApp webhook messages."""
    # Parse JSON data
    data = request.get_json(force=True)
    
    if not data:
        logger.warning("No JSON data received")
        return jsonify({"status": "error", "message": "No JSON received"}), 400
    
    logger.debug(f"Webhook data type: {type(data)}, keys: {data.keys() if isinstance(data, dict) else 'N/A'}")
    
    # Ignore system payloads
    if is_ignorable_system_payload(data):
        logger.debug("Ignoring system-level webhook data")
        return "ok"
    
    # Handle encrypted Meta Flow messages
    if "encrypted_flow_data" in data and "encrypted_aes_key" in data:
        return handle_encrypted_flow(data)
    
    # Handle standard WhatsApp messages
    if "entry" in data:
        return handle_standard_message(data)
    
    logger.warning("Received unrecognized POST data structure")
    return jsonify({"status": "ignored", "message": "Unrecognized payload"}), 200


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
        
        response = determine_flow_response(action, decrypted_data, flow_token)
        
        # Encrypt response
        json_payload = json.dumps(response).encode("utf-8")
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        encrypted_response = cipher.encrypt(pad(json_payload, AES.block_size))
        encrypted_b64 = b64encode(encrypted_response).decode("utf-8")
        
        return encrypted_b64, 200, {"Content-Type": "text/plain"}
        
    except Exception as e:
        logger.error(f"Encrypted flow error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def determine_flow_response(action: str, data: dict, flow_token: str) -> dict:
    """Determine appropriate response for flow action."""
    if action == "INIT":
        return SCREEN_RESPONSES["PERSONAL_INFO"]
    
    elif action == "data_exchange":
        param = data.get("data", {}).get("some_param", "VOLUNTEER_OPTION_1")
        return {
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
        return SCREEN_RESPONSES.get("SUMMARY", {"screen": "SUMMARY", "data": {}})
    
    else:
        logger.warning(f"Unknown flow action: {action}")
        return SCREEN_RESPONSES.get("TERMS", {"screen": "TERMS", "data": {}})


@whatsapp_circuit_breaker
def handle_standard_message(data: dict):
    """Handle standard WhatsApp text messages with circuit breaker protection."""
    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        messages = value.get("messages", [])
        if not messages:
            return "ok"
        
        msg_data = messages[0]
        msg_id = msg_data.get("id")
        msg_from = msg_data.get("from")
        
        # Skip echo/duplicate messages
        if is_echo_message(msg_id) or msg_data.get("echo"):
            logger.debug(f"Skipping echo message: {msg_id}")
            return "ok"
        
        # Skip messages from bot itself
        if msg_from in [os.getenv("PHONE_NUMBER_ID"), os.getenv("WHATSAPP_BOT_NUMBER")]:
            logger.debug("Skipping self-message")
            save_sent_message_id(msg_id)
            return "ok"
        
        # Extract message details
        phone = whatsapp.get_mobile(data)
        name = whatsapp.get_name(data)
        raw_msg = whatsapp.get_message(data)
        
        # Sanitize input
        msg = input_validator.sanitize_message(raw_msg)
        
        logger.info(f"Message from {phone} ({name}): '{msg[:100]}'")
        
        # Save message ID to prevent reprocessing
        save_sent_message_id(msg_id)
        
        # Process message
        return process_user_message(phone, name, msg)
        
    except Exception as e:
        logger.error(f"Standard message handling error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def process_user_message(phone: str, name: str, msg: str):
    """Process a validated user message."""
    try:
        # Load or create session
        session = load_session(phone)
        
        if not session:
            logger.info(f"Creating new session for {phone}")
            initialize_session(phone, name)
            return jsonify({"status": "session initialized"}), 200
        
        # Check for timeout
        if check_session_timeout(phone):
            return jsonify({"status": "session timeout"}), 200
        
        # Handle cancel command
        if msg.lower() == "cancel":
            cancel_session(phone)
            return jsonify({"status": "session cancelled"}), 200
        
        # Update session activity
        session["last_active"] = datetime.now()
        save_session(phone, session["step"], session.get("data", {}))
        
        # Delegate to donation flow handler
        return handle_user_message(phone, msg, session)
        
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
                    try:
                        changes = data["entry"][0]["changes"][0]["value"]
                        messages = changes.get("messages", [])
                        if not messages:
                            logging.warning("No messages in webhook event")
                            return "ok"
                        msg_data = messages[0]
                    except (IndexError, KeyError) as e:
                        logging.error(f"Error processing webhook: {e}")
                        return "ok"
    

                    if not msg_data:
                        return "ok"

                    msg_id = msg_data.get("id")
                    msg_from = msg_data.get("from")
                    if is_echo_message(msg_id):
                        print(" Detected echo via DB. Ignoring.")
                        return "ok"

                    if msg_data.get("echo"):
                        print(" Detected echo=True. Ignoring.")
                        return "ok"

                    if msg_from == os.getenv("PHONE_NUMBER_ID") or msg_from == os.getenv("WHATSAPP_BOT_NUMBER"):
                        print(" Message from own bot. Ignored.")
                        return "ok"

                    print(" Valid message received:", msg_data.get("text", {}).get("body"))

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

            session = load_session(phone)

            if not session:


                whatsapp.send_message(
                    " You sent me a message!\n\n"
                    "Welcome! What would you like to do?\n\n"
                    "1️⃣ Register to Runde Rural Clinic Project\n"
                    "2️⃣ Make payment\n\n"
                    "Please reply with a number", phone)
                
                session = {
                    "step": "start",
                    "data": {},
                    "last_active": datetime.now()
                }
                save_session(phone, session["step"], session["data"])


                return handle_first_message(phone,msg,session)




            if check_session_timeout(phone):
                return jsonify({"status": "session timeout"}), 200


            if msg.lower() == "cancel":
                cancel_session(phone)
                return jsonify({"status": "session cancelled"}), 200


# ============================================================================
# APPLICATION STARTUP
# ============================================================================

# Create Flask app
latterpay = create_app()


def main():
    """Main entry point."""
    logger.info(f"{'='*60}")
    logger.info(f"  LatterPay WhatsApp Donation Service v{APP_VERSION}")
    logger.info(f"  Starting up...")
    logger.info(f"{'='*60}")
    
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
