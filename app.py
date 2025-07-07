import os
import json
import base64
import logging
from flask import Flask, request, jsonify
from Crypto.Cipher import AES as CryptoAES
from Crypto.Util.Padding import pad, unpad
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('whatsapp_webhook.log')
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
PRIVATE_KEY_FILE = os.getenv('PRIVATE_KEY_FILE', 'private.pem')
PRIVATE_KEY_PASSPHRASE = os.getenv('PRIVATE_KEY_PASSPHRASE')

class WhatsAppDecryptor:
    """Handles WhatsApp message decryption with robust error handling"""
    
    @staticmethod
    def decrypt_aes_key(encrypted_key_b64: str) -> bytes:
        """Decrypt the AES key using RSA private key"""
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
            logger.error(f"AES key decryption failed: {str(e)}")
            raise

    @staticmethod
    def decrypt_flow_data(encrypted_data_b64: str, aes_key: bytes, iv_b64: str) -> str:
        """Decrypt WhatsApp flow data with padding handling"""
        try:
            # Clean and decode inputs
            encrypted_data = base64.b64decode(encrypted_data_b64.strip())
            iv = base64.b64decode(iv_b64.strip())

            # Validate lengths
            if len(aes_key) not in [16, 24, 32]:
                raise ValueError(f"Invalid AES key length: {len(aes_key)} bytes")
            if len(iv) != 16:
                raise ValueError(f"Invalid IV length: {len(iv)} bytes")

            # Handle decryption with padding recovery
            cipher = CryptoAES.new(aes_key, CryptoAES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_data)
            
            try:
                return unpad(decrypted, CryptoAES.block_size).decode('utf-8')
            except ValueError as e:
                # If padding fails, try to process without unpadding
                logger.warning(f"Padding error, attempting raw decryption: {str(e)}")
                return decrypted.decode('utf-8').strip()

        except Exception as e:
            logger.error(f"Decryption failed | Key: {aes_key.hex()[:6]}... | IV: {iv_b64[:10]}... | Data: {encrypted_data_b64[:20]}...")
            raise

@app.route('/webhook', methods=['GET', 'POST'])
def webhook_handler():
    """Main WhatsApp webhook endpoint with proper HTTP responses"""
    try:
        if request.method == 'GET':
            # Verification handshake
            verify_token = request.args.get('hub.verify_token')
            if verify_token == os.getenv('VERIFY_TOKEN'):
                return request.args.get('hub.challenge'), 200
            return "Verification failed", 403

        # Ensure proper Content-Type
        if request.content_type != 'application/json':
            logger.error(f"Invalid Content-Type: {request.content_type}")
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 415

        try:
            data = request.get_json()
            if not data:
                return jsonify({"status": "error", "message": "Empty request body"}), 400
        except Exception as e:
            logger.error(f"JSON parsing failed: {str(e)}")
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        # Handle encrypted flow data
        if all(key in data for key in ['encrypted_aes_key', 'encrypted_flow_data', 'initial_vector']):
            try:
                aes_key = WhatsAppDecryptor.decrypt_aes_key(data['encrypted_aes_key'])
                decrypted = WhatsAppDecryptor.decrypt_flow_data(
                    data['encrypted_flow_data'],
                    aes_key,
                    data['initial_vector']
                )
                
                # Always return 200 even if decrypted content has issues
                try:
                    flow_data = json.loads(decrypted)
                    logger.info(f"Decrypted flow data: {json.dumps(flow_data, indent=2)}")
                    return jsonify({"status": "success", "data": flow_data}), 200
                except json.JSONDecodeError:
                    logger.warning(f"Decrypted content is not JSON: {decrypted[:200]}...")
                    return jsonify({"status": "success", "raw_data": decrypted[:200]}), 200

            except Exception as e:
                logger.error(f"Flow processing error: {str(e)}")
                # Return 200 to acknowledge receipt even if processing fails
                return jsonify({"status": "received", "message": "Processing attempted"}), 200

        # Handle regular messages
        return jsonify({"status": "success", "message": "Regular message received"}), 200

    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == '__main__':
    # Validate configuration
    required_vars = ['VERIFY_TOKEN']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

    if not os.path.exists(PRIVATE_KEY_FILE):
        raise FileNotFoundError(f"Private key file not found at {PRIVATE_KEY_FILE}")

    # Start the server
    port = int(os.getenv('PORT', 8000))
    logger.info(f"Starting WhatsApp webhook service on port {port}")
    app.run(host='0.0.0.0', port=port)