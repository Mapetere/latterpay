import os
import json
import base64
import logging
from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# ---------------------- App Setup ---------------------- #
app = Flask(__name__)
load_dotenv()

# ---------------------- Logging ------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("whatsapp_webhook.log")]
)
logger = logging.getLogger(__name__)

# ---------------------- Config ------------------------- #
PRIVATE_KEY_FILE = os.getenv("PRIVATE_KEY_FILE", "private.pem")
PRIVATE_KEY_PASSPHRASE = os.getenv("PRIVATE_KEY_PASSPHRASE")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PORT = int(os.getenv("PORT", 8010))

# ---------------------- Validation --------------------- #
if not VERIFY_TOKEN:
    logger.error("Missing VERIFY_TOKEN environment variable.")
if not os.path.exists(PRIVATE_KEY_FILE):
    logger.error(f"Private key file not found: {PRIVATE_KEY_FILE}")

# ---------------------- Decryption Handler ---------------------- #
class WhatsAppDecryptor:

    @staticmethod
    def decrypt_aes_key(encrypted_key_b64: str) -> bytes:
        """Decrypt base64 AES key using RSA private key."""
        try:
            encrypted_key = base64.b64decode(encrypted_key_b64)
            with open(PRIVATE_KEY_FILE, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=PRIVATE_KEY_PASSPHRASE.encode() if PRIVATE_KEY_PASSPHRASE else None,
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
            logger.error(f"Failed to decrypt AES key: {e}")
            raise

    @staticmethod
    def force_decrypt(encrypted_data: bytes, aes_key: bytes, iv: bytes) -> bytes:
        """Decrypt AES-CBC data, truncate if needed."""
        try:
            if len(encrypted_data) % AES.block_size != 0:
                logger.warning(f"Encrypted data length {len(encrypted_data)} is not a multiple of 16. Truncating...")
                encrypted_data = encrypted_data[:len(encrypted_data) - (len(encrypted_data) % AES.block_size)]

            cipher = AES.new(aes_key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_data)
            try:
                return unpad(decrypted, AES.block_size)
            except ValueError:
                logger.warning("Unpadding failed, returning raw decrypted data.")
                return decrypted
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            return b""

    @staticmethod
    def decrypt_flow_data(encrypted_data_b64: str, aes_key: bytes, iv_b64: str) -> bytes:
        """Decrypt base64 flow data."""
        try:
            encrypted_data = base64.b64decode(encrypted_data_b64.strip())
            iv = base64.b64decode(iv_b64.strip())

            if len(aes_key) not in [16, 24, 32]:
                logger.warning(f"AES key length {len(aes_key)} is invalid.")
            if len(iv) != 16:
                logger.warning(f"IV length {len(iv)} is invalid.")

            return WhatsAppDecryptor.force_decrypt(encrypted_data, aes_key, iv)

        except Exception as e:
            logger.error(f"Pre-decryption error: {e}")
            return b""


# ---------------------- Webhook Route ---------------------- #
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    try:
        if request.method == "GET":
            token = request.args.get("hub.verify_token")
            if token == VERIFY_TOKEN:
                return request.args.get("hub.challenge", ""), 200
            return "Verification failed", 403

        response = {
            "status": "success",
            "message": "Message processed",
            "metadata": {}
        }

        # Parse incoming data
        try:
            content_type = (request.content_type or "").lower()
            if "x-www-form-urlencoded" in content_type:
                form_data = dict(request.form)
                data = json.loads(form_data.get("payload", "{}"))
            else:
                data = request.get_json(force=True, silent=True) or {}
        except Exception as e:
            logger.warning(f"Request parsing error: {e}")
            data = {}

        # Handle encrypted fields
        if all(k in data for k in ["encrypted_aes_key", "encrypted_flow_data", "initial_vector"]):
            try:
                aes_key = WhatsAppDecryptor.decrypt_aes_key(data["encrypted_aes_key"])
                decrypted_bytes = WhatsAppDecryptor.decrypt_flow_data(
                    data["encrypted_flow_data"],
                    aes_key,
                    data["initial_vector"]
                )

                response["metadata"]["decryption_status"] = "complete" if decrypted_bytes else "partial"

                try:
                    # 1. Try UTF-8 → JSON
                    decrypted_text = decrypted_bytes.decode("utf-8")
                    try:
                        response["data"] = json.loads(decrypted_text)
                        response["message"] = "Decrypted JSON successfully"
                    except json.JSONDecodeError:
                        # 2. Try base64 decode → UTF-8 → JSON
                        try:
                            base64_decoded = base64.b64decode(decrypted_text)
                            response["data"] = json.loads(base64_decoded.decode("utf-8"))
                            response["message"] = "Decrypted base64-encoded JSON"
                        except Exception as e:
                            logger.warning(f"Base64-decoded JSON fallback failed: {e}")
                            # 3. Fall back to base64 string
                            response["metadata"]["base64_encoded"] = base64.b64encode(decrypted_bytes).decode("utf-8")
                            response["message"] = "Decrypted content is not JSON. Returning base64."
                except UnicodeDecodeError:
                    response["metadata"]["base64_encoded"] = base64.b64encode(decrypted_bytes).decode("utf-8")
                    response["message"] = "Decrypted binary content. Returned base64."

            except Exception as e:
                logger.error(f"Decryption or parsing error: {e}")
                response.update({
                    "status": "received",
                    "message": "Processing attempted",
                    "metadata": {
                        "error": str(e),
                        "decryption_status": "failed"
                    }
                })

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Critical error in webhook: {e}")
        return jsonify({
            "status": "received",
            "message": "Message received"
        }), 200


# ---------------------- App Entry ---------------------- #
if __name__ == "__main__":
    logger.info(f"🚀 Starting WhatsApp webhook service on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
