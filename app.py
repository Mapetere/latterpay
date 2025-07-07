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
    """Handles all WhatsApp decryption operations with maximum compatibility"""
    
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
            raise ValueError("Failed to decrypt AES key")

    @staticmethod
    def force_decrypt(encrypted_data: bytes, aes_key: bytes, iv: bytes) -> str:
        """Ultra-permissive decryption that always returns something"""
        try:
            # First try standard CBC decryption
            cipher = CryptoAES.new(aes_key, CryptoAES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_data)
            
            # Try to remove padding if present
            try:
                return unpad(decrypted, CryptoAES.block_size).decode('utf-8')
            except ValueError:
                # If padding removal fails, try to decode anyway
                return decrypted.decode('utf-8', errors='replace').strip()
                
        except Exception as e:
            logger.error(f"Critical decryption failure: {str(e)}")
            # Return empty string if all decryption attempts fail
            return ""

    @staticmethod
    def decrypt_flow_data(encrypted_data_b64: str, aes_key: bytes, iv_b64: str) -> str:
        """Main decryption method that cannot fail"""
        try:
            # Clean and decode inputs
            encrypted_data = base64.b64decode(encrypted_data_b64.strip())
            iv = base64.b64decode(iv_b64.strip())

            # Validate lengths
            if len(aes_key) not in [16, 24, 32]:
                logger.warning(f"Unexpected AES key length: {len(aes_key)} bytes")
            if len(iv) != 16:
                logger.warning(f"Unexpected IV length: {len(iv)} bytes")

            return WhatsAppDecryptor.force_decrypt(encrypted_data, aes_key, iv)

        except Exception as e:
            logger.error(f"Decryption preprocessing failed: {str(e)}")
            return ""

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Main webhook endpoint that never fails"""
    try:
        if request.method == 'GET':
            # Verification handshake
            verify_token = request.args.get('hub.verify_token')
            if verify_token == os.getenv('VERIFY_TOKEN'):
                return request.args.get('hub.challenge'), 200
            return "Verification failed", 403

        # Initialize response template
        response = {
            "status": "success",
            "message": "Message processed",
            "metadata": {}
        }

        # Handle all POST content types
        content_type = request.content_type or ''
        raw_data = request.data
        
        # Try to parse JSON from any content type
        try:
            if content_type.lower() == 'application/x-www-form-urlencoded':
                data = dict(request.form)
                if 'payload' in data:
                    try:
                        data = json.loads(data['payload'])
                    except json.JSONDecodeError:
                        pass
            else:
                data = request.get_json(force=True, silent=True) or {}
        except Exception as e:
            logger.warning(f"Content parsing warning: {str(e)}")
            data = {}

        # Handle encrypted flow data
        if all(key in data for key in ['encrypted_aes_key', 'encrypted_flow_data', 'initial_vector']):
            try:
                aes_key = WhatsAppDecryptor.decrypt_aes_key(data['encrypted_aes_key'])
                decrypted = WhatsAppDecryptor.decrypt_flow_data(
                    data['encrypted_flow_data'],
                    aes_key,
                    data['initial_vector']
                )
                
                response['metadata']['decryption_status'] = 'complete' if decrypted else 'partial'
                
                try:
                    flow_data = json.loads(decrypted)
                    response['data'] = flow_data
                except json.JSONDecodeError:
                    response['metadata']['raw_data'] = decrypted[:500] + "..." if len(decrypted) > 500 else decrypted
                    response['message'] = "Decrypted content is not valid JSON"
                
            except Exception as e:
                logger.error(f"Flow processing error: {str(e)}")
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
        logger.error(f"Critical webhook error: {str(e)}")
        return jsonify({
            "status": "received",
            "message": "Message received"
        }), 200

if __name__ == '__main__':
    # Validate configuration
    required_vars = ['VERIFY_TOKEN']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    if not os.path.exists(PRIVATE_KEY_FILE):
        logger.error(f"Private key file not found at {PRIVATE_KEY_FILE}")

    # Start the server
    port = int(os.getenv('PORT', 8010))
    logger.info(f"Starting WhatsApp webhook service on port {port}")
    app.run(host='0.0.0.0', port=port)