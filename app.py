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

class EncryptionManager:
    """Handles all encryption/decryption operations with flexible padding support"""
    
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
    def decrypt_with_padding(encrypted_data: bytes, aes_key: bytes, iv: bytes) -> str:
        """Try multiple padding schemes to decrypt data"""
        padding_schemes = [
            ('PKCS7', lambda d: unpad(d, CryptoAES.block_size)),
            ('ISO7816', EncryptionManager.iso7816_unpad),
            ('Zero', lambda d: d.rstrip(b'\x00')),
            ('None', lambda d: d)
        ]

        cipher = CryptoAES.new(aes_key, CryptoAES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted_data)

        for name, unpadder in padding_schemes:
            try:
                plaintext = unpadder(decrypted).decode('utf-8')
                if plaintext.strip():  # Only accept if we get valid content
                    logger.info(f"Success with {name} padding")
                    return plaintext
            except Exception as e:
                continue

        raise ValueError("All padding schemes failed")

    @staticmethod
    def iso7816_unpad(data: bytes) -> bytes:
        """ISO/IEC 7816-4 padding removal"""
        if len(data) == 0:
            return data
        pad_len = data[-1]
        if data[-pad_len:] == b'\x80' + bytes([0]*(pad_len-1)):
            return data[:-pad_len]
        return data

    @staticmethod
    def decrypt_flow_data(encrypted_data_b64: str, aes_key: bytes, iv_b64: str) -> str:
        """Main decryption method with comprehensive error handling"""
        try:
            # Clean and decode inputs
            encrypted_data = base64.b64decode(encrypted_data_b64.strip())
            iv = base64.b64decode(iv_b64.strip())

            # Validate lengths
            if len(aes_key) not in [16, 24, 32]:
                raise ValueError(f"Invalid AES key length: {len(aes_key)} bytes")
            if len(iv) != 16:
                raise ValueError(f"Invalid IV length: {len(iv)} bytes")

            return EncryptionManager.decrypt_with_padding(encrypted_data, aes_key, iv)

        except Exception as e:
            logger.error(f"Decryption failed | Key: {aes_key.hex()[:6]}... | IV: {iv_b64[:10]}... | Data: {encrypted_data_b64[:20]}...")
            raise ValueError(f"Decryption failed: {str(e)}")

class WhatsAppWebhook:
    """Handles WhatsApp webhook processing"""
    
    @staticmethod
    def process_encrypted_flow(enc_key: str, enc_data: str, iv: str):
        """Process encrypted WhatsApp flow data"""
        try:
            aes_key = EncryptionManager.decrypt_aes_key(enc_key)
            decrypted_json = EncryptionManager.decrypt_flow_data(enc_data, aes_key, iv)
            
            logger.debug(f"Decrypted flow data: {decrypted_json}")
            data = json.loads(decrypted_json)
            
            # Process different flow actions
            action = data.get('action')
            if action == 'INIT':
                return {"status": "Flow initialized"}
            elif action == 'data_exchange':
                return {"status": "Data processed", "user_data": data.get('data')}
            else:
                return {"status": "Unknown action", "action": action}

        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in decrypted data")
        except Exception as e:
            logger.error(f"Flow processing error: {str(e)}")
            raise

    @staticmethod
    def verify_webhook(request):
        """Verify webhook subscription"""
        verify_token = request.args.get('hub.verify_token')
        if verify_token == os.getenv('VERIFY_TOKEN'):
            return request.args.get('hub.challenge'), 200
        return "Verification failed", 403

@app.route('/webhook', methods=['GET', 'POST'])
def webhook_handler():
    """Main webhook endpoint"""
    try:
        if request.method == 'GET':
            return WhatsAppWebhook.verify_webhook(request)

        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        # Handle encrypted flow data
        if all(key in data for key in ['encrypted_aes_key', 'encrypted_flow_data', 'initial_vector']):
            try:
                result = WhatsAppWebhook.process_encrypted_flow(
                    data['encrypted_aes_key'],
                    data['encrypted_flow_data'],
                    data['initial_vector']
                )
                return jsonify(result)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                return jsonify({"error": "Internal server error"}), 500

        # Handle regular messages
        return jsonify({"status": "Regular message received"}), 200

    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # Validate required environment variables
    required_vars = ['VERIFY_TOKEN']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

    # Start the application
    port = int(os.getenv('PORT', 8000))
    logger.info(f"Starting WhatsApp webhook service on port {port}")
    app.run(host='0.0.0.0', port=port)